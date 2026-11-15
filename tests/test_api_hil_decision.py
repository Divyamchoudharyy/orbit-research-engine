import asyncio

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from src.api.models import HILDecisionRequest
from src.api.routes import research as research_routes


class FakeBackgroundTasks:
    def __init__(self):
        self.tasks = []

    def add_task(self, function, *args, **kwargs):
        self.tasks.append((function, args, kwargs))


def test_hil_decision_rejects_invalid_value():
    with pytest.raises(ValidationError):
        HILDecisionRequest(decision="skip")


def test_hil_decision_returns_conflict_if_claim_was_lost(monkeypatch):
    monkeypatch.setattr(
        research_routes,
        "get_job",
        lambda job_id: {"job_id": job_id, "status": "running"},
    )
    monkeypatch.setattr(
        research_routes,
        "claim_hil_decision",
        lambda job_id, decision: False,
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            research_routes.submit_job_decision(
                "job-1",
                HILDecisionRequest(decision="continue"),
                FakeBackgroundTasks(),
            )
        )

    assert error.value.status_code == 409


def test_hil_decision_claims_before_scheduling_resume(monkeypatch):
    calls = []
    background = FakeBackgroundTasks()

    monkeypatch.setattr(
        research_routes,
        "get_job",
        lambda job_id: {"job_id": job_id, "status": "awaiting_human"},
    )
    monkeypatch.setattr(
        research_routes,
        "claim_hil_decision",
        lambda job_id, decision: calls.append((job_id, decision)) or True,
    )

    response = asyncio.run(
        research_routes.submit_job_decision(
            "job-2",
            HILDecisionRequest(decision="finalize"),
            background,
        )
    )

    assert calls == [("job-2", "finalize")]
    assert response == {
        "job_id": "job-2",
        "status": "running",
        "decision": "finalize",
    }
    assert len(background.tasks) == 1
    assert background.tasks[0][1] == ("job-2", "finalize")
