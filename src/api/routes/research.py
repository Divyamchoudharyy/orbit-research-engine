import uuid
import json
import asyncio
import threading
import time
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
from src.api.models import ReasearchRequest, ReasearchJobResponse, JobResultResponse, HILStatusResponse, HILDecisionRequest
from src.persistence.db import (
    create_job, get_job, get_hil_payload,
    update_job_status, set_job_awaiting_human, log_hil_decision
)
from src.api.limiter import limiter          # shared instance — must match app.state.limiter
from src.api.stream_manager import stream_manager
from sse_starlette.sse import EventSourceResponse
from src.graph.pipeline import build_graph
from langgraph.types import Command

router = APIRouter()
_DEPTH_ESTIMATES = {
    "quick": 20,
    "standard": 45,
    "deep": 90
}

# Build graph once at module load — not per request
_graph = build_graph()


# ── Internal task helpers (run in thread pool via BackgroundTasks) ─────────────

def _finalize_job(job_id: str, result: dict) -> None:
    update_job_status(
        job_id,
        status="complete",
        result={
            "report": result.get("final_report", ""),
            "sources": result.get("sources", []),
        },
        agent_turns=result.get("research_iterations", 0)
    )


def _schedule_hil_timeout(job_id: str, expires_at: str) -> None:
    """Spawn a daemon thread that auto-finalizes if HIL timeout expires."""
    def _timeout_worker():
        try:
            target_dt = datetime.fromisoformat(expires_at)
            while True:
                remaining = (target_dt - datetime.now(timezone.utc)).total_seconds()
                if remaining <= 0:
                    break
                time.sleep(min(remaining, 5.0))
                job = get_job(job_id)
                if not job or job["status"] != "awaiting_human":
                    return  # resolved by user
            job = get_job(job_id)
            if job and job["status"] == "awaiting_human":
                log_hil_decision(
                    job_id=job_id,
                    iteration=job.get("agent_turns", 0),
                    decision="auto_finalize",
                    gaps=[]
                )
                _run_research_resume(job_id, "finalize")
        except Exception:
            pass

    threading.Thread(target=_timeout_worker, daemon=True).start()


def _run_research(job_id: str, query: str, depth: str) -> None:
    """Execute the full research pipeline in a background thread."""
    update_job_status(job_id, "running")
    try:
        result = _graph.invoke(
            {
                "query": query,
                "depth": depth,
                "messages": [],
                "sub_questions": [],
                "research_findings": [],
                "gaps_identified": [],
                "research_iterations": 0,
                "final_report": "",
                "sources": [],
                "next_agent": "",
                "job_id": job_id,
                "hil_decision": "none",
            },
            config={"configurable": {"thread_id": job_id}},
        )

        if "__interrupt__" in result and result["__interrupt__"]:
            interrupt_val = result["__interrupt__"][0].value
            gaps = interrupt_val.get("gaps", [])
            iteration = interrupt_val.get("iteration", 0)
            expires_at = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
            set_job_awaiting_human(job_id, gaps, iteration, expires_at)
            _schedule_hil_timeout(job_id, expires_at)
            return

        _finalize_job(job_id, result)
    except Exception as e:
        update_job_status(job_id, "failed", error=str(e))


def _run_research_resume(job_id: str, decision: str) -> None:
    """Resume a paused (HIL) graph in a background thread."""
    update_job_status(job_id, "running")
    try:
        result = _graph.invoke(
            Command(resume=decision),
            config={"configurable": {"thread_id": job_id}}
        )

        if "__interrupt__" in result and result["__interrupt__"]:
            interrupt_val = result["__interrupt__"][0].value
            gaps = interrupt_val.get("gaps", [])
            iteration = interrupt_val.get("iteration", 0)
            expires_at = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
            set_job_awaiting_human(job_id, gaps, iteration, expires_at)
            _schedule_hil_timeout(job_id, expires_at)
            return

        _finalize_job(job_id, result)
    except Exception as e:
        update_job_status(job_id, "failed", error=str(e))


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/research", response_model=ReasearchJobResponse, status_code=202)
@limiter.limit("5/hour")
async def create_research_job(request: Request, body: ReasearchRequest, background_tasks: BackgroundTasks):
    if body.depth not in ("quick", "standard", "deep"):
        raise HTTPException(status_code=422, detail="depth must be 'quick', 'standard', or 'deep'")
    job_id = str(uuid.uuid4())
    create_job(job_id, body.query, body.depth)

    # FastAPI runs sync background tasks in a thread-pool executor — non-blocking
    background_tasks.add_task(_run_research, job_id, body.query, body.depth)

    return ReasearchJobResponse(
        job_id=job_id,
        status="pending",
        estimated_seconds=_DEPTH_ESTIMATES.get(body.depth, 45),
    )


@router.get("/jobs/{job_id}/status", response_model=HILStatusResponse)
def get_job_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    hil_payload = None
    if job["status"] == "awaiting_human":
        hil_payload = get_hil_payload(job_id)

    return HILStatusResponse(
        job_id=job["job_id"],
        status=job["status"],
        created_at=job["created_at"],
        updated_at=job["updated_at"],
        hil_payload=hil_payload
    )


@router.post("/jobs/{job_id}/decision", status_code=202)
async def submit_job_decision(job_id: str, body: HILDecisionRequest, background_tasks: BackgroundTasks):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job["status"] != "awaiting_human":
        raise HTTPException(status_code=400, detail=f"Job {job_id} is not awaiting human feedback")

    background_tasks.add_task(_run_research_resume, job_id, body.decision)
    return {"job_id": job_id, "status": "running"}


@router.get("/jobs/{job_id}/stream")
async def stream_job_events(job_id: str, request: Request):
    """Server-Sent Events endpoint — pushes real-time agent logs to the Streamlit UI."""
    queue = stream_manager.subscribe(job_id)

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield {
                        "event": "message",
                        "data": json.dumps(data)
                    }
                except asyncio.TimeoutError:
                    # Heartbeat — prevents reverse-proxies from dropping idle connections
                    yield {
                        "event": "ping",
                        "data": ""
                    }
        finally:
            stream_manager.unsubscribe(job_id, queue)

    return EventSourceResponse(event_generator())


@router.get("/jobs/{job_id}/result", response_model=JobResultResponse)
def get_job_result(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    result_data = {}
    if job["result"]:
        result_data = json.loads(job["result"])

    return JobResultResponse(
        job_id=job["job_id"],
        query=job["query"],
        status=job["status"],
        report=result_data.get("report"),
        sources=result_data.get("sources"),
        agent_turns=job["agent_turns"],
        error=job["error"],
        created_at=job["created_at"],
        updated_at=job["updated_at"],
    )
