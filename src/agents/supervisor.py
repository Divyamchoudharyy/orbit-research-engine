
from langgraph.graph import END
from langgraph.types import Command

from src.graph.state import ResearchState


def supervisor_node(state: ResearchState) -> Command:
    """
    Deterministic controller for the ORBIT research workflow.

    Routing order:
    1. Finish if a final report already exists.
    2. Create a research plan if none exists.
    3. Execute pending planned questions.
    4. Execute pending follow-up questions.
    5. Evaluate research if critique is incomplete.
    6. Process human approval decisions.
    7. Finalize when no further research is required.
    """

    # --------------------------------------------------
    # 1. Read current workflow state
    # --------------------------------------------------

    sub_questions = state.get("sub_questions") or []

    planned_index = state.get("planned_question_index", 0)

    follow_up_questions = state.get("follow_up_questions") or []

    follow_up_index = state.get("follow_up_question_index", 0)

    research_rounds = state.get("research_rounds", 0)

    max_research_rounds = state.get("max_research_rounds", 3)

    gaps = state.get("gaps_identified") or []

    critique_complete = state.get("critique_complete", False)

    hil_decision = (state.get("hil_decision") or "none").strip().lower()

    # --------------------------------------------------
    # 2. Final report already exists
    # --------------------------------------------------

    if state.get("final_report"):
        return Command(
            goto=END,
            update={"next_agent": "FINISH"},
        )

    # --------------------------------------------------
    # 3. No research plan exists
    # --------------------------------------------------

    if not sub_questions:
        return Command(
            goto="planner",
            update={"next_agent": "planner"},
        )

    # --------------------------------------------------
    # 4. Execute pending planned questions
    # --------------------------------------------------

    if planned_index < len(sub_questions):
        return Command(
            goto="researcher",
            update={"next_agent": "researcher"},
        )

    # --------------------------------------------------
    # 5. Execute pending follow-up questions
    # --------------------------------------------------

    if follow_up_index < len(follow_up_questions):
        return Command(
            goto="researcher",
            update={"next_agent": "researcher"},
        )

    # --------------------------------------------------
    # 6. Research completed but not yet evaluated
    # --------------------------------------------------

    if not critique_complete:
        return Command(
            goto="critic",
            update={"next_agent": "critic"},
        )

    # --------------------------------------------------
    # 7. Process human-in-the-loop decisions
    # --------------------------------------------------

    if hil_decision == "continue":

        # Never exceed the configured follow-up research limit.
        if research_rounds >= max_research_rounds:
            return Command(
                goto="writer",
                update={
                    "next_agent": "writer",
                    "hil_decision": "auto_capped",
                },
            )

        # Nothing new to investigate.
        if not gaps:
            return Command(
                goto="writer",
                update={
                    "next_agent": "writer",
                    "hil_decision": "none",
                },
            )

        # Convert identified gaps into follow-up research tasks.
        return Command(
            goto="researcher",
            update={
                "next_agent": "researcher",
                "follow_up_questions": gaps[:3],
                "follow_up_question_index": 0,
                "research_rounds": research_rounds + 1,
                "critique_complete": False,
                "gaps_identified": [],
                "hil_decision": "none",
            },
        )

    # --------------------------------------------------
    # 8. Human or automatic finalization
    # --------------------------------------------------

    if hil_decision in {
        "finalize",
        "auto_finalize",
        "auto_capped",
    }:
        return Command(
            goto="writer",
            update={
                "next_agent": "writer",
                "hil_decision": "none",
            },
        )

    # --------------------------------------------------
    # 9. Research has gaps and needs human review
    # --------------------------------------------------

    if gaps:
        return Command(
            goto="hil_gate",
            update={"next_agent": "hil_gate"},
        )

    # --------------------------------------------------
    # 10. No outstanding work remains
    # --------------------------------------------------

    return Command(
        goto="writer",
        update={
            "next_agent": "writer",
            "hil_decision": "none",
        },
    )
