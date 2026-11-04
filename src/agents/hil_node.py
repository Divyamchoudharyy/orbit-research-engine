
from langgraph.types import interrupt

from src.graph.state import ResearchState
from src.persistence.db import log_hil_decision


def hil_node(state: ResearchState) -> dict:
    """
    Pause the research workflow when the Critic identifies gaps.

    Research limits are based on additional research rounds,
    not the total number of Researcher executions.

    Supported decisions:
        continue
        finalize
        auto_capped
        none
    """

    # --------------------------------------------------
    # 1. READ WORKFLOW STATE
    # --------------------------------------------------

    gaps = state.get("gaps_identified") or []

    research_rounds = state.get("research_rounds", 0)

    max_research_rounds = state.get("max_research_rounds", 3)

    job_id = state.get("job_id")

    # --------------------------------------------------
    # 2. NO GAPS: SKIP HUMAN REVIEW
    # --------------------------------------------------

    if not gaps:
        return {
            "hil_decision": "none"
        }

    # --------------------------------------------------
    # 3. CHECK RESEARCH ROUND LIMIT
    # --------------------------------------------------

    if research_rounds >= max_research_rounds:
        return {
            "hil_decision": "auto_capped"
        }

    # --------------------------------------------------
    # 4. REQUEST HUMAN APPROVAL
    # --------------------------------------------------

    next_round = research_rounds + 1

    decision = interrupt({
        "question": "Continue researching or finalize now?",
        "gaps": gaps,
        "iteration": next_round,
        "max_iterations": max_research_rounds,
        "research_rounds_completed": research_rounds,
    })

    # --------------------------------------------------
    # 5. VALIDATE USER DECISION
    # --------------------------------------------------

    if not isinstance(decision, str):
        raise ValueError(
            "Human review decision must be a string."
        )

    decision = decision.strip().lower()

    allowed_decisions = {
        "continue",
        "finalize",
    }

    if decision not in allowed_decisions:
        raise ValueError(
            f"Invalid human review decision: {decision}. "
            f"Expected one of: {allowed_decisions}"
        )

    # --------------------------------------------------
    # 6. RECORD HUMAN DECISION
    # --------------------------------------------------

    if job_id:
        log_hil_decision(
            job_id=job_id,
            iteration=next_round,
            decision=decision,
            gaps=gaps,
        )

    # --------------------------------------------------
    # 7. RETURN DECISION TO SUPERVISOR
    # --------------------------------------------------

    return {
        "hil_decision": decision
    }
