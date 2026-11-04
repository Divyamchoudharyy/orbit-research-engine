
import pytest

from langgraph.graph import END
from langgraph.checkpoint.memory import InMemorySaver

from src.agents.supervisor import supervisor_node
from src.graph import pipeline as pipeline_module
from src.graph.pipeline import build_graph, create_initial_state


# ==================================================
# 1. SUPERVISOR UNIT TESTS
# ==================================================

def make_state(**overrides):
    """Create a minimal valid research state for testing."""

    state = {
        "query": "Test research query",
        "depth": "standard",
        "sub_questions": [],
        "planned_question_index": 0,
        "follow_up_questions": [],
        "follow_up_question_index": 0,
        "research_iterations": 0,
        "research_rounds": 0,
        "max_research_rounds": 3,
        "research_findings": [],
        "research_errors": [],
        "sources": [],
        "gaps_identified": [],
        "critique_complete": False,
        "final_report": "",
        "hil_decision": "none",
        "job_id": "test-job",
        "messages": [],
    }

    state.update(overrides)
    return state


def test_supervisor_routes_to_planner_without_plan():
    command = supervisor_node(make_state())

    assert command.goto == "planner"


def test_supervisor_routes_to_researcher_for_pending_question():
    state = make_state(
        sub_questions=["Question 1", "Question 2"],
        planned_question_index=0,
    )

    command = supervisor_node(state)

    assert command.goto == "researcher"


def test_supervisor_routes_to_follow_up_researcher():
    state = make_state(
        sub_questions=["Question 1"],
        planned_question_index=1,
        follow_up_questions=["Follow-up question"],
        follow_up_question_index=0,
    )

    command = supervisor_node(state)

    assert command.goto == "researcher"


def test_supervisor_routes_to_critic_after_research():
    state = make_state(
        sub_questions=["Question 1"],
        planned_question_index=1,
        critique_complete=False,
    )

    command = supervisor_node(state)

    assert command.goto == "critic"


def test_supervisor_routes_to_human_review_when_gaps_exist():
    state = make_state(
        sub_questions=["Question 1"],
        planned_question_index=1,
        critique_complete=True,
        gaps_identified=["Missing security analysis"],
    )

    command = supervisor_node(state)

    assert command.goto == "hil_gate"


def test_supervisor_accepts_continue_decision():
    state = make_state(
        sub_questions=["Question 1"],
        planned_question_index=1,
        critique_complete=True,
        gaps_identified=[
            "Missing security analysis",
            "Missing enterprise comparison",
        ],
        hil_decision="continue",
        research_rounds=0,
    )

    command = supervisor_node(state)

    assert command.goto == "researcher"

    assert command.update["follow_up_questions"] == [
        "Missing security analysis",
        "Missing enterprise comparison",
    ]

    assert command.update["follow_up_question_index"] == 0
    assert command.update["research_rounds"] == 1
    assert command.update["critique_complete"] is False
    assert command.update["gaps_identified"] == []


def test_supervisor_enforces_research_round_limit():
    state = make_state(
        sub_questions=["Question 1"],
        planned_question_index=1,
        critique_complete=True,
        gaps_identified=["Additional research needed"],
        hil_decision="continue",
        research_rounds=3,
        max_research_rounds=3,
    )

    command = supervisor_node(state)

    assert command.goto == "writer"
    assert command.update["hil_decision"] == "auto_capped"


def test_supervisor_routes_finalize_to_writer():
    state = make_state(
        sub_questions=["Question 1"],
        planned_question_index=1,
        critique_complete=True,
        hil_decision="finalize",
    )

    command = supervisor_node(state)

    assert command.goto == "writer"


def test_supervisor_routes_to_writer_when_research_is_sufficient():
    state = make_state(
        sub_questions=["Question 1"],
        planned_question_index=1,
        critique_complete=True,
        gaps_identified=[],
        hil_decision="none",
    )

    command = supervisor_node(state)

    assert command.goto == "writer"


def test_supervisor_terminates_after_report_generation():
    state = make_state(
        final_report="Final research report",
    )

    command = supervisor_node(state)

    assert command.goto == END


# ==================================================
# 2. FULL GRAPH INTEGRATION TESTS
# ==================================================

@pytest.mark.parametrize(
    ("depth", "expected_questions"),
    [
        ("quick", 2),
        ("standard", 3),
        ("deep", 5),
    ],
)
def test_graph_completes_all_planned_questions(
    monkeypatch,
    depth,
    expected_questions,
):
    """
    Test the actual LangGraph orchestration with mocked agents.

    No Groq, Tavily, ArXiv or Wikipedia API calls are made.
    """

    research_calls = []

    # --------------------------------------------------
    # Mock Planner
    # --------------------------------------------------

    def fake_planner(state):

        questions = [
            f"Research question {i + 1}"
            for i in range(expected_questions)
        ]

        return {
            "sub_questions": questions,
            "planned_question_index": 0,
            "follow_up_questions": [],
            "follow_up_question_index": 0,
            "research_rounds": 0,
            "max_research_rounds": 3,
            "critique_complete": False,
            "gaps_identified": [],
        }

    # --------------------------------------------------
    # Mock Researcher
    # --------------------------------------------------

    def fake_researcher(state):

        index = state["planned_question_index"]

        question = state["sub_questions"][index]

        research_calls.append(question)

        return {
            "planned_question_index": index + 1,
            "research_iterations": (
                state.get("research_iterations", 0) + 1
            ),
            "research_findings": (
                state.get("research_findings", [])
                + [f"Evidence for {question}"]
            ),
        }

    # --------------------------------------------------
    # Mock Critic
    # --------------------------------------------------

    def fake_critic(state):

        return {
            "gaps_identified": [],
            "critique_complete": True,
        }

    # --------------------------------------------------
    # Mock Human Review
    # --------------------------------------------------

    def fake_hil(state):

        return {
            "hil_decision": "none",
        }

    # --------------------------------------------------
    # Mock Writer
    # --------------------------------------------------

    def fake_writer(state):

        return {
            "final_report": "Mocked research report",
        }

    # --------------------------------------------------
    # Inject Mocked Nodes
    # --------------------------------------------------

    monkeypatch.setattr(
        pipeline_module,
        "planner_node",
        fake_planner,
    )

    monkeypatch.setattr(
        pipeline_module,
        "research_node",
        fake_researcher,
    )

    monkeypatch.setattr(
        pipeline_module,
        "critic_node",
        fake_critic,
    )

    monkeypatch.setattr(
        pipeline_module,
        "hil_node",
        fake_hil,
    )

    monkeypatch.setattr(
        pipeline_module,
        "writer_node",
        fake_writer,
    )

    # --------------------------------------------------
    # Build Actual LangGraph
    # --------------------------------------------------

    graph = build_graph(
        checkpointer=InMemorySaver()
    )

    initial_state = create_initial_state(
        query="Test research query",
        depth=depth,
        job_id=f"test-{depth}",
    )

    result = graph.invoke(
        initial_state,
        config={
            "configurable": {
                "thread_id": f"test-{depth}"
            }
        },
    )

    # --------------------------------------------------
    # ASSERTIONS
    # --------------------------------------------------

    assert len(research_calls) == expected_questions

    assert result["planned_question_index"] == expected_questions

    assert result["research_iterations"] == expected_questions

    assert result["critique_complete"] is True

    assert result["final_report"] == "Mocked research report"


def test_graph_completes_critic_feedback_loop(monkeypatch):
    """
    Verify:
    Initial research -> Critic identifies gap ->
    Human approves -> Follow-up research ->
    Critic approves -> Writer.
    """

    research_calls = []
    critic_calls = []

    def fake_planner(state):
        return {
            "sub_questions": [
                "Research question 1",
                "Research question 2",
            ],
            "planned_question_index": 0,
            "follow_up_questions": [],
            "follow_up_question_index": 0,
            "research_rounds": 0,
            "max_research_rounds": 3,
            "critique_complete": False,
        }

    def fake_researcher(state):
        planned_index = state["planned_question_index"]
        sub_questions = state["sub_questions"]

        if planned_index < len(sub_questions):
            question = sub_questions[planned_index]

            return {
                "planned_question_index": planned_index + 1,
                "research_iterations": (
                    state.get("research_iterations", 0) + 1
                ),
                "research_findings": (
                    state.get("research_findings", [])
                    + [f"Evidence for {question}"]
                ),
            }

        follow_index = state["follow_up_question_index"]
        question = state["follow_up_questions"][follow_index]

        research_calls.append(question)

        return {
            "follow_up_question_index": follow_index + 1,
            "research_iterations": (
                state.get("research_iterations", 0) + 1
            ),
            "research_findings": (
                state.get("research_findings", [])
                + [f"Follow-up evidence for {question}"]
            ),
        }

    def fake_critic(state):
        critic_calls.append(len(state.get("research_findings", [])))

        # First evaluation finds a gap.
        if len(critic_calls) == 1:
            return {
                "gaps_identified": [
                    "Investigate security limitations"
                ],
                "critique_complete": True,
            }

        # Second evaluation finds sufficient evidence.
        return {
            "gaps_identified": [],
            "critique_complete": True,
        }

    def fake_hil(state):
        if state.get("gaps_identified"):
            return {"hil_decision": "continue"}

        return {"hil_decision": "none"}

    def fake_writer(state):
        return {"final_report": "Verified research report"}

    monkeypatch.setattr(pipeline_module, "planner_node", fake_planner)
    monkeypatch.setattr(pipeline_module, "research_node", fake_researcher)
    monkeypatch.setattr(pipeline_module, "critic_node", fake_critic)
    monkeypatch.setattr(pipeline_module, "hil_node", fake_hil)
    monkeypatch.setattr(pipeline_module, "writer_node", fake_writer)

    graph = build_graph(checkpointer=InMemorySaver())

    result = graph.invoke(
        create_initial_state(
            query="Test research",
            depth="quick",
            job_id="feedback-loop-test",
        ),
        config={
            "configurable": {
                "thread_id": "feedback-loop-test"
            }
        },
    )

    assert result["planned_question_index"] == 2
    assert result["follow_up_question_index"] == 1

    assert result["research_rounds"] == 1
    assert len(critic_calls) == 2

    assert research_calls == [
        "Investigate security limitations"
    ]

    assert result["final_report"] == "Verified research report"
