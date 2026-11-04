import os
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from src.graph.state import ReasearchState
from src.api.stream_manager import stream_manager

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
- Use markdown formatting throughout
- Every major claim should reference a source by number [1], [2] etc.
- Be comprehensive but concise — target 600-1000 words
- Do NOT hallucinate — only state what the findings support
"""


def writer_node(state: ReasearchState) -> dict:
    job_id = state.get("job_id")
    if job_id:
        stream_manager.publish(job_id,{
            "type":"log",
            "message":"Writer: Generating final report..."
        })
    llm = ChatGroq(
        model="llama-3.3-70b-versatile",
        api_key=os.getenv("GROQ_API_KEY"),
        temperature=0.2,    # slight creativity for good prose, low enough to stay accurate
    )

    # Deduplicate sources and number them
    sources = list(dict.fromkeys(state.get("sources", [])))  # preserves order, removes dupes
    sources_text = "\n".join(f"[{i+1}] {url}" for i, url in enumerate(sources))

    findings_text = "\n\n".join(state.get("research_findings", []))

    synthesis_prompt = f"""Research query: {state['query']}

Research findings:
{findings_text}

Available sources for citation:
{sources_text}

Write the complete research report now."""

    response = llm.invoke([
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=synthesis_prompt),
    ])

    if job_id:
        stream_manager.publish(job_id,{
            "type":"log",
            "message":"Writer: final report complete."
        })

    return {
        "final_report": response.content,
        "sources": sources,
        "messages": [AIMessage(content="Writer: final report complete.")],
    }