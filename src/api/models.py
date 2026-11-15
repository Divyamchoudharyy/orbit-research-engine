from typing import Literal

from pydantic import BaseModel, Field


class ReasearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=10_000)
    depth: Literal["quick", "standard", "deep"] = "standard"


class ReasearchJobResponse(BaseModel):
    """Returned immediately from POST /research."""

    job_id: str
    status: str
    estimated_seconds: int


class JobStatusResponse(BaseModel):
    """Returned from GET /jobs/{job_id}/status."""

    job_id: str
    status: str
    created_at: str
    updated_at: str


class HILPayload(BaseModel):
    gaps: list[str]
    iteration: int
    max_iterations: int
    expires_at: str


class HILStatusResponse(JobStatusResponse):
    """Job status with a pending human-review payload, when applicable."""

    hil_payload: HILPayload | None = None


class HILDecisionRequest(BaseModel):
    decision: Literal["continue", "finalize"]


class JobResultResponse(BaseModel):
    """Returned from GET /jobs/{job_id}/result."""

    job_id: str
    query: str
    status: str
    report: str | None = None
    sources: list[str] | None = None
    agent_turns: int | None = None
    error: str | None = None
    created_at: str
    updated_at: str
