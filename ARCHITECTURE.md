# ORBIT — Current Architecture

This document describes the architecture inherited in the initial ORBIT source snapshot. It is a baseline, not a claim that every component is production-hardened.

## Request lifecycle

1. The Streamlit client submits a research request to FastAPI.
2. FastAPI creates a job record and schedules the research workflow.
3. LangGraph orchestrates the supervisor, planner, researcher, critic, human-review gate, and writer nodes.
4. Research tools gather web, arXiv, and Wikipedia material.
5. The graph can pause for a human decision and resume from a checkpoint.
6. The writer generates a Markdown report and returns source URLs.
7. The client observes job status and receives progress events through Server-Sent Events (SSE).

## Current modules

- `src/agents/`: specialized agent nodes and routing logic.
- `src/graph/`: shared graph state and graph construction.
- `src/tools/`: web, arXiv, and Wikipedia integrations.
- `src/api/`: FastAPI app, routes, rate limiting, streaming, and Celery configuration.
- `src/persistence/`: job persistence and LangGraph checkpointer selection.
- `src/tasks/`: Celery task wrappers.
- `src/ui/`: Streamlit research interface.

## Infrastructure

- LLM provider: Groq, configured through `GROQ_API_KEY`.
- Web research: Tavily, configured through `TAVILY_API_KEY`.
- Optional tracing: LangSmith.
- Local persistence: SQLite.
- Optional database and worker services: PostgreSQL and Redis/Celery through Docker Compose.
- API: FastAPI; UI: Streamlit.

## Known baseline constraints

The initial snapshot has an unpinned `requirements.txt`. PostgreSQL checkpointer support imports additional packages that are not all declared in the supplied dependency file. The default local path and Docker path should be validated before relying on PostgreSQL/Celery in production. Automated evaluation, authentication, robust evidence-to-citation mapping, and comprehensive tests are not yet part of this baseline.

These are intentional items for the ORBIT upgrade roadmap.
