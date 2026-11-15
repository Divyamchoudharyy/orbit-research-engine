from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
import threading
import os

from dotenv import load_dotenv

# Environment must be loaded before importing modules that inspect DATABASE_URL.
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from src.api.limiter import limiter
from src.api.security import validate_production_configuration
from src.api.routes.research import (
    router as research_router,
    _run_research_resume,
    _schedule_hil_timeout,
)
from src.api.routes.health import router as health_router
from src.persistence.db import (
    claim_hil_decision,
    get_jobs_by_status,
    init_db,
    update_job_status,
)

logger = logging.getLogger(__name__)


def _recover_orphaned_hil_jobs() -> None:
    """Restore timers or atomically auto-finalize expired HIL jobs."""
    for job in get_jobs_by_status("awaiting_human"):
        job_id = job["job_id"]
        expires_at = job.get("hil_expires_at")

        try:
            if expires_at:
                expires_dt = datetime.fromisoformat(expires_at)
                if expires_dt.tzinfo is None:
                    expires_dt = expires_dt.replace(tzinfo=timezone.utc)
            else:
                expires_dt = datetime.min.replace(tzinfo=timezone.utc)

            if expires_dt <= datetime.now(timezone.utc):
                if claim_hil_decision(job_id, "auto_finalize"):
                    threading.Thread(
                        target=_run_research_resume,
                        args=(job_id, "finalize"),
                        name=f"orbit-hil-recovery-{job_id[:8]}",
                        daemon=True,
                    ).start()
            else:
                _schedule_hil_timeout(job_id, expires_at)

        except Exception:
            logger.exception("Could not recover HIL job %s", job_id)


def _mark_interrupted_jobs_failed() -> None:
    """Avoid leaving jobs permanently marked running after a process restart."""
    for job in get_jobs_by_status("running") + get_jobs_by_status("pending"):
        update_job_status(
            job["job_id"],
            "failed",
            error="The API restarted before this job completed. Please submit it again.",
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_production_configuration()
    init_db()
    _mark_interrupted_jobs_failed()
    _recover_orphaned_hil_jobs()
    yield


app = FastAPI(
    title="ORBIT Deep Research Engine",
    description=(
        "Multi-agent research pipeline: "
        "Planner → Researcher → Critic → Writer"
    ),
    version="1.2.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(
    RateLimitExceeded,
    _rate_limit_exceeded_handler,
)

cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:8501",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=False,
)

app.include_router(health_router)
app.include_router(research_router)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")
