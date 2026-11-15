# ORBIT - Autonomous Deep Research Engine

> A **multi-agent research prototype and portfolio project** that autonomously plans, researches, critiques, and synthesizes comprehensive cited reports from any research query -- with real-time streaming logs and human-in-the-loop review.

[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green.svg)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-multi--agent-orange.svg)](https://langchain-ai.github.io/langgraph/)
[![SSE Streaming](https://img.shields.io/badge/SSE-real--time%20logs-purple.svg)](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](https://docker.com)

---

## What Is ORBIT?

ORBIT accepts a research query via REST API and runs a **supervisor-orchestrated multi-agent pipeline** that:

1. **Plans** -- decomposes the query into focused sub-questions based on depth setting
2. **Researches** -- searches the web (Tavily), retrieves papers (ArXiv), and queries Wikipedia
3. **Critiques** -- reviews findings for gaps; loops back if more research is needed
4. **Pauses for human review** -- a Human-in-the-Loop gate fires at the critique boundary, letting the user continue or finalize
5. **Writes** -- synthesizes a structured markdown report with numbered citations

The pipeline runs **asynchronously** -- the API returns a `job_id` immediately. **Real-time agent logs stream via SSE** to the Streamlit dashboard. LLM calls can be traced in LangSmith when tracing is enabled.

---

## Architecture

```mermaid
flowchart TB
    subgraph Client["Client Layer"]
        User["User"]
        UI["Streamlit UI port 8501"]
    end

    subgraph API["API Layer - FastAPI port 8000"]
        direction TB
        Endpoint["POST /research
GET /jobs/id/status
GET /jobs/id/result
POST /jobs/id/decision"]
        SSERoute["GET /jobs/id/stream
Server-Sent Events"]
        RateLimit["slowapi rate limiter"]
    end

    subgraph Execution["Execution Layer - Background Thread"]
        Runner["Pipeline Runner
BackgroundTasks thread pool"]
        StreamPub["stream_manager
publish log events"]
    end

    subgraph Graph["LangGraph Supervisor Graph"]
        direction TB
        Supervisor{{"Supervisor
Command routing"}}
        Planner["Planner
Sub-questions"]
        Researcher["Researcher
Tavily + ArXiv + Wiki"]
        Critic["Critic
Gap analysis"]
        HIL["HIL Gate
interrupt check"]
        Writer["Writer
Markdown + citations"]
    end

    subgraph Persistence["Persistence Layer"]
        direction LR
        JobsDB[("Jobs Table
SQLite or PostgreSQL")]
        Checkpoints[("LangGraph
Checkpoints")]
    end

    User -->|"POST /research"| RateLimit
    RateLimit --> Endpoint
    Endpoint -->|"202 Accepted job_id"| User
    Endpoint --> JobsDB
    Endpoint -->|"BackgroundTasks"| Runner

    Runner -->|"status: running"| JobsDB
    Runner --> Graph
    Runner --> StreamPub

    Supervisor --> Planner
    Planner -->|"sub_questions"| Supervisor
    Supervisor --> Researcher
    Researcher -->|"research_findings"| Supervisor
    Supervisor --> Critic
    Critic -->|"gaps_identified"| HIL

    HIL -->|"gaps AND iterations less than 3"| Pause["INTERRUPT
await_human 30 min"]
    Pause -->|"continue"| Researcher
    Pause -->|"finalize"| Writer
    HIL -->|"no gaps OR iterations 3 or more"| Writer

    Writer -->|"status: complete"| JobsDB
    StreamPub -->|"SSE events"| SSERoute
    Graph -.->|"save state after each node"| Checkpoints

    UI -->|"SSE subscribe"| SSERoute
    SSERoute -->|"real-time agent logs"| UI
    UI -->|"poll status / fetch result"| Endpoint
```

---

## Agent State Machine

```mermaid
stateDiagram-v2
    [*] --> supervisor : graph.invoke()

    supervisor --> planner : first turn
    planner --> supervisor : sub_questions set

    supervisor --> researcher : after planner
    researcher --> supervisor : findings accumulated

    supervisor --> critic : after researcher
    critic --> hil_gate : gaps_identified set

    hil_gate --> INTERRUPT : gaps found AND iterations less than 3
    INTERRUPT --> researcher : decision = continue
    INTERRUPT --> writer : decision = finalize

    hil_gate --> writer : no gaps OR iterations 3 or more

    writer --> supervisor : final_report set
    supervisor --> [*] : next_agent = END
```

> **Hard cap**: `research_rounds >= max_research_rounds` bypasses another HIL cycle and routes directly to `writer` (`auto_capped`), preventing unbounded follow-up loops.

---

## Tech Stack

| Component | Choice | Why |
|-----------|--------|-----|
| Agent framework | LangGraph supervisor | Multi-agent, cyclic graph, checkpointing, HIL interrupts |
| LLM | Groq Llama 3.3 70B | Free tier, 500+ tok/s, strong instruction-following |
| Web search | Tavily | Semantic search with scored, cited results |
| Paper search | ArXiv | Direct Python library |
| General knowledge | Wikipedia | Fast encyclopedic background |
| REST API | FastAPI + uvicorn | Async-native, OpenAPI docs auto-generated |
| Job execution | FastAPI BackgroundTasks | Simple in-process execution; restart recovery is limited |
| Real-time logs | SSE via sse-starlette | Push agent logs to UI without polling |
| Persistence | SQLite / PostgreSQL | Jobs and LangGraph checkpoints use the configured database |
| Observability | LangSmith | Optional traces when configured |
| Rate limiting | slowapi | 5 req/IP/hour on `POST /research` |
| UI | Streamlit | SSE log streaming, HIL review panel, report render |

---

## Project Structure

```
ORBIT/
+-- src/
    +-- api/
    |   +-- main.py               # FastAPI app, CORS, lifespan, startup recovery
    |   +-- models.py             # Pydantic request/response models
    |   +-- celery_app.py         # Optional Celery app configuration
    |   +-- stream_manager.py     # Thread-safe SSE pub/sub via asyncio.Queue
    |   +-- routes/
    |       +-- research.py       # All job routes + BackgroundTasks + SSE stream
    |       +-- health.py         # GET /health
    +-- agents/
    |   +-- supervisor.py         # LLM routing via Command(goto=...)
    |   +-- planner.py            # Decomposes query into sub-questions
    |   +-- researcher.py         # Tavily + ArXiv + Wikipedia; publishes SSE logs
    |   +-- critic.py             # Identifies research gaps; publishes SSE logs
    |   +-- writer.py             # Synthesizes markdown report; publishes SSE logs
    +-- graph/
    |   +-- state.py              # ResearchState TypedDict + add_messages reducer
    |   +-- pipeline.py           # Builds + compiles LangGraph StateGraph
    +-- tools/                    # tavily_tool, arxiv_tool, wikipedia_tool
    +-- persistence/
    |   +-- db.py                 # Dual-dialect CRUD -- SQLite or PostgreSQL
    |   +-- checkpointer.py       # Dynamic SqliteSaver / PostgresSaver
    +-- tasks/
    |   +-- research_tasks.py     # Optional Celery task entry points
    +-- ui/
        +-- streamlit_app.py      # SSE streaming, HIL panel, report render
```

---

## API Reference

### `POST /research`
```json
// Request
{ "query": "Latest breakthroughs in protein folding AI?", "depth": "standard" }
// depth: "quick" (~20s, Tavily only)  |  "standard" (~45s, all tools)  |  "deep" (~90s)

// Response 202
{ "job_id": "550e8400-...", "status": "pending", "estimated_seconds": 45 }
```

### `GET /jobs/{job_id}/status`
```json
// While paused for HIL review
{
  "status": "awaiting_human",
  "hil_payload": {
    "gaps": ["Missing AlphaFold 3 comparison", "No benchmarks cited"],
    "iteration": 2, "max_iterations": 3, "expires_at": "2026-07-12T18:00:00Z"
  }
}
// status: pending | running | awaiting_human | complete | failed
```

### `POST /jobs/{job_id}/decision`
```json
{ "decision": "continue" }   // loop back to Researcher
{ "decision": "finalize" }   // skip to Writer
```

### `GET /jobs/{job_id}/stream` -- SSE
```
event: message
data: {"type": "log", "message": "Researcher: Searching Tavily for ..."}

event: ping
data:
```

### `GET /jobs/{job_id}/result`
```json
{ "status": "complete", "report": "## Report...", "sources": ["..."], "agent_turns": 4 }
```

Interactive docs at `/docs` (Swagger UI auto-generated by FastAPI). All research and job routes require `Authorization: Bearer <ORBIT_API_KEY>`; `/health` and `/ready` are public health probes.

---

## Setup & Running

### Prerequisites
- Python 3.11+
- API keys: [Groq](https://console.groq.com) (free), [Tavily](https://tavily.com) (free)
- [LangSmith](https://smith.langchain.com) (optional, for observability)
- Docker Desktop (optional, for PostgreSQL / full-stack)

### Local Development (no Docker needed)

```bash
git clone https://github.com/<your-github-username>/orbit-research-engine.git
cd orbit-research-engine

# Create and activate a virtual environment (Windows PowerShell)
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1

# Configure API keys and install dependencies
Copy-Item .env.example .env
python -m pip install -r requirements-dev.txt

# Terminal 1 -- FastAPI
.venv\Scripts\python.exe -m uvicorn src.api.main:app --reload --port 8000

# Terminal 2 -- Streamlit
.venv\Scripts\python.exe -m streamlit run src/ui/streamlit_app.py
```

> The pipeline runs in FastAPI's built-in thread pool. For tests, install `requirements-dev.txt` and run `python -m pytest tests/ -v`.

### Full Stack with Docker Compose

```bash
cp .env.example .env
# Add GROQ_API_KEY, TAVILY_API_KEY and a strong ORBIT_API_KEY.
# ORBIT_UI_PASSWORD is optional locally; required for production UI access.
docker compose up --build
```

Starts PostgreSQL, FastAPI, and Streamlit. Research/job endpoints require an `Authorization: Bearer <ORBIT_API_KEY>` header; the Streamlit UI sends it automatically. In production, the Streamlit UI also requires `ORBIT_UI_PASSWORD`. The API runs as a single Uvicorn worker because job execution and SSE fan-out are process-local.

- UI: `http://localhost:8501` | API docs: `http://localhost:8000/docs`
- Liveness: `http://localhost:8000/health` | Readiness: `http://localhost:8000/ready`
- See [DEPLOYMENT.md](DEPLOYMENT.md) for Render setup, secrets, smoke tests, and operational boundaries.

### Switch to PostgreSQL

```bash
# Add to .env
DATABASE_URL=postgresql://postgres:secret@localhost:5432/orbit
```

Both the jobs table and LangGraph checkpointer switch automatically when the PostgreSQL drivers are installed.

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GROQ_API_KEY` | Yes | [console.groq.com](https://console.groq.com) -- free tier |
| `TAVILY_API_KEY` | Yes | [tavily.com](https://tavily.com) -- free tier |
| `LANGSMITH_API_KEY` | Recommended | [smith.langchain.com](https://smith.langchain.com) |
| `LANGSMITH_PROJECT` | Recommended | e.g. `orbit-research-engine` |
| `LANGSMITH_TRACING_V2` | Recommended | Set to `true` |
| `DATABASE_URL` | Optional | PostgreSQL connection string; falls back to SQLite |
| `ORBIT_API_KEY` | Required in production | Shared Bearer token for protected API routes |
| `ORBIT_UI_PASSWORD` | Required in production | Shared password gate for the Streamlit UI |
| `ORBIT_UI_PASSWORD` | Required in production | Shared password gate for the Streamlit UI |
| `ORBIT_ENV` | Optional | Set to `production` to enforce API-key configuration |
| `CORS_ORIGINS` | Optional | Comma-separated allowed browser origins |
| `ORBIT_DATA_DIR` | Optional | Persistent directory for SQLite database files |
| `REDIS_URL` | Optional | Only needed when running the optional Celery worker manually |
| `API_BASE` | Docker only | `http://api:8000` |

---

## Design Decisions

<details>
<summary><strong>Why multi-agent instead of one ReAct agent?</strong></summary>

A single ReAct agent conflates planning, researching, critiquing, and writing in one prompt. Separating into specialists allows independent prompts and error handling. The Critic reviewing findings with fresh context -- rather than the same agent that just produced them -- is the key architectural benefit.

</details>

<details>
<summary><strong>Why put the HIL gate in its own node?</strong></summary>

LangGraph re-executes a node from the top when resuming after `interrupt()`. If the interrupt lived inside `supervisor_node`, every resume would re-run the LLM routing call -- wasting tokens and risking different routing. A dedicated `hil_node` with no logic before the interrupt makes re-execution free and deterministic.

</details>

<details>
<summary><strong>Why FastAPI BackgroundTasks instead of Celery/Redis locally?</strong></summary>

`BackgroundTasks` runs sync functions in a thread-pool executor -- zero extra infrastructure. Trade-off: if the server restarts mid-research, an active job can remain marked `running`. The shared execution service also exposes Celery task entry points, but the HTTP submission route currently uses `BackgroundTasks`; cross-process SSE delivery is not implemented yet.

</details>

<details>
<summary><strong>Why SQLite locally but PostgreSQL-ready?</strong></summary>

`src/persistence/db.py` detects `DATABASE_URL` at startup and switches to a `psycopg2` connection pool, translating `?` placeholders to `%s`. The `checkpointer.py` similarly switches between `SqliteSaver` and `PostgresSaver`. The schema is identical between both backends.

</details>

<details>
<summary><strong>What would you add with more time?</strong></summary>

| Improvement | Status |
|-------------|--------|
| Human-in-the-Loop gate | Done |
| Rate limiting (slowapi) | Done |
| SSE real-time log streaming | Done |
| PostgreSQL support | Done |
| Celery task wrappers | Available but not wired to HTTP submission |
| LLM-as-Judge evaluation | Planned |
| Authentication (shared API key) | Implemented |
| Report caching (same query, 24h) | Planned |
| PDF export | Planned |

</details>

---




## Reliability Notes

- Human-review decisions are claimed atomically in the database. A human response and an automatic timeout cannot both win the same pending decision.
- Research graph execution and resume logic are shared between the API and Celery task entry points.
- SQLite is suitable for local development and a single API process. For concurrent deployments, configure PostgreSQL.
- SSE fan-out is process-local. If research is moved to separate Celery worker processes, cross-process SSE delivery requires a Redis-backed event transport; the current HTTP route uses in-process FastAPI BackgroundTasks.
- A process restart during an active job causes pending/running jobs to be marked `failed` at startup; interrupted work must be resubmitted. Durable queue dispatch and automatic replay are not implemented.
- The current tests mock model/search calls. They verify orchestration and persistence behavior, not the accuracy of live research results or external provider availability.

## Test Suite

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

The test suite uses mocked agent/tool responses and does not require live Groq or Tavily credentials.

## Source and Licensing

See [UPSTREAM_NOTICE.md](UPSTREAM_NOTICE.md) for the source-provenance and licensing note. Confirm the applicable license and preserve any required notices before redistributing the project.
