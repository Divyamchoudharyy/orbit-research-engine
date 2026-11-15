"""LangGraph checkpoint storage shared within each worker process."""

import sqlite3
import threading

from src.persistence.db import DATABASE_URL, DB_PATH, IS_POSTGRES

_checkpointer = None
_checkpointer_lock = threading.Lock()
_connection_pool = None


def get_checkpointer():
    """Return a process-local checkpointer backed by the configured database."""
    global _checkpointer, _connection_pool

    if _checkpointer is not None:
        return _checkpointer

    with _checkpointer_lock:
        if _checkpointer is not None:
            return _checkpointer

        if IS_POSTGRES:
            try:
                from langgraph.checkpoint.postgres import PostgresSaver
                from psycopg_pool import ConnectionPool
            except ImportError as exc:
                raise RuntimeError(
                    "PostgreSQL checkpointing requires "
                    "'langgraph-checkpoint-postgres' and 'psycopg[binary,pool]'."
                ) from exc

            _connection_pool = ConnectionPool(
                conninfo=DATABASE_URL,
                max_size=10,
                open=True,
                kwargs={
                    "autocommit": True,
                    "prepare_threshold": 0,
                },
            )
            _checkpointer = PostgresSaver(_connection_pool)
            _checkpointer.setup()
            return _checkpointer

        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            str(DB_PATH),
            check_same_thread=False,
            timeout=30,
        )
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")

        from langgraph.checkpoint.sqlite import SqliteSaver

        _checkpointer = SqliteSaver(connection)
        return _checkpointer
