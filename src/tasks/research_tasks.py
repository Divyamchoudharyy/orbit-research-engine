"""Celery entry points for ORBIT research jobs."""

import logging
import threading
import time
from datetime import datetime, timezone

from src.api.celery_app import celery_app
from src.persistence.db import (
    claim_hil_decision,
    get_job,
    update_job_status,
)
from src.services.research_runner import (
    resume_research,
    run_initial_research,
)

logger = logging.getLogger(__name__)


def _schedule_hil_timeout(job_id: str, expires_at: str) -> None:
    """Recover a pending HIL decision from a worker-local timeout thread."""

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
                resume_research_task.delay(job_id, "finalize")

        except Exception:
            logger.exception(
                "Celery HIL timeout worker failed for job %s",
                job_id,
            )

    threading.Thread(
        target=_timeout_worker,
        name=f"orbit-celery-hil-timeout-{job_id[:8]}",
        daemon=True,
    ).start()


@celery_app.task(name="run_research_pipeline", acks_late=True)
def run_research_task(job_id: str, query: str, depth: str) -> None:
    try:
        outcome = run_initial_research(job_id, query, depth)
        if outcome["interrupted"]:
            _schedule_hil_timeout(job_id, outcome["expires_at"])
    except Exception as exc:
        logger.exception("Celery research task failed for job %s", job_id)
        update_job_status(job_id, "failed", error=str(exc))
        raise


@celery_app.task(name="resume_research_pipeline", acks_late=True)
def resume_research_task(job_id: str, decision: str) -> None:
    try:
        outcome = resume_research(job_id, decision)
        if outcome["interrupted"]:
            _schedule_hil_timeout(job_id, outcome["expires_at"])
    except Exception as exc:
        logger.exception("Celery resume task failed for job %s", job_id)
        update_job_status(job_id, "failed", error=str(exc))
        raise
