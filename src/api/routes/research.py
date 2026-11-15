import asyncio
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from src.api.limiter import limiter
from src.api.security import require_api_key
from src.api.models import (
    HILDecisionRequest,
    HILStatusResponse,
    JobResultResponse,
    ReasearchJobResponse,
    ReasearchRequest,
)
from src.api.stream_manager import stream_manager
from src.persistence.db import (
    claim_hil_decision,
    create_job,
    get_hil_payload,
    get_job,
    update_job_status,
)
from src.services.research_runner import (
    resume_research,
    run_initial_research,
)

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(require_api_key)])

_DEPTH_ESTIMATES = {
    "quick": 20,
    "standard": 45,
    "deep": 90,
}


def _schedule_hil_timeout(job_id: str, expires_at: str) -> None:
    """Auto-finalize an unresolved HIL job after its persisted deadline."""

    def _timeout_worker():
        try:
            target_dt = datetime.fromisoformat(expires_at)
            if target_dt.tzinfo is None:
                target_dt = target_dt.replace(tzinfo=timezone.utc)

            while True:
                remaining = (
                    target_dt - datetime.now(timezone.utc)
                ).total_seconds()
                if remaining <= 0:
                    break

                time.sleep(min(remaining, 5.0))
                job = get_job(job_id)
                if not job or job["status"] != "awaiting_human":
                    return

            if claim_hil_decision(job_id, "auto_finalize"):
                _run_research_resume(job_id, "finalize")

        except Exception:
            logger.exception("HIL timeout worker failed for job %s", job_id)

    threading.Thread(
        target=_timeout_worker,
        name=f"orbit-hil-timeout-{job_id[:8]}",
        daemon=True,
    ).start()


def _run_research(job_id: str, query: str, depth: str) -> None:
    """Run a fresh research job in FastAPI's background thread pool."""
    try:
        outcome = run_initial_research(job_id, query, depth)
        if outcome["interrupted"]:
            _schedule_hil_timeout(job_id, outcome["expires_at"])
    except Exception as exc:
        logger.exception("Research execution failed for job %s", job_id)
        update_job_status(job_id, "failed", error=str(exc))


def _run_research_resume(job_id: str, decision: str) -> None:
    """Resume a previously interrupted graph execution."""
    try:
        outcome = resume_research(job_id, decision)
        if outcome["interrupted"]:
            _schedule_hil_timeout(job_id, outcome["expires_at"])
    except Exception as exc:
        logger.exception("Research resume failed for job %s", job_id)
        update_job_status(job_id, "failed", error=str(exc))


@router.post(
    "/research",
    response_model=ReasearchJobResponse,
    status_code=202,
)
@limiter.limit("5/hour")
async def create_research_job(
    request: Request,
    body: ReasearchRequest,
    background_tasks: BackgroundTasks,
):
    query = body.query.strip()
    if not query:
        raise HTTPException(status_code=422, detail="query must not be empty")

    if body.depth not in _DEPTH_ESTIMATES:
        raise HTTPException(
            status_code=422,
            detail="depth must be 'quick', 'standard', or 'deep'",
        )

    job_id = str(uuid.uuid4())
    create_job(job_id, query, body.depth)
    background_tasks.add_task(_run_research, job_id, query, body.depth)

    return ReasearchJobResponse(
        job_id=job_id,
        status="pending",
        estimated_seconds=_DEPTH_ESTIMATES[body.depth],
    )


@router.get("/jobs/{job_id}/status", response_model=HILStatusResponse)
def get_job_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    hil_payload = (
        get_hil_payload(job_id)
        if job["status"] == "awaiting_human"
        else None
    )

    return HILStatusResponse(
        job_id=job["job_id"],
        status=job["status"],
        created_at=job["created_at"],
        updated_at=job["updated_at"],
        hil_payload=hil_payload,
    )


@router.post("/jobs/{job_id}/decision", status_code=202)
async def submit_job_decision(
    job_id: str,
    body: HILDecisionRequest,
    background_tasks: BackgroundTasks,
):
    if not get_job(job_id):
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    claimed = claim_hil_decision(job_id, body.decision)
    if not claimed:
        raise HTTPException(
            status_code=409,
            detail=(
                "This job is no longer awaiting human feedback "
                "or its decision has already been claimed."
            ),
        )

    background_tasks.add_task(_run_research_resume, job_id, body.decision)
    return {
        "job_id": job_id,
        "status": "running",
        "decision": body.decision,
    }


@router.get("/jobs/{job_id}/stream")
async def stream_job_events(job_id: str, request: Request):
    """Stream progress events; always unsubscribe when the client disconnects."""
    if not get_job(job_id):
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    queue = stream_manager.subscribe(job_id)

    async def event_generator():
        try:
            while not await request.is_disconnected():
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield {
                        "event": "message",
                        "data": json.dumps(data, default=str),
                    }
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": ""}
        finally:
            stream_manager.unsubscribe(job_id, queue)

    return EventSourceResponse(event_generator())


@router.get("/jobs/{job_id}/result", response_model=JobResultResponse)
def get_job_result(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    result_data = {}
    if job.get("result"):
        try:
            result_data = json.loads(job["result"])
        except (TypeError, json.JSONDecodeError):
            logger.exception("Stored result JSON is invalid for job %s", job_id)
            raise HTTPException(
                status_code=500,
                detail="Stored research result is invalid.",
            )

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
