
import importlib
import json
from types import SimpleNamespace

import pytest

critic = importlib.import_module("src.agents.critic")


def make_state(**overrides):
    state = {
        "query": "Research the impact of Agentic AI",
        "sub_questions": [
            "What are its applications?",
            "What are its limitations?",
        ],
        "research_findings": [
            "Agents can automate software development.",
            "Agents may produce unreliable results.",
        ],
        "research_errors": [],
        "job_id": None,
    }

    state.update(overrides)
    return state


# ==============================================
# 1. JSON PARSING TESTS
# ==============================================

def test_parse_valid_gaps():
    response = json.dumps({
        "gaps": [
            "Investigate security risks",
            "Compare enterprise applications",
        ]
    })

    result = critic._parse_gaps(response)

    assert len(result) == 2
    assert result[0] == "Investigate security risks"


def test_parse_empty_gaps():
    response = '{"gaps": []}'

    result = critic._parse_gaps(response)

    assert result == []


def test_parse_removes_duplicate_gaps():
    response = json.dumps({
        "gaps": [
            "Security risks",
            "security risks",
            "Enterprise deployment",
        ]
    })

    result = critic._parse_gaps(response)

    assert len(result) == 2


def test_parse_limits_gaps_to_three():
    response = json.dumps({
        "gaps": [
            "Gap one",
            "Gap two",
            "Gap three",
            "Gap four",
            "Gap five",
        ]
    })

    result = critic._parse_gaps(response)

    assert len(result) == 3


def test_parse_markdown_code_fence():
    response = '''```json
{
    "gaps": ["Investigate security risks"]
}
```'''

    result = critic._parse_gaps(response)

    assert result == ["Investigate security risks"]


def test_parse_rejects_invalid_json():
    with pytest.raises(ValueError, match="invalid JSON"):
        critic._parse_gaps("This is not JSON")


def test_parse_rejects_missing_gaps_field():
    with pytest.raises(ValueError, match="must contain a list"):
        critic._parse_gaps('{"result": "complete"}')


def test_parse_rejects_non_list_gaps():
    with pytest.raises(ValueError, match="must contain a list"):
        critic._parse_gaps('{"gaps": "missing security"}')


# ==============================================
# 2. CRITIC NODE TESTS
# ==============================================

def test_critic_node_marks_evaluation_complete(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    class FakeChatGroq:

        def __init__(self, **kwargs):
            pass

        def invoke(self, messages):
            return SimpleNamespace(
                content=json.dumps({
                    "gaps": ["Investigate security risks"]
                })
            )

    monkeypatch.setattr(critic, "ChatGroq", FakeChatGroq)

    result = critic.critic_node(make_state())

    assert result["critique_complete"] is True

    assert result["gaps_identified"] == [
        "Investigate security risks"
    ]


def test_critic_node_handles_sufficient_research(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    class FakeChatGroq:

        def __init__(self, **kwargs):
            pass

        def invoke(self, messages):
            return SimpleNamespace(
                content='{"gaps": []}'
            )

    monkeypatch.setattr(critic, "ChatGroq", FakeChatGroq)

    result = critic.critic_node(make_state())

    assert result["critique_complete"] is True
    assert result["gaps_identified"] == []


def test_critic_does_not_mark_malformed_response_complete(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    class FakeChatGroq:

        def __init__(self, **kwargs):
            pass

        def invoke(self, messages):
            return SimpleNamespace(
                content="Invalid response"
            )

    monkeypatch.setattr(critic, "ChatGroq", FakeChatGroq)

    with pytest.raises(ValueError):
        critic.critic_node(make_state())


def test_critic_rejects_missing_api_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        critic.critic_node(make_state())
