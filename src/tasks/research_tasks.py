import threading
import time
from datetime import datetime, timezone, timedelta
from src.api.celery_app import celery_app
from src.persistence.db import update_job_status, set_job_awaiting_human, log_hil_decision, get_job
from src.graph.pipeline import build_graph
from langgraph.types import Command

# Build graph once
_graph = build_graph()

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
    def _timeout_worker():
        try:
            target_dt = datetime.fromisoformat(expires_at)
            while True:
                now = datetime.now(timezone.utc)
                remaining = (target_dt - now).total_seconds()
                if remaining <= 0:
                    break
                sleep_time = min(remaining, 5.0)
                time.sleep(sleep_time)
                
                # Check status
                job = get_job(job_id)
                if not job or job["status"] != "awaiting_human":
                    return # resolved by user or deleted
            
            # Timeout expired. Auto-finalize.
            job = get_job(job_id)
            if job and job["status"] == "awaiting_human":
                log_hil_decision(
                    job_id=job_id,
                    iteration=job.get("agent_turns", 0),
                    decision="auto_finalize",
                    gaps=[]
                )
                # Dispatch celery task to resume
                resume_research_task.delay(job_id, "finalize")
        except Exception:
            pass
            
    t = threading.Thread(target=_timeout_worker, daemon=True)
    t.start()

@celery_app.task(name="run_research_pipeline")
def run_research_task(job_id: str, query: str, depth: str) -> None:
    update_job_status(job_id, "running")
    try:
        result = _graph.invoke({
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
                config={"configurable":{"thread_id": job_id}},
            )
            
        if "__interrupt__" in result and result["__interrupt__"]:
            # Pause execution and set job status
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

@celery_app.task(name="resume_research_pipeline")
def resume_research_task(job_id: str, decision: str) -> None:
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
