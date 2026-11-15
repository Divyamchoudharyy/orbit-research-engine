
from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class ResearchState(TypedDict, total=False):
    """
    Shared state for the ORBIT research workflow.

    All agents read from and update this shared state.
    LangGraph reducers determine how individual updates
    are merged.
    """

    # --------------------------------------------------
    # 1. USER INPUT
    # --------------------------------------------------

    query: str
    depth: str

    # --------------------------------------------------
    # 2. AGENT COMMUNICATION
    # --------------------------------------------------

    messages: Annotated[list, add_messages]

    # --------------------------------------------------
    # 3. INITIAL RESEARCH PLAN
    # --------------------------------------------------

    sub_questions: list[str]

    # Index of the next planned question to research.
    planned_question_index: int

    # --------------------------------------------------
    # 4. RESEARCH FINDINGS
    # --------------------------------------------------

    research_findings: list[str]
    research_errors: list[str]
    sources: list[str]

    # Total number of Researcher node executions.
    research_iterations: int

    # --------------------------------------------------
    # 5. CRITIC AND FOLLOW-UP RESEARCH
    # --------------------------------------------------

    gaps_identified: list[str]

    # Additional questions generated from research gaps.
    follow_up_questions: list[str]

    # Index of the next follow-up question to research.
    follow_up_question_index: int

    # Number of additional research rounds approved.
    research_rounds: int

    # Maximum allowed additional research rounds.
    max_research_rounds: int

    # True when Critic has evaluated the current findings.
    critique_complete: bool

    # --------------------------------------------------
    # 6. FINAL REPORT
    # --------------------------------------------------

    final_report: str

    # --------------------------------------------------
    # 7. WORKFLOW ROUTING
    # --------------------------------------------------

    next_agent: str

    # --------------------------------------------------
    # 8. HUMAN-IN-THE-LOOP
    # --------------------------------------------------

    job_id: str

    # continue | finalize | auto_finalize | auto_capped | none
    hil_decision: str


# Temporary backward compatibility.
# Existing agents still importing ReasearchState will work.
# We will migrate all imports to ResearchState during cleanup.

ReasearchState = ResearchState
