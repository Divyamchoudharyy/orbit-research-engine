"""Shared execution functions used by the API and Celery workers."""

import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from langgraph.types import Command

from src.graph.pipeline import build_graph, create_initial_state
from src.persistence.db import set_job_awaiting_human, update_job_status

_graph = None
_graph_lock = threading.Lock()


def get_graph():
    """Build one graph per process, lazily, rather than at import time."""
    global _graph
    if _graph is None:
        with _graph_lock:
            if _graph is None:
                _graph = build_graph()
    return _graph


def _interrupt_payload(result: dict) -> dict | None:
    interrupts = result.get("__interrupt__") or []
    if not interrupts:
        return None

    value = getattr(interrupts[0], "value", None)
    if not isinstance(value, dict):
        raise RuntimeError("Graph returned an invalid HIL interrupt payload.")

    return value


def _persist_result(job_id: str, result: dict) -> dict[str, Any]:
    interrupt = _interrupt_payload(result)

    if interrupt is not None:
        gaps = interrupt.get("gaps") or []
        iteration = int(interrupt.get("iteration") or 0)
        expires_at = (
            datetime.now(timezone.utc) + timedelta(minutes=30)
        ).isoformat()

        set_job_awaiting_human(
            job_id=job_id,
            gaps=gaps,
            iteration=iteration,
            expires_at=expires_at,
        )
        return {
            "interrupted": True,
            "gaps": gaps,
            "iteration": iteration,
            "expires_at": expires_at,
        }

    update_job_status(
        job_id,
        status="complete",
        result={
            "report": result.get("final_report", ""),
            "sources": result.get("sources", []),
        },
        agent_turns=result.get("research_iterations", 0),
        error=None,
    )
    return {"interrupted": False}


def run_initial_research(job_id: str, query: str, depth: str) -> dict:
    """Start a fresh graph run and persist either its interrupt or result."""
    update_job_status(
        job_id,
        status="running",
        result=None,
        error=None,
        agent_turns=0,
    )
    result = get_graph().invoke(
        create_initial_state(
            query=query,
            depth=depth,
            job_id=job_id,
        ),
        config={"configurable": {"thread_id": job_id}},
    )
    return _persist_result(job_id, result)


def resume_research(job_id: str, decision: str) -> dict:
    """Resume the existing checkpoint for a previously interrupted job."""
    if decision not in {"continue", "finalize"}:
        raise ValueError("decision must be 'continue' or 'finalize'")

    # Do not reset agent_turns, report, or prior error state here.
    update_job_status(job_id, status="running")
    result = get_graph().invoke(
        Command(resume=decision),
        config={"configurable": {"thread_id": job_id}},
    )
    return _persist_result(job_id, result)
