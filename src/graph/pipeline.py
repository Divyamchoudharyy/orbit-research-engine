
from langgraph.graph import END, START, StateGraph

from src.graph.state import ResearchState

from src.agents.supervisor import supervisor_node
from src.agents.planner import planner_node
from src.agents.researcher import research_node
from src.agents.critic import critic_node
from src.agents.hil_node import hil_node
from src.agents.writer import writer_node

from src.persistence.checkpointer import get_checkpointer


def build_graph(checkpointer=None):
    """
    Build the ORBIT research graph.

    An optional checkpointer can be injected for testing.
    If none is provided, the configured application
    checkpointer is used.
    """

    # --------------------------------------------------
    # 1. INITIALIZE GRAPH
    # --------------------------------------------------

    builder = StateGraph(ResearchState)

    # --------------------------------------------------
    # 2. REGISTER NODES
    # --------------------------------------------------

    builder.add_node("supervisor", supervisor_node)
    builder.add_node("planner", planner_node)
    builder.add_node("researcher", research_node)
    builder.add_node("critic", critic_node)
    builder.add_node("hil_gate", hil_node)
    builder.add_node("writer", writer_node)

    # --------------------------------------------------
    # 3. DEFINE WORKFLOW CONNECTIONS
    # --------------------------------------------------

    builder.add_edge(START, "supervisor")

    # Agents return control to the Supervisor.
    # The Supervisor uses Command(goto=...) for routing.

    builder.add_edge("planner", "supervisor")
    builder.add_edge("researcher", "supervisor")

    # Critic always passes through the HIL gate.
    builder.add_edge("critic", "hil_gate")

    builder.add_edge("hil_gate", "supervisor")

    # Writer returns to Supervisor, which terminates
    # execution after detecting a completed report.
    builder.add_edge("writer", "supervisor")

    # --------------------------------------------------
    # 4. CONFIGURE CHECKPOINTER
    # --------------------------------------------------

    if checkpointer is None:
        checkpointer = get_checkpointer()

    # --------------------------------------------------
    # 5. COMPILE GRAPH
    # --------------------------------------------------

    return builder.compile(
        checkpointer=checkpointer
    )


def create_initial_state(
    query: str,
    depth: str = "standard",
    job_id: str | None = None,
) -> ResearchState:
    """
    Create a complete initial research state.

    Centralizing initialization prevents different API
    entry points from starting with inconsistent fields.
    """

    return {
        "query": query,
        "depth": depth,

        "messages": [],

        # Initial plan
        "sub_questions": [],
        "planned_question_index": 0,

        # Follow-up research
        "follow_up_questions": [],
        "follow_up_question_index": 0,

        # Research tracking
        "research_findings": [],
        "research_errors": [],
        "sources": [],

        "research_iterations": 0,
        "research_rounds": 0,
        "max_research_rounds": 3,

        # Critic
        "gaps_identified": [],
        "critique_complete": False,

        # Report
        "final_report": "",

        # Workflow
        "next_agent": "",
        "hil_decision": "none",

        # Job tracking
        "job_id": job_id or "",
    }


# --------------------------------------------------
# LOCAL SMOKE TEST
# --------------------------------------------------

if __name__ == "__main__":

    import uuid

    from dotenv import load_dotenv

    load_dotenv()

    job_id = str(uuid.uuid4())

    # Create complete graph state.
    initial_state = create_initial_state(
        query=(
            "What are the latest breakthroughs "
            "in protein folding AI?"
        ),
        depth="quick",
        job_id=job_id,
    )

    graph = build_graph()

    result = graph.invoke(
        initial_state,
        config={
            "configurable": {
                "thread_id": job_id
            }
        },
    )

    print("\n=== ORBIT SMOKE TEST ===")

    print(f"\nResearch query: {result['query']}")

    print(
        f"\nPlanned questions: "
        f"{len(result.get('sub_questions', []))}"
    )

    print(
        f"Completed planned questions: "
        f"{result.get('planned_question_index', 0)}"
    )

    print(
        f"Follow-up research rounds: "
        f"{result.get('research_rounds', 0)}"
    )

    print(
        f"Research executions: "
        f"{result.get('research_iterations', 0)}"
    )

    print(
        f"\nResearch errors: "
        f"{len(result.get('research_errors', []))}"
    )

    print("\n=== FINAL REPORT ===")

    print(result.get("final_report", ""))

    print("\n=== SOURCES ===")

    for source in result.get("sources", []):
        print(source)
