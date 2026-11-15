
import json

from src.persistence import db


def setup_test_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "IS_POSTGRES", False)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")

    db.init_db()
    db.create_job("job-1", "Test research", "standard")


def test_running_status_preserves_agent_turns(tmp_path, monkeypatch):
    setup_test_db(tmp_path, monkeypatch)

    db.update_job_status(
        "job-1",
        "running",
        agent_turns=5,
    )

    db.update_job_status("job-1", "running")

    job = db.get_job("job-1")
    assert job["agent_turns"] == 5


def test_omitted_result_and_error_are_preserved(tmp_path, monkeypatch):
    setup_test_db(tmp_path, monkeypatch)

    db.update_job_status(
        "job-1",
        "failed",
        result={"report": "Existing report"},
        error="Existing error",
    )

    db.update_job_status("job-1", "running")

    job = db.get_job("job-1")

    assert json.loads(job["result"]) == {
        "report": "Existing report"
    }
    assert job["error"] == "Existing error"


def test_explicit_none_clears_result_and_error(tmp_path, monkeypatch):
    setup_test_db(tmp_path, monkeypatch)

    db.update_job_status(
        "job-1",
        "failed",
        result={"report": "Old report"},
        error="Old error",
    )

    db.update_job_status(
        "job-1",
        "running",
        result=None,
        error=None,
    )

    job = db.get_job("job-1")

    assert job["result"] is None
    assert job["error"] is None


def test_completion_updates_result_and_agent_turns(tmp_path, monkeypatch):
    setup_test_db(tmp_path, monkeypatch)

    db.update_job_status(
        "job-1",
        "complete",
        result={"report": "Final report"},
        agent_turns=7,
    )

    job = db.get_job("job-1")

    assert job["status"] == "complete"
    assert json.loads(job["result"]) == {
        "report": "Final report"
    }
    assert job["agent_turns"] == 7
