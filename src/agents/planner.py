
import os
import re

from langchain_groq import ChatGroq
from langchain_core.messages import (
    AIMessage,
    SystemMessage,
    HumanMessage,
)

from src.graph.state import ResearchState
from src.api.stream_manager import stream_manager


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

_DEPTH_QUESTION = {
    "quick": 2,
    "standard": 3,
    "deep": 5,
}

_SYSTEM_PROMPT = """
You are an expert research planning specialist.

Your task is to decompose a research query into focused,
independent and answerable research questions.

Rules:
- Generate exactly the requested number of questions.
- Every question must contribute to answering the original query.
- Cover background, current developments, challenges and future directions.
- Avoid overlapping or repetitive questions.
- Questions must be specific enough for web and academic research.
- Return ONLY a numbered list.
- Do not include a title, introduction or conclusion.

Example:
1. What is the background and history of the topic?
2. What are its latest developments?
3. What are its current limitations?
"""


def _publish_log(job_id: str | None, message: str) -> None:
    """Publish planner progress without affecting execution."""

    if not job_id:
        return

    try:
        stream_manager.publish(
            job_id,
            {
                "type": "log",
                "message": message,
            },
        )
    except Exception:
        pass


def _parse_questions(content: str, expected_count: int) -> list[str]:
    """Extract unique questions from the numbered LLM response."""

    if not isinstance(content, str):
        raise ValueError("Planner returned an invalid response format.")

    questions = []
    seen = set()

    for line in content.splitlines():

        line = line.strip()

        match = re.match(
            r"^(?:\d+[.)]|[-*•])\s+(.+?)\s*$",
            line,
        )

        if not match:
            continue

        question = match.group(1).strip()

        if not question:
            continue

        normalized = question.casefold()

        if normalized in seen:
            continue

        seen.add(normalized)
        questions.append(question)

        if len(questions) == expected_count:
            break

    if len(questions) != expected_count:
        raise ValueError(
            f"Planner generated {len(questions)} valid questions, "
            f"but {expected_count} were required. "
            "Please retry the research job."
        )

    return questions


# --------------------------------------------------
# PLANNER NODE
# --------------------------------------------------

def planner_node(state: ResearchState) -> dict:
    """
    Generate the initial research plan and initialize
    the research workflow state.
    """

    job_id = state.get("job_id")

    query = (state.get("query") or "").strip()

    depth = (state.get("depth") or "standard").strip().lower()

    # --------------------------------------------------
    # 1. VALIDATE INPUT
    # --------------------------------------------------

    if not query:
        raise ValueError("Research query cannot be empty.")

    if depth not in _DEPTH_QUESTION:
        raise ValueError(
            f"Invalid research depth: {depth}. "
            f"Expected: {list(_DEPTH_QUESTION.keys())}"
        )

    n_questions = _DEPTH_QUESTION[depth]

    _publish_log(
        job_id,
        f"Planner: creating a {depth} research plan "
        f"with {n_questions} questions.",
    )

    # --------------------------------------------------
    # 2. VALIDATE API CONFIGURATION
    # --------------------------------------------------

    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not configured.")

    # --------------------------------------------------
    # 3. INITIALIZE MODEL
    # --------------------------------------------------

    llm = ChatGroq(
        model="llama-3.3-70b-versatile",
        api_key=api_key,
        temperature=0.2,
    )

    # --------------------------------------------------
    # 4. GENERATE RESEARCH PLAN
    # --------------------------------------------------

    response = llm.invoke(
        [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    f"Research query: {query}\n"
                    f"Generate exactly {n_questions} "
                    "independent research questions."
                )
            ),
        ]
    )

    # --------------------------------------------------
    # 5. PARSE AND VALIDATE QUESTIONS
    # --------------------------------------------------

    sub_questions = _parse_questions(
        response.content,
        expected_count=n_questions,
    )

    # --------------------------------------------------
    # 6. LOG PLAN
    # --------------------------------------------------

    _publish_log(
        job_id,
        f"Planner: successfully generated "
        f"{len(sub_questions)} research questions.",
    )

    # --------------------------------------------------
    # 7. INITIALIZE WORKFLOW STATE
    # --------------------------------------------------

    return {
        # Initial research plan
        "sub_questions": sub_questions,

        "planned_question_index": 0,

        # Follow-up research
        "follow_up_questions": [],

        "follow_up_question_index": 0,

        "research_rounds": 0,

        "max_research_rounds": state.get(
            "max_research_rounds", 3
        ),

        # Research tracking
        "research_iterations": state.get(
            "research_iterations", 0
        ),

        "research_findings": state.get(
            "research_findings", []
        ),

        "research_errors": state.get(
            "research_errors", []
        ),

        "sources": state.get("sources", []),

        # Critic tracking
        "gaps_identified": [],

        "critique_complete": False,

        # Workflow control
        "hil_decision": "none",

        # Agent communication
        "messages": [
            AIMessage(
                content=(
                    f"Planner: generated "
                    f"{len(sub_questions)} research questions "
                    f"for {depth} research."
                )
            )
        ],
    }
