# ORBIT — Architecture and Operational Boundaries

ORBIT is a multi-agent research prototype. This document describes the current implementation and distinguishes implemented behavior from deployment limitations.

## Request lifecycle

1. The FastAPI endpoint validates the query and depth, creates a job record, and schedules a background task.
2. `src/services/research_runner.py` creates the complete LangGraph initial state and runs the compiled graph.
3. The supervisor routes work through planner, researcher, critic, the HIL gate, and writer.
4. When the graph interrupts for human review, the job is persisted as `awaiting_human` with its gaps and expiration time.
5. The user can submit `continue` or `finalize`. The database atomically changes the job from `awaiting_human` to `running` and appends the audit event before the graph is resumed.
6. The timeout and startup-recovery paths use the same atomic claim operation with `auto_finalize`, preventing duplicate human/timeout decisions.
7. The result, sources, status, and research-iteration count are persisted for the result endpoint.

## Main modules

- `src/agents/`: supervisor, planner, researcher, critic, HIL gate, and writer nodes.
- `src/graph/`: typed graph state, graph construction, and complete initial-state factory.
- `src/services/research_runner.py`: shared initial-run and resume execution used by API and Celery entry points.
- `src/api/`: FastAPI routes, request/response models, rate limiting, startup recovery, and process-local SSE fan-out.
- `src/persistence/db.py`: SQLite/PostgreSQL job persistence, additive schema migrations, and atomic HIL decision claims.
- `src/persistence/checkpointer.py`: process-local LangGraph SQLite/PostgreSQL checkpointer.
- `src/tasks/`: optional Celery task wrappers.
- `src/ui/`: Streamlit interface.

## Persistence

- Local development defaults to SQLite.
- Configure `DATABASE_URL` to use PostgreSQL for job records and LangGraph checkpoints.
- PostgreSQL job records use `psycopg2`; PostgreSQL LangGraph checkpoints use `psycopg` v3 and `langgraph-checkpoint-postgres`.
- The SQLite checkpointer is intended for lightweight, single-process development. Prefer PostgreSQL for concurrent deployments.

## Operational limitations

- The HTTP API currently runs jobs using FastAPI `BackgroundTasks`. If the API process stops during an active job, the job may remain marked `running`; active-job lease recovery is not implemented.
- Celery task wrappers share the same execution service, but the HTTP submission route does not currently enqueue Celery tasks.
- SSE fan-out uses in-process asyncio queues. Events published from a separate Celery process are not delivered to the API process; cross-process Redis Pub/Sub is not implemented.
- The timeout thread is process-local. Startup recovery restores pending HIL timers when the API starts, but this is not a substitute for a durable distributed scheduler.
- Automated tests mock model and search calls. They verify routing, HIL persistence, and local event fan-out, not live provider quality, rate limits, or end-to-end deployment behavior.
- Authentication and authorization are not implemented. Do not expose the API publicly without an appropriate access-control layer and restrictive CORS configuration.

## Test commands

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests/ -v
```
