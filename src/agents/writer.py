import os

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from src.graph.state import ResearchState
from src.api.stream_manager import stream_manager


# Keep the complete prompt comfortably below Groq's 8k TPM on-demand limit.
# Character budgets are deliberately conservative because tokenization varies.
MAX_FINDINGS_CHARS = 10_000
MAX_SOURCES = 30
MAX_SOURCE_CHARS = 4_000
MAX_COMPLETION_TOKENS = 1_800

_SYSTEM_PROMPT = """You are an expert research report writer. Synthesize the provided research findings into a
comprehensive, well-structured markdown report.

Report structure (mandatory):
## [Title based on query]

### Executive Summary
(2-3 sentence overview of key findings)

### Background & Context
(Foundational information)

### Key Findings
(Main discoveries, organized by theme with sub-headings)

### Current Challenges & Limitations
(What problems remain unsolved)

### Future Directions
(Where the field is heading)

### Sources
(Numbered list of all URLs provided)

Rules:
- Use markdown formatting throughout.
- Every major claim should reference a source by number [1], [2] etc.
- Be comprehensive but concise — target 600-1000 words, within the output token limit.
- Do NOT hallucinate — only state what the findings support.
- If evidence is incomplete or conflicting, explicitly disclose that limitation.
- Never imply that a source supports a claim unless the supplied findings establish that connection.
"""


def _prepare_findings_text(findings: list[str], max_chars: int = MAX_FINDINGS_CHARS) -> str:
    """Build a bounded, extractive evidence context without inventing summaries."""
    if max_chars <= 0:
        return ""

    normalized = [item.strip() for item in findings if isinstance(item, str) and item.strip()]
    if not normalized:
        return "No research findings were collected."

    # Keep early and late evidence represented when the accumulated state is large.
    ordered = normalized
    if len(normalized) > 12:
        ordered = normalized[:6] + normalized[-6:]

    sections = []
    remaining = max_chars
    omitted = 0

    for index, finding in enumerate(ordered, start=1):
        if remaining <= 0:
            omitted += 1
            continue

        prefix = f"[Finding {index}] "
        available = remaining - len(prefix)
        if available <= 0:
            omitted += 1
            continue

        excerpt = finding
        if len(excerpt) > available:
            excerpt = excerpt[: max(0, available - 24)].rstrip() + " [excerpt truncated]"
            omitted += 1

        section = prefix + excerpt
        sections.append(section)
        remaining -= len(section) + 2

    if omitted:
        note = f"[Context budget: {omitted} finding(s) or trailing text omitted. Treat the included evidence as partial.]"
        if len(note) <= remaining:
            sections.append(note)

    return "\n\n".join(sections)


def _prepare_sources(raw_sources: list[str]) -> list[str]:
    """Deduplicate and bound the source list while preserving original order."""
    unique = list(dict.fromkeys(
        source.strip()
        for source in raw_sources
        if isinstance(source, str)
        and source.strip().startswith(("http://", "https://"))
    ))

    selected = []
    used_chars = 0
    for source in unique:
        if len(selected) >= MAX_SOURCES:
            break
        if len(source) > 500:
            continue
        addition = len(source) + 1
        if used_chars + addition > MAX_SOURCE_CHARS:
            break
        selected.append(source)
        used_chars += addition
    return selected


def writer_node(state: ResearchState) -> dict:
    job_id = state.get("job_id")
    if job_id:
        try:
            stream_manager.publish(job_id, {
                "type": "log",
                "message": "Writer: Preparing bounded evidence context...",
            })
        except Exception:
            pass

    # Deduplicate and cap sources before constructing the prompt.
    sources = _prepare_sources(state.get("sources") or [])
    sources_text = "\n".join(
        f"[{index + 1}] {url}" for index, url in enumerate(sources)
    ) or "No source URLs were collected."

    findings_text = _prepare_findings_text(
        state.get("research_findings") or []
    )

    synthesis_prompt = f"""Research query: {state.get('query', '')}

Research findings (bounded evidence excerpts; omitted material may exist):
{findings_text}

Available sources for citation:
{sources_text}

Write the complete research report now. Disclose any evidence gaps caused by incomplete findings."""

    llm = ChatGroq(
        model="openai/gpt-oss-120b",
        api_key=os.getenv("GROQ_API_KEY"),
        temperature=0.2,
        max_tokens=MAX_COMPLETION_TOKENS,
    )

    if job_id:
        try:
            stream_manager.publish(job_id, {
                "type": "log",
                "message": (
                    f"Writer: generating report from {len(findings_text)} "
                    f"finding-context characters and {len(sources)} sources."
                ),
            })
        except Exception:
            pass

    response = llm.invoke([
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=synthesis_prompt),
    ])

    if job_id:
        try:
            stream_manager.publish(job_id, {
                "type": "log",
                "message": "Writer: final report complete.",
            })
        except Exception:
            pass

    return {
        "final_report": response.content,
        "sources": sources,
        "messages": [AIMessage(content="Writer: final report complete.")],
    }
