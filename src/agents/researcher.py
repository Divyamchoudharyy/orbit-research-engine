
from typing import Any

from langchain_core.messages import AIMessage

from src.graph.state import ResearchState
from src.tools.arxiv_tool import arxiv_search
from src.tools.tavily_tool import tavily_search
from src.tools.wikipedia_tool import wikipedia_search
from src.api.stream_manager import stream_manager


# --------------------------------------------------
# RESEARCH CONFIGURATION
# --------------------------------------------------

_DEPTH_TOOLS = {
    "quick": {
        "tavily": 3,
        "arxiv": False,
        "wikipedia": False,
    },
    "standard": {
        "tavily": 5,
        "arxiv": True,
        "wikipedia": True,
    },
    "deep": {
        "tavily": 7,
        "arxiv": True,
        "wikipedia": True,
    },
}


# --------------------------------------------------
# HELPER FUNCTIONS
# --------------------------------------------------

def _publish_log(job_id: str | None, message: str) -> None:
    """Publish a progress message without interrupting research."""

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
        # Logging failures should not crash research execution.
        pass


def _is_valid_url(url: Any) -> bool:
    """Accept only HTTP/HTTPS source URLs."""

    return (
        isinstance(url, str)
        and url.strip().startswith(("http://", "https://"))
    )


def _collect_tavily_results(
    query: str,
    max_results: int,
) -> tuple[list[str], list[str], list[str]]:
    """Collect web findings, source URLs and tool errors."""

    findings = []
    sources = []
    errors = []

    try:
        results = tavily_search(
            query,
            max_results=max_results,
        )

        if not isinstance(results, list):
            raise TypeError("Tavily returned an unexpected response.")

        for result in results:

            if not isinstance(result, dict):
                continue

            title = str(result.get("title") or "Untitled")
            content = str(result.get("content") or "")
            url = result.get("url")

            # Tavily currently represents errors as result dictionaries.
            if (
                title.strip().lower() == "error"
                or content.lower().startswith("tavily error:")
            ):
                errors.append(
                    f"Tavily: {content[:400] or 'Search failed.'}"
                )
                continue

            if content.strip():
                findings.append(
                    f"[Web] {title}: {content[:600]}"
                )

            if _is_valid_url(url):
                sources.append(url.strip())

    except Exception as exc:
        errors.append(f"Tavily: {str(exc)[:400]}")

    return findings, sources, errors


def _collect_arxiv_results(
    query: str,
    max_results: int = 2,
) -> tuple[list[str], list[str], list[str]]:
    """Collect academic research findings and errors."""

    findings = []
    sources = []
    errors = []

    try:
        papers = arxiv_search(
            query,
            max_results=max_results,
        )

        if not isinstance(papers, list):
            raise TypeError("ArXiv returned an unexpected response.")

        for paper in papers:

            if not isinstance(paper, dict):
                continue

            title = str(paper.get("title") or "Untitled")
            summary = str(paper.get("summary") or "")
            published = str(paper.get("published") or "")
            pdf_url = paper.get("pdf_url")

            if (
                title.strip().lower() == "error"
                or summary.lower().startswith("arxiv error:")
            ):
                errors.append(
                    f"ArXiv: {summary[:400] or 'Search failed.'}"
                )
                continue

            if summary.strip():
                findings.append(
                    f"[ArXiv] {title} "
                    f"({published}): {summary[:800]}"
                )

            if _is_valid_url(pdf_url):
                sources.append(pdf_url.strip())

    except Exception as exc:
        errors.append(f"ArXiv: {str(exc)[:400]}")

    return findings, sources, errors


def _collect_wikipedia_result(
    query: str,
) -> tuple[list[str], list[str], list[str]]:
    """Collect Wikipedia context and errors."""

    findings = []
    sources = []
    errors = []

    try:
        result = wikipedia_search(query)

        if not isinstance(result, dict):
            raise TypeError("Wikipedia returned an unexpected response.")

        if result.get("error"):
            errors.append(
                f"Wikipedia: {str(result['error'])[:400]}"
            )
            return findings, sources, errors

        title = str(result.get("title") or "Untitled")
        summary = str(result.get("summary") or "")
        url = result.get("url")

        if summary.strip():
            findings.append(
                f"[Wikipedia] {title}: {summary[:800]}"
            )

        if _is_valid_url(url):
            sources.append(url.strip())

    except Exception as exc:
        errors.append(f"Wikipedia: {str(exc)[:400]}")

    return findings, sources, errors


# --------------------------------------------------
# MAIN RESEARCHER NODE
# --------------------------------------------------

def research_node(state: ResearchState) -> dict:
    """
    Research exactly one pending question per execution.

    Priority:
        1. Planned research questions.
        2. Critic-generated follow-up questions.

    Research indexes advance after an attempt, even if an
    external search tool fails, to prevent infinite loops.
    """

    # --------------------------------------------------
    # 1. VALIDATE CONFIGURATION
    # --------------------------------------------------

    job_id = state.get("job_id")
    depth = (state.get("depth") or "standard").strip().lower()

    tool_config = _DEPTH_TOOLS.get(depth)

    if tool_config is None:
        raise ValueError(
            f"Invalid research depth: '{depth}'. "
            f"Expected one of: {list(_DEPTH_TOOLS.keys())}"
        )

    # --------------------------------------------------
    # 2. SELECT NEXT RESEARCH QUESTION
    # --------------------------------------------------

    sub_questions = state.get("sub_questions") or []
    planned_index = state.get("planned_question_index", 0)

    follow_up_questions = state.get("follow_up_questions") or []
    follow_up_index = state.get("follow_up_question_index", 0)

    question_type = None

    if planned_index < len(sub_questions):

        current_query = sub_questions[planned_index]
        question_type = "planned"

        current_index = planned_index
        total_questions = len(sub_questions)

    elif follow_up_index < len(follow_up_questions):

        current_query = follow_up_questions[follow_up_index]
        question_type = "follow_up"

        current_index = follow_up_index
        total_questions = len(follow_up_questions)

    else:
        raise ValueError(
            "Researcher was called, but no pending research "
            "questions remain. Check Supervisor routing."
        )

    if not isinstance(current_query, str) or not current_query.strip():
        raise ValueError("The selected research question is empty.")

    current_query = current_query.strip()

    iteration = state.get("research_iterations", 0) + 1

    # --------------------------------------------------
    # 3. LOG START
    # --------------------------------------------------

    _publish_log(
        job_id,
        (
            f"Researcher: starting {question_type} question "
            f"{current_index + 1}/{total_questions}: "
            f"'{current_query[:80]}'"
        ),
    )

    findings = []
    sources = []
    errors = []

    # --------------------------------------------------
    # 4. TAVILY WEB SEARCH
    # --------------------------------------------------

    web_findings, web_sources, web_errors = _collect_tavily_results(
        current_query,
        max_results=tool_config["tavily"],
    )

    findings.extend(web_findings)
    sources.extend(web_sources)
    errors.extend(web_errors)

    # --------------------------------------------------
    # 5. ARXIV PAPER SEARCH
    # --------------------------------------------------

    if tool_config["arxiv"]:

        arxiv_findings, arxiv_sources, arxiv_errors = (
            _collect_arxiv_results(current_query)
        )

        findings.extend(arxiv_findings)
        sources.extend(arxiv_sources)
        errors.extend(arxiv_errors)

    # --------------------------------------------------
    # 6. WIKIPEDIA SEARCH
    # --------------------------------------------------

    if tool_config["wikipedia"]:

        wiki_findings, wiki_sources, wiki_errors = (
            _collect_wikipedia_result(current_query)
        )

        findings.extend(wiki_findings)
        sources.extend(wiki_sources)
        errors.extend(wiki_errors)

    # --------------------------------------------------
    # 7. UPDATE CORRECT QUESTION INDEX
    # --------------------------------------------------

    progress_update = {}

    if question_type == "planned":
        progress_update["planned_question_index"] = (
            planned_index + 1
        )

    elif question_type == "follow_up":
        progress_update["follow_up_question_index"] = (
            follow_up_index + 1
        )

    # --------------------------------------------------
    # 8. PRESERVE EXISTING FINDINGS AND SOURCES
    # --------------------------------------------------

    existing_findings = state.get("research_findings") or []
    existing_sources = state.get("sources") or []
    existing_errors = state.get("research_errors") or []

    # Remove duplicate URLs while preserving order.
    updated_sources = list(
        dict.fromkeys(existing_sources + sources)
    )

    updated_findings = existing_findings + findings

    updated_errors = existing_errors + errors

    # --------------------------------------------------
    # 9. CREATE EXECUTION SUMMARY
    # --------------------------------------------------

    if errors:
        status = (
            f"{len(findings)} findings, "
            f"{len(errors)} tool error(s)"
        )
    else:
        status = f"{len(findings)} findings collected"

    completion_message = (
        f"Researcher: completed {question_type} question "
        f"{current_index + 1}/{total_questions}. {status}."
    )

    _publish_log(job_id, completion_message)

    # --------------------------------------------------
    # 10. RETURN STATE UPDATE
    # --------------------------------------------------

    return {
        **progress_update,

        "research_findings": updated_findings,

        "research_errors": updated_errors,

        "sources": updated_sources,

        "research_iterations": iteration,

        "messages": [
            AIMessage(content=completion_message)
        ],
    }
