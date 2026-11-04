
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from src.graph import pipeline as pipeline_module
from src.graph.pipeline import build_graph, create_initial_state
from src.agents import hil_node as hil_module


def test_real_human_interrupt_and_resume(monkeypatch):
    """Verify actual LangGraph interrupt and resume behavior."""

    research_calls = []
    critic_calls = []

    def fake_planner(state):
        return {
            "sub_questions": ["Question 1", "Question 2"],
            "planned_question_index": 0,
            "follow_up_questions": [],
            "follow_up_question_index": 0,
            "research_rounds": 0,
            "max_research_rounds": 3,
            "critique_complete": False,
        }

    def fake_researcher(state):
        planned_index = state["planned_question_index"]

        if planned_index < len(state["sub_questions"]):
            question = state["sub_questions"][planned_index]

            research_calls.append(question)

            return {
                "planned_question_index": planned_index + 1,
                "research_iterations": (
                    state.get("research_iterations", 0) + 1
                ),
                "research_findings": (
                    state.get("research_findings", [])
                    + [f"Evidence: {question}"]
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
                + [f"Follow-up evidence: {question}"]
            ),
        }

    def fake_critic(state):
        critic_calls.append(
            len(state.get("research_findings", []))
        )

        if len(critic_calls) == 1:
            return {
                "gaps_identified": [
                    "Investigate security limitations"
                ],
                "critique_complete": True,
            }

        return {
            "gaps_identified": [],
            "critique_complete": True,
        }

    def fake_writer(state):
        return {
            "final_report": "Research completed successfully."
        }

    # Mock the agents but retain the actual HIL node.
    monkeypatch.setattr(
        pipeline_module, "planner_node", fake_planner
    )
    monkeypatch.setattr(
        pipeline_module, "research_node", fake_researcher
    )
    monkeypatch.setattr(
        pipeline_module, "critic_node", fake_critic
    )
    monkeypatch.setattr(
        pipeline_module, "writer_node", fake_writer
    )

    # Prevent the test from writing to the real database.
    monkeypatch.setattr(
        hil_module,
        "log_hil_decision",
        lambda **kwargs: None,
    )

    graph = build_graph(
        checkpointer=InMemorySaver()
    )

    config = {
        "configurable": {
            "thread_id": "real-hil-test"
        }
    }

    initial_state = create_initial_state(
        query="Test research question",
        depth="quick",
        job_id="real-hil-test",
    )

    # 1. Start graph execution.
    first_result = graph.invoke(
        initial_state,
        config=config,
    )

    # 2. Verify actual interruption.
    interrupts = first_result.get("__interrupt__", [])

    assert len(interrupts) == 1

    interrupt_data = interrupts[0].value

    assert interrupt_data["gaps"] == [
        "Investigate security limitations"
    ]

    assert interrupt_data["iteration"] == 1

    # 3. Resume the SAME graph thread.
    resumed_result = graph.invoke(
        Command(resume="continue"),
        config=config,
    )

    # 4. Verify completion.
    assert not resumed_result.get("__interrupt__")

    assert research_calls == [
        "Question 1",
        "Question 2",
        "Investigate security limitations",
    ]

    assert resumed_result["research_rounds"] == 1

    assert resumed_result["follow_up_question_index"] == 1

    assert len(critic_calls) == 2

    assert resumed_result["final_report"] == (
        "Research completed successfully."
    )
