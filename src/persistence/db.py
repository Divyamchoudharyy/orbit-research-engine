import os
import sqlite3
import json 
from datetime import datetime, timezone
from pathlib import Path

DATABASE_URL = os.getenv("DATABASE_URL")
IS_POSTGRES = False
if DATABASE_URL and (DATABASE_URL.startswith("postgresql://") or DATABASE_URL.startswith("postgres://")):
    IS_POSTGRES = True

DB_PATH = Path(__file__).parent.parent.parent / "data" / "research.db"

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

# Initialize Connection Pool if using PostgreSQL
_pg_pool = None
if IS_POSTGRES:
    try:
        from psycopg2.pool import SimpleConnectionPool
        from psycopg2.extras import RealDictCursor
        # pool size 1 to 20
        _pg_pool = SimpleConnectionPool(1, 20, dsn=DATABASE_URL)
    except ImportError:
        # Fall back to SQLite if psycopg2 is not installed
        IS_POSTGRES = False

def init_db() -> None:
    if IS_POSTGRES:
        conn = _pg_pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(_CREATE_JOBS_TABLE)
                conn.commit()
        finally:
            _pg_pool.putconn(conn)
    else:
        DB_PATH.parent.mkdir(exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=10)
        try:
            with conn:
                conn.execute(_CREATE_JOBS_TABLE)
                # Run migrations
                try:
                    conn.execute("ALTER TABLE jobs ADD COLUMN hil_decisions TEXT")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute("ALTER TABLE jobs ADD COLUMN hil_expires_at TEXT")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute("ALTER TABLE jobs ADD COLUMN hil_pending_payload TEXT")
                except sqlite3.OperationalError:
                    pass
        finally:
            conn.close()

def _execute_query(query: str, params: tuple = (), fetchall: bool = False, fetchone: bool = False, commit: bool = False):
    """Executes a query using the active database driver (PostgreSQL or SQLite)."""
    if IS_POSTGRES:
        # Replace SQLite style '?' with PostgreSQL style '%s'
        query = query.replace("?", "%s")
        conn = _pg_pool.getconn()
        try:
            from psycopg2.extras import RealDictCursor
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                if commit:
                    conn.commit()
                if fetchall:
                    return [dict(row) for row in cur.fetchall()]
                if fetchone:
                    row = cur.fetchone()
                    return dict(row) if row else None
        finally:
            _pg_pool.putconn(conn)
    else:
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                cur = conn.execute(query, params)
                if fetchall:
                    return [dict(row) for row in cur.fetchall()]
                if fetchone:
                    row = cur.fetchone()
                    return dict(row) if row else None
        finally:
            conn.close()

def create_job(job_id:str,query:str,depth:str)->None:
    now = datetime.now(timezone.utc).isoformat()
    _execute_query(
        "INSERT INTO jobs (job_id, query, depth, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (job_id, query, depth, "pending", now, now),
        commit=True
    )
        
def update_job_status(
    job_id:str,
    status:str,
    result :dict |None = None,
    error:str |None = None,
    agent_turns:int =0,
)->None:
    now = datetime.now(timezone.utc).isoformat()
    if status != "awaiting_human":
        _execute_query(
            "UPDATE jobs SET status=?, result=?, error=?, agent_turns=?, hil_expires_at=NULL, hil_pending_payload=NULL, updated_at=? WHERE job_id=?",
            (status, json.dumps(result) if result else None, error, agent_turns, now, job_id),
            commit=True
        )
    else:
        _execute_query(
            "UPDATE jobs SET status=?, result=?, error=?, agent_turns=?, updated_at=? WHERE job_id=?",
            (status, json.dumps(result) if result else None, error, agent_turns, now, job_id),
            commit=True
        )

def log_hil_decision(job_id: str, iteration: int, decision: str, gaps: list[str]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    new_event = {
        "iteration": iteration,
        "decision": decision,
        "gaps": gaps,
        "timestamp": now
    }
    row = _execute_query("SELECT hil_decisions FROM jobs WHERE job_id=?", (job_id,), fetchone=True)
    decisions = []
    if row and row["hil_decisions"]:
        try:
            decisions = json.loads(row["hil_decisions"])
        except Exception:
            decisions = []
    decisions.append(new_event)
    _execute_query(
        "UPDATE jobs SET hil_decisions=?, updated_at=? WHERE job_id=?",
        (json.dumps(decisions), now, job_id),
        commit=True
    )

def set_job_awaiting_human(job_id: str, gaps: list[str], iteration: int, expires_at: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "gaps": gaps,
        "iteration": iteration,
        "max_iterations": 3,
        "expires_at": expires_at
    }
    _execute_query(
        "UPDATE jobs SET status=?, hil_expires_at=?, hil_pending_payload=?, updated_at=? WHERE job_id=?",
        ("awaiting_human", expires_at, json.dumps(payload), now, job_id),
        commit=True
    )

def get_hil_payload(job_id: str) -> dict | None:
    row = _execute_query("SELECT hil_pending_payload FROM jobs WHERE job_id=?", (job_id,), fetchone=True)
    if row and row["hil_pending_payload"]:
        try:
            return json.loads(row["hil_pending_payload"])
        except Exception:
            return None
    return None

def get_jobs_by_status(status: str) -> list[dict]:
    return _execute_query("SELECT * FROM jobs WHERE status=?", (status,), fetchall=True)

def get_job(job_id:str)->dict | None:
    return _execute_query("SELECT * FROM jobs WHERE job_id=?", (job_id,), fetchone=True)