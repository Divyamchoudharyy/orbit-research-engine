from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
import threading

from dotenv import load_dotenv

# Environment must be loaded before importing modules that inspect DATABASE_URL.
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from src.api.limiter import limiter
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
                # A pending review without an expiry cannot be monitored
                # safely; treat it as expired and finalize through the claim.
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _recover_orphaned_hil_jobs()
    yield


app = FastAPI(
    title="ORBIT Deep Research Engine",
    description=(
        "Multi-agent research pipeline: "
        "Planner → Researcher → Critic → Writer"
    ),
    version="1.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(
    RateLimitExceeded,
    _rate_limit_exceeded_handler,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(research_router)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")
