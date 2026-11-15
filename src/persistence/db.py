"""Database access for ORBIT jobs and human-in-the-loop decisions."""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATABASE_URL = os.getenv("DATABASE_URL")
IS_POSTGRES = bool(
    DATABASE_URL
    and DATABASE_URL.startswith(("postgresql://", "postgres://"))
)

_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DB_PATH = Path(os.getenv("ORBIT_DATA_DIR", str(_DEFAULT_DATA_DIR))) / "research.db"


class _Unset:
    """Sentinel distinguishing omitted arguments from explicit ``None``."""


_UNSET = _Unset()

_CREATE_JOBS_TABLE = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id VARCHAR(50) PRIMARY KEY,
    query TEXT NOT NULL,
    depth VARCHAR(20) NOT NULL DEFAULT 'standard',
    status VARCHAR(30) NOT NULL DEFAULT 'pending',
    result TEXT,
    error TEXT,
    agent_turns INTEGER DEFAULT 0,
    hil_decisions TEXT,
    hil_expires_at VARCHAR(50),
    hil_pending_payload TEXT,
    created_at VARCHAR(50) NOT NULL,
    updated_at VARCHAR(50) NOT NULL
);
"""

_pg_pool = None
if IS_POSTGRES:
    try:
        from psycopg2.pool import SimpleConnectionPool

        _pg_pool = SimpleConnectionPool(1, 20, dsn=DATABASE_URL)
    except ImportError as exc:
        raise RuntimeError(
            "DATABASE_URL points to PostgreSQL, but psycopg2-binary "
            "is not installed. Install project requirements."
        ) from exc


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sqlite_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(DB_PATH),
        check_same_thread=False,
        timeout=30,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db() -> None:
    """Create the jobs table and apply additive schema migrations."""
    if IS_POSTGRES:
        conn = _pg_pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(_CREATE_JOBS_TABLE)
                cur.execute(
                    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS hil_decisions TEXT"
                )
                cur.execute(
                    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS hil_expires_at VARCHAR(50)"
                )
                cur.execute(
                    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS hil_pending_payload TEXT"
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            _pg_pool.putconn(conn)
        return

    conn = _sqlite_connection()
    try:
        with conn:
            conn.execute(_CREATE_JOBS_TABLE)
            existing = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
            }
            migrations = {
                "hil_decisions": "ALTER TABLE jobs ADD COLUMN hil_decisions TEXT",
                "hil_expires_at": "ALTER TABLE jobs ADD COLUMN hil_expires_at VARCHAR(50)",
                "hil_pending_payload": "ALTER TABLE jobs ADD COLUMN hil_pending_payload TEXT",
            }
            for column, statement in migrations.items():
                if column not in existing:
                    conn.execute(statement)
    finally:
        conn.close()


def _execute_query(
    query: str,
    params: tuple = (),
    fetchall: bool = False,
    fetchone: bool = False,
    commit: bool = False,
):
    """Execute a query using the configured database driver."""
    if IS_POSTGRES:
        conn = _pg_pool.getconn()
        try:
            from psycopg2.extras import RealDictCursor

            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query.replace("?", "%s"), params)
                rows = None
                if fetchall:
                    rows = [dict(row) for row in cur.fetchall()]
                elif fetchone:
                    row = cur.fetchone()
                    rows = dict(row) if row else None
            if commit or fetchall or fetchone:
                conn.commit()
            return rows
        except Exception:
            conn.rollback()
            raise
        finally:
            _pg_pool.putconn(conn)

    conn = _sqlite_connection()
    try:
        with conn:
            cur = conn.execute(query, params)
            if fetchall:
                return [dict(row) for row in cur.fetchall()]
            if fetchone:
                row = cur.fetchone()
                return dict(row) if row else None
            if commit:
                return cur.rowcount
    finally:
        conn.close()
    return None


def create_job(job_id: str, query: str, depth: str) -> None:
    now = _now()
    _execute_query(
        """
        INSERT INTO jobs
            (job_id, query, depth, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (job_id, query, depth, "pending", now, now),
        commit=True,
    )


def update_job_status(
    job_id: str,
    status: str,
    result: dict | None | _Unset = _UNSET,
    error: str | None | _Unset = _UNSET,
    agent_turns: int | None | _Unset = _UNSET,
) -> None:
    """Update job status without accidentally erasing omitted fields."""
    assignments = ["status=?", "updated_at=?"]
    params: list[Any] = [status, _now()]

    if result is not _UNSET:
        assignments.append("result=?")
        params.append(json.dumps(result) if result is not None else None)

    if error is not _UNSET:
        assignments.append("error=?")
        params.append(error)

    if agent_turns is not _UNSET:
        assignments.append("agent_turns=?")
        params.append(agent_turns)

    if status != "awaiting_human":
        assignments.extend(["hil_expires_at=NULL", "hil_pending_payload=NULL"])

    params.append(job_id)
    _execute_query(
        f"UPDATE jobs SET {', '.join(assignments)} WHERE job_id=?",
        tuple(params),
        commit=True,
    )


def log_hil_decision(
    job_id: str,
    iteration: int,
    decision: str,
    gaps: list[str],
) -> None:
    """Append an HIL audit event (for non-claim, internal graph events)."""
    now = _now()
    row = _execute_query(
        "SELECT hil_decisions FROM jobs WHERE job_id=?",
        (job_id,),
        fetchone=True,
    )
    decisions = []
    if row and row.get("hil_decisions"):
        try:
            decisions = json.loads(row["hil_decisions"])
        except (TypeError, json.JSONDecodeError):
            decisions = []
    if not isinstance(decisions, list):
        decisions = []
    decisions.append(
        {
            "iteration": iteration,
            "decision": decision,
            "gaps": gaps,
            "timestamp": now,
        }
    )
    _execute_query(
        "UPDATE jobs SET hil_decisions=?, updated_at=? WHERE job_id=?",
        (json.dumps(decisions), now, job_id),
        commit=True,
    )


def set_job_awaiting_human(
    job_id: str,
    gaps: list[str],
    iteration: int,
    expires_at: str,
) -> None:
    now = _now()
    payload = {
        "gaps": gaps,
        "iteration": iteration,
        "max_iterations": 3,
        "expires_at": expires_at,
    }
    _execute_query(
        """
        UPDATE jobs
        SET status=?, hil_expires_at=?, hil_pending_payload=?, updated_at=?
        WHERE job_id=?
        """,
        ("awaiting_human", expires_at, json.dumps(payload), now, job_id),
        commit=True,
    )


def claim_hil_decision(job_id: str, decision: str) -> bool:
    """Atomically claim a pending HIL decision and append its audit event."""
    allowed = {"continue", "finalize", "auto_finalize"}
    if decision not in allowed:
        raise ValueError(f"Unsupported HIL decision: {decision}")

    now = _now()

    if IS_POSTGRES:
        conn = _pg_pool.getconn()
        try:
            from psycopg2.extras import RealDictCursor

            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    UPDATE jobs
                    SET status=%s, updated_at=%s
                    WHERE job_id=%s AND status=%s
                    """,
                    ( "running", now, job_id, "awaiting_human" ),
                )
                if cur.rowcount != 1:
                    conn.rollback()
                    return False

                cur.execute(
                    """
                    SELECT agent_turns, hil_decisions, hil_pending_payload
                    FROM jobs WHERE job_id=%s
                    """,
                    (job_id,),
                )
                row = cur.fetchone()
                decisions = _decode_decisions(row["hil_decisions"] if row else None)
                payload = _decode_payload(row["hil_pending_payload"] if row else None)
                decisions.append(
                    {
                        "iteration": payload.get(
                            "iteration",
                            (row["agent_turns"] or 0) if row else 0,
                        ),
                        "decision": decision,
                        "gaps": payload.get("gaps", []),
                        "timestamp": now,
                    }
                )
                cur.execute(
                    """
                    UPDATE jobs
                    SET hil_decisions=%s,
                        hil_expires_at=NULL,
                        hil_pending_payload=NULL,
                        updated_at=%s
                    WHERE job_id=%s
                    """,
                    (json.dumps(decisions), now, job_id),
                )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            _pg_pool.putconn(conn)

    conn = _sqlite_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            """
            UPDATE jobs
            SET status=?, updated_at=?
            WHERE job_id=? AND status=?
            """,
            ("running", now, job_id, "awaiting_human"),
        )
        if cur.rowcount != 1:
            conn.rollback()
            return False

        row = conn.execute(
            """
            SELECT agent_turns, hil_decisions, hil_pending_payload
            FROM jobs WHERE job_id=?
            """,
            (job_id,),
        ).fetchone()
        decisions = _decode_decisions(row["hil_decisions"] if row else None)
        payload = _decode_payload(row["hil_pending_payload"] if row else None)
        decisions.append(
            {
                "iteration": payload.get(
                    "iteration",
                    (row["agent_turns"] or 0) if row else 0,
                ),
                "decision": decision,
                "gaps": payload.get("gaps", []),
                "timestamp": now,
            }
        )
        conn.execute(
            """
            UPDATE jobs
            SET hil_decisions=?,
                hil_expires_at=NULL,
                hil_pending_payload=NULL,
                updated_at=?
            WHERE job_id=?
            """,
            (json.dumps(decisions), now, job_id),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _decode_decisions(raw: str | None) -> list[dict]:
    try:
        value = json.loads(raw) if raw else []
    except (TypeError, json.JSONDecodeError):
        return []
    return value if isinstance(value, list) else []


def _decode_payload(raw: str | None) -> dict:
    try:
        value = json.loads(raw) if raw else {}
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def get_hil_payload(job_id: str) -> dict | None:
    row = _execute_query(
        "SELECT hil_pending_payload FROM jobs WHERE job_id=?",
        (job_id,),
        fetchone=True,
    )
    if not row or not row.get("hil_pending_payload"):
        return None
    return _decode_payload(row["hil_pending_payload"])


def get_jobs_by_status(status: str) -> list[dict]:
    return _execute_query(
        "SELECT * FROM jobs WHERE status=?",
        (status,),
        fetchall=True,
    )


def get_job(job_id: str) -> dict | None:
    return _execute_query(
        "SELECT * FROM jobs WHERE job_id=?",
        (job_id,),
        fetchone=True,
    )
