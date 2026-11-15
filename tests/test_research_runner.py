from types import SimpleNamespace

from src.services import research_runner


class FakeGraph:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def invoke(self, state, config):
        self.calls.append((state, config))
        return self.result


def test_initial_research_uses_complete_state_and_persists_report(monkeypatch):
    graph = FakeGraph(
        {
            "final_report": "A final report",
            "sources": ["https://example.com"],
            "research_iterations": 4,
        }
    )
    status_updates = []

    monkeypatch.setattr(research_runner, "get_graph", lambda: graph)
    monkeypatch.setattr(
        research_runner,
        "create_initial_state",
        lambda **kwargs: {"query": kwargs["query"], "job_id": kwargs["job_id"]},
    )
    monkeypatch.setattr(
        research_runner,
        "update_job_status",
        lambda *args, **kwargs: status_updates.append((args, kwargs)),
    )

    outcome = research_runner.run_initial_research(
        "job-1",
        "Test query",
        "quick",
    )

    assert outcome == {"interrupted": False}
    assert graph.calls[0][0] == {
        "query": "Test query",
        "job_id": "job-1",
    }
    assert graph.calls[0][1]["configurable"]["thread_id"] == "job-1"
    assert status_updates[0][1]["status"] == "running"
    assert status_updates[-1][1]["status"] == "complete"
    assert status_updates[-1][1]["agent_turns"] == 4


def test_initial_research_persists_hil_interrupt(monkeypatch):
    interrupt = SimpleNamespace(
        value={"gaps": ["Need more evidence"], "iteration": 2}
    )
    graph = FakeGraph({"__interrupt__": [interrupt]})
    awaiting_calls = []

    monkeypatch.setattr(research_runner, "get_graph", lambda: graph)
    monkeypatch.setattr(
        research_runner,
        "create_initial_state",
        lambda **kwargs: {"query": kwargs["query"]},
    )
    monkeypatch.setattr(
        research_runner,
        "update_job_status",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        research_runner,
        "set_job_awaiting_human",
        lambda **kwargs: awaiting_calls.append(kwargs),
    )

    outcome = research_runner.run_initial_research(
        "job-2",
        "Test query",
        "standard",
    )

    assert outcome["interrupted"] is True
    assert outcome["gaps"] == ["Need more evidence"]
    assert outcome["iteration"] == 2
    assert awaiting_calls[0]["job_id"] == "job-2"
    assert awaiting_calls[0]["gaps"] == ["Need more evidence"]


def test_resume_research_preserves_existing_agent_turns(monkeypatch):
    graph = FakeGraph(
        {
            "final_report": "Resumed report",
            "sources": [],
            "research_iterations": 6,
        }
    )
    status_updates = []

    monkeypatch.setattr(research_runner, "get_graph", lambda: graph)
    monkeypatch.setattr(
        research_runner,
        "update_job_status",
        lambda *args, **kwargs: status_updates.append((args, kwargs)),
    )

    outcome = research_runner.resume_research("job-3", "finalize")

    assert outcome == {"interrupted": False}
    assert status_updates[0][1] == {"status": "running"}
    assert status_updates[-1][1]["status"] == "complete"
    assert status_updates[-1][1]["agent_turns"] == 6
    assert graph.calls[0][1]["configurable"]["thread_id"] == "job-3"
