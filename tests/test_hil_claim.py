
import json
import threading
from concurrent.futures import ThreadPoolExecutor

from src.persistence import db


def test_claim_hil_decision_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "IS_POSTGRES", False)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")

    db.init_db()
    db.create_job("job-1", "Test research", "standard")

    db.set_job_awaiting_human(
        "job-1",
        ["Missing recent evidence"],
        1,
        "2026-12-01T12:00:00+00:00",
    )

    claimed = db.claim_hil_decision("job-1", "continue")

    assert claimed is True

    job = db.get_job("job-1")
    assert job["status"] == "running"
    assert job["hil_expires_at"] is None
    assert job["hil_pending_payload"] is None

    decisions = json.loads(job["hil_decisions"])
    assert len(decisions) == 1
    assert decisions[0]["decision"] == "continue"
    assert decisions[0]["gaps"] == ["Missing recent evidence"]


def test_second_claim_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "IS_POSTGRES", False)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")

    db.init_db()
    db.create_job("job-2", "Test research", "standard")

    db.set_job_awaiting_human(
        "job-2",
        ["Missing evidence"],
        1,
        "2026-12-01T12:00:00+00:00",
    )

    first_claim = db.claim_hil_decision("job-2", "continue")
    second_claim = db.claim_hil_decision("job-2", "finalize")

    assert first_claim is True
    assert second_claim is False

    job = db.get_job("job-2")
    decisions = json.loads(job["hil_decisions"])

    assert len(decisions) == 1
    assert decisions[0]["decision"] == "continue"


def test_claim_rejects_nonexistent_job(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "IS_POSTGRES", False)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")

    db.init_db()

    result = db.claim_hil_decision(
        "unknown-job",
        "continue",
    )

    assert result is False


def test_concurrent_claim_only_one_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "IS_POSTGRES", False)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")

    db.init_db()
    db.create_job(
        "job-concurrent",
        "Concurrent test",
        "standard",
    )

    db.set_job_awaiting_human(
        "job-concurrent",
        ["Missing evidence"],
        1,
        "2026-12-01T12:00:00+00:00",
    )

    # Synchronize both threads before they attempt the claim.
    barrier = threading.Barrier(2)

    def attempt_claim(decision):
        barrier.wait(timeout=5)
        return db.claim_hil_decision(
            "job-concurrent",
            decision,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        future1 = executor.submit(
            attempt_claim,
            "continue",
        )
        future2 = executor.submit(
            attempt_claim,
            "finalize",
        )

        results = [
            future1.result(timeout=10),
            future2.result(timeout=10),
        ]

    # Exactly one thread should successfully claim the job.
    assert results.count(True) == 1
    assert results.count(False) == 1

    # Verify that only one audit decision was recorded.
    job = db.get_job("job-concurrent")
    decisions = json.loads(job["hil_decisions"])

    assert job["status"] == "running"
    assert len(decisions) == 1
    assert decisions[0]["decision"] in (
        "continue",
        "finalize",
    )


def test_claim_rejects_invalid_decision(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "IS_POSTGRES", False)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")

    db.init_db()
    db.create_job("job-invalid", "Test research", "standard")
    db.set_job_awaiting_human(
        "job-invalid",
        ["Missing evidence"],
        1,
        "2026-12-01T12:00:00+00:00",
    )

    import pytest

    with pytest.raises(ValueError):
        db.claim_hil_decision("job-invalid", "skip")
