
import json
import os

from langchain_groq import ChatGroq
from langchain_core.messages import (
    AIMessage,
    SystemMessage,
    HumanMessage,
)

from src.graph.state import ResearchState
from src.api.stream_manager import stream_manager


_SYSTEM_PROMPT = """
You are a critical research reviewer.

Your responsibility is to evaluate whether the collected research
sufficiently answers the user's original research question.

Evaluate:

1. Coverage of the original research question.
2. Coverage of every planned sub-question.
3. Missing important perspectives or topics.
4. Missing recent developments where relevant.
5. Insufficient or contradictory supporting evidence.

Rules:

- Identify at most 3 important research gaps.
- Each gap must be a specific, actionable research question.
- Do not repeat questions that have already been adequately answered.
- Do not invent missing information.
- If research is sufficient, return an empty gaps list.

Return ONLY valid JSON in this exact format:

{
    "gaps": [
        "Specific research question one",
        "Specific research question two"
    ]
}

If research is sufficient, return:

{
    "gaps": []
}

Do not include Markdown fences or explanatory text.
"""


def _publish_log(job_id: str | None, message: str) -> None:
    """Publish a log without allowing streaming failures to crash Critic."""

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


def _parse_gaps(content: str) -> list[str]:
    """Parse and validate the Critic's JSON response."""

    content = content.strip()

    # Support accidental Markdown code fences.
    if content.startswith("```"):
        lines = content.splitlines()

        if lines[-1].strip() == "```":
            content = "\n".join(lines[1:-1]).strip()

    try:
        response = json.loads(content)

    except json.JSONDecodeError as exc:
        raise ValueError(
            "Critic returned invalid JSON. "
            "Research evaluation cannot be trusted."
        ) from exc

    if not isinstance(response, dict):
        raise ValueError("Critic response must be a JSON object.")

    raw_gaps = response.get("gaps")

    if not isinstance(raw_gaps, list):
        raise ValueError(
            "Critic response must contain a list named 'gaps'."
        )

    gaps = []
    seen = set()

    for item in raw_gaps:

        if not isinstance(item, str):
            continue

        gap = item.strip()

        if not gap:
            continue

        normalized = gap.casefold()

        if normalized in seen:
            continue

        seen.add(normalized)
        gaps.append(gap)

        if len(gaps) == 3:
            break

    return gaps


def critic_node(state: ResearchState) -> dict:
    """
    Evaluate accumulated research findings.

    A successful evaluation always sets critique_complete=True.
    A malformed response raises an exception instead of falsely
    marking research as complete.
    """

    job_id = state.get("job_id")

    _publish_log(
        job_id,
        "Critic: evaluating research coverage and evidence...",
    )

    # --------------------------------------------------
    # 1. COLLECT RESEARCH CONTEXT
    # --------------------------------------------------

    query = state.get("query", "")

    sub_questions = state.get("sub_questions") or []

    findings = state.get("research_findings") or []

    research_errors = state.get("research_errors") or []

    # Preserve both initial and most recent findings when the
    # accumulated research exceeds the context limit.
    if len(findings) > 20:
        selected_findings = findings[:10] + findings[-10:]
    else:
        selected_findings = findings

    findings_summary = "\n\n".join(selected_findings)

    sub_questions_text = "\n".join(
        f"- {question}" for question in sub_questions
    )

    errors_summary = "\n".join(
        f"- {error}" for error in research_errors
    )

    if not findings_summary:
        findings_summary = "No usable research findings collected."

    if not errors_summary:
        errors_summary = "No tool failures recorded."

    # --------------------------------------------------
    # 2. INITIALIZE LLM
    # --------------------------------------------------

    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not configured.")

    llm = ChatGroq(
        model="llama-3.3-70b-versatile",
        api_key=api_key,
        temperature=0,
    )

    # --------------------------------------------------
    # 3. BUILD CRITIQUE REQUEST
    # --------------------------------------------------

    review_prompt = f"""
Original research question:

{query}


Planned research questions:

{sub_questions_text}


Collected research findings:

{findings_summary}


Research tool failures:

{errors_summary}


Evaluate the completeness and quality of the research.

Identify only the most important remaining research gaps.

Return the required JSON response.
"""

    # --------------------------------------------------
    # 4. EXECUTE CRITIC
    # --------------------------------------------------

    response = llm.invoke(
        [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=review_prompt),
        ]
    )

    content = response.content

    if not isinstance(content, str):
        raise ValueError(
            "Critic returned an unsupported response format."
        )

    # --------------------------------------------------
    # 5. VALIDATE CRITIC OUTPUT
    # --------------------------------------------------

    gaps = _parse_gaps(content)

    # --------------------------------------------------
    # 6. GENERATE STATUS MESSAGE
    # --------------------------------------------------

    if gaps:
        message = (
            f"Critic: identified {len(gaps)} research gap(s). "
            "Human review is required."
        )
    else:
        message = (
            "Critic: research is sufficient. "
            "No additional gaps identified."
        )

    _publish_log(job_id, message)

    # --------------------------------------------------
    # 7. UPDATE LANGGRAPH STATE
    # --------------------------------------------------

    return {
        "gaps_identified": gaps,

        "critique_complete": True,

        "messages": [
            AIMessage(content=message)
        ],
    }
