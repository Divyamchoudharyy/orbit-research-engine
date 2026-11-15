from fastapi import APIRouter, HTTPException

from src.persistence.db import get_jobs_by_status

router = APIRouter()


@router.get("/health")
def health_check():
    """Liveness probe: confirms the API process is responding."""
    return {"status": "ok", "version": "1.2.0"}


@router.get("/ready")
def readiness_check():
    """Readiness probe: confirms the configured persistence backend is reachable."""
    try:
        get_jobs_by_status("__readiness_probe__")
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Persistence backend is unavailable.",
        ) from exc
    return {"status": "ready", "version": "1.2.0"}
