import os
from langgraph.types import interrupt
from src.graph.state import ReasearchState
from src.persistence.db import log_hil_decision

def hil_node(state: ReasearchState) -> dict:
    gaps = state.get("gaps_identified", [])
    iteration = state.get("research_iterations", 0)
    job_id = state.get("job_id")

    # If there are no gaps or we've reached/exceeded the max iteration limit (3),
    # do not interrupt. Just proceed.
    if not gaps or iteration >= 3:
        return {"hil_decision": "none"}

    # Pause execution and request user feedback.
    # The interrupt function yields control and returns the value provided on resume.
    decision = interrupt({
        "question": "Continue researching or finalize now?",
        "gaps": gaps,
        "iteration": iteration,
        "max_iterations": 3,
    })

    # Expected values for decision: "continue" | "finalize" | "auto_finalize"
    if not decision:
        decision = "finalize"

    # Log the decision directly to the database audit trail
    if job_id:
        log_hil_decision(
            job_id=job_id,
            iteration=iteration,
            decision=decision,
            gaps=gaps,
        )

    return {"hil_decision": decision}
