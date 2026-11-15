import sqlite3

from src.persistence import db


def test_init_db_adds_missing_hil_columns(tmp_path, monkeypatch):
    database_path = tmp_path / "legacy.db"
    monkeypatch.setattr(db, "IS_POSTGRES", False)
    monkeypatch.setattr(db, "DB_PATH", database_path)

    conn = sqlite3.connect(database_path)
    conn.execute(
        """
        CREATE TABLE jobs (
            job_id VARCHAR(50) PRIMARY KEY,
            query TEXT NOT NULL,
            depth VARCHAR(20) NOT NULL DEFAULT 'standard',
            status VARCHAR(30) NOT NULL DEFAULT 'pending',
            result TEXT,
            error TEXT,
            agent_turns INTEGER DEFAULT 0,
            created_at VARCHAR(50) NOT NULL,
            updated_at VARCHAR(50) NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()

    db.init_db()

    conn = sqlite3.connect(database_path)
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
    }
    conn.close()

    assert {
        "hil_decisions",
        "hil_expires_at",
        "hil_pending_payload",
    }.issubset(columns)
