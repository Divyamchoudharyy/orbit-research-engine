import os
import sqlite3
from src.persistence.db import DB_PATH, IS_POSTGRES, DATABASE_URL

def get_checkpointer():
    if IS_POSTGRES:
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
            from psycopg_pool import ConnectionPool
            pool = ConnectionPool(conninfo=DATABASE_URL, max_size=10)
            saver = PostgresSaver(pool)
            # PostgresSaver needs setup to be run once to initialize its internal tables
            saver.setup()
            return saver
        except ImportError:
            # Fall back to sqlite checkpointer if postgres requirements are missing
            pass

    from langgraph.checkpoint.sqlite import SqliteSaver
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    return SqliteSaver(conn)