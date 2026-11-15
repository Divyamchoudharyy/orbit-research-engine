
import importlib

import pytest

researcher = importlib.import_module("src.agents.researcher")


def make_state(**overrides):
    state = {
        "query": "Test research",
        "depth": "quick",
        "sub_questions": ["Question 1", "Question 2"],
        "planned_question_index": 0,
        "follow_up_questions": [],
        "follow_up_question_index": 0,
        "research_findings": [],
        "research_errors": [],
        "sources": [],
        "research_iterations": 0,
        "job_id": None,
    }

    state.update(overrides)
    return state


def mock_tavily(monkeypatch, results):
    monkeypatch.setattr(
        researcher,
        "tavily_search",
        lambda query, max_results: results,
    )


def test_researcher_processes_next_planned_question(monkeypatch):
    mock_tavily(monkeypatch, [
        {
            "title": "Research Article",
            "content": "Important research evidence.",
            "url": "https://example.com/article",
        }
    ])

    result = researcher.research_node(
        make_state(planned_question_index=0)
    )

    assert result["planned_question_index"] == 1
    assert result["research_iterations"] == 1

    assert len(result["research_findings"]) == 1
    assert "Important research evidence." in (
        result["research_findings"][0]
    )

    assert result["sources"] == [
        "https://example.com/article"
    ]


def test_researcher_processes_next_follow_up_question(monkeypatch):
    mock_tavily(monkeypatch, [
        {
            "title": "Security Article",
            "content": "Security evidence.",
            "url": "https://example.com/security",
        }
    ])

    result = researcher.research_node(
        make_state(
            planned_question_index=2,
            follow_up_questions=[
                "Investigate security limitations",
                "Compare enterprise deployment",
            ],
            follow_up_question_index=0,
        )
    )

    assert "planned_question_index" not in result

    assert result["follow_up_question_index"] == 1
    assert result["research_iterations"] == 1


def test_researcher_deduplicates_sources(monkeypatch):
    url = "https://example.com/article"

    mock_tavily(monkeypatch, [
        {
            "title": "Article",
            "content": "Evidence one.",
            "url": url,
        },
        {
            "title": "Article duplicate",
            "content": "Evidence two.",
            "url": url,
        },
    ])

    result = researcher.research_node(
        make_state(sources=[url])
    )

    assert result["sources"].count(url) == 1


def test_researcher_separates_tavily_errors_from_findings(monkeypatch):
    mock_tavily(monkeypatch, [
        {
            "title": "Error",
            "content": "Tavily error: request timed out",
            "url": "",
        }
    ])

    result = researcher.research_node(make_state())

    assert result["research_findings"] == []
    assert len(result["research_errors"]) == 1
    assert "Tavily" in result["research_errors"][0]


def test_researcher_handles_arxiv_and_wikipedia(monkeypatch):
    calls = []

    mock_tavily(monkeypatch, [
        {
            "title": "Web result",
            "content": "Web evidence.",
            "url": "https://example.com/web",
        }
    ])

    def fake_arxiv(query, max_results):
        calls.append("arxiv")

        return [{
            "title": "Research Paper",
            "summary": "Academic evidence.",
            "published": "2026",
            "pdf_url": "https://arxiv.org/pdf/1234",
        }]

    def fake_wikipedia(query):
        calls.append("wikipedia")

        return {
            "title": "Topic",
            "summary": "Background evidence.",
            "url": "https://en.wikipedia.org/wiki/Topic",
        }

    monkeypatch.setattr(researcher, "arxiv_search", fake_arxiv)
    monkeypatch.setattr(researcher, "wikipedia_search", fake_wikipedia)

    result = researcher.research_node(
        make_state(depth="standard")
    )

    assert calls == ["arxiv", "wikipedia"]
    assert len(result["research_findings"]) == 3
    assert len(result["sources"]) == 3


def test_researcher_rejects_invalid_depth():
    with pytest.raises(ValueError, match="Invalid research depth"):
        researcher.research_node(
            make_state(depth="ultra")
        )


def test_researcher_rejects_missing_pending_questions():
    with pytest.raises(ValueError, match="no pending research questions"):
        researcher.research_node(
            make_state(
                sub_questions=[],
                planned_question_index=0,
            )
        )
