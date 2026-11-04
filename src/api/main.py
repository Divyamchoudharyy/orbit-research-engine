from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from src.api.limiter import limiter          # shared instance
from src.api.routes.research import router as research_router
from src.api.routes.health import router as health_router
from src.persistence.db import init_db  # triggers table creation on startup

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs once at startup - creates DB + jobs table if not exists
    init_db()
    
    # Recovery check: scan for orphaned "awaiting_human" jobs on startup
    try:
        from src.persistence.db import get_jobs_by_status, log_hil_decision
        from src.api.routes.research import _schedule_hil_timeout, _run_research_resume
        import threading
        from datetime import datetime, timezone
        
        orphaned = get_jobs_by_status("awaiting_human")
        for job in orphaned:
            expires_at = job.get("hil_expires_at")
            if expires_at:
                try:
                    exp_dt = datetime.fromisoformat(expires_at)
                    if exp_dt < datetime.now(timezone.utc):
                        # Already expired — auto-finalize immediately in a background thread
                        log_hil_decision(
                            job_id=job["job_id"],
                            iteration=job.get("agent_turns", 0),
                            decision="auto_finalize",
                            gaps=[]
                        )
                        threading.Thread(
                            target=_run_research_resume,
                            args=(job["job_id"], "finalize"),
                            daemon=True
                        ).start()
                    else:
                        # Not yet expired — re-spawn the timeout thread
                        _schedule_hil_timeout(job["job_id"], expires_at)
                except Exception:
                    pass
    except Exception:
        pass
        
    yield


app = FastAPI(
    title="ORBIT Deep Research Engine",
    description="Multi-agent research pipeline: Planner → Researcher → Critic → Writer",
    version="1.0.0",
    lifespan=lifespan,
)

# slowapi — must be set AFTER app is defined
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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
