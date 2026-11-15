"""Shared API-key authentication for protected ORBIT endpoints."""

import hmac
import os

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

API_KEY = os.getenv("ORBIT_API_KEY")
ORBIT_ENV = os.getenv("ORBIT_ENV", "development").strip().lower()
_bearer = HTTPBearer(auto_error=False)


def validate_production_configuration() -> None:
    """Fail closed when a production deployment has no API key."""
    if ORBIT_ENV == "production" and not API_KEY:
        raise RuntimeError(
            "ORBIT_API_KEY must be configured when ORBIT_ENV=production."
        )


def require_api_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Require a valid Bearer token whenever an API key is configured."""
    if not API_KEY:
        if ORBIT_ENV == "production":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="API authentication is not configured.",
            )
        return

    supplied = credentials.credentials if credentials else ""
    if not supplied or not hmac.compare_digest(supplied, API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid Bearer API key is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
