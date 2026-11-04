from langgraph.graph import StateGraph,START
from src.graph.state import ReasearchState
from src.agents.supervisor import supervisor_node
from src.agents.planner import planner_node 
from src.agents.researcher import research_node
from src.agents.critic import critic_node
from src.agents.writer import writer_node
from src.agents.hil_node import hil_node
from src.persistence.checkpointer import get_checkpointer

def build_graph():
    builder = StateGraph(ReasearchState)
    
    #all nodes 
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("planner", planner_node)
    builder.add_node("researcher", research_node)
    builder.add_node("critic", critic_node)
    builder.add_node("hil_gate", hil_node)
    builder.add_node("writer", writer_node)
    
    #all edges return to supervisor after finishing
    #supervisoer_node returns command(goto=...) which handles dynamic routing
    builder.add_edge(START, "supervisor")
    builder.add_edge("planner", "supervisor")
    builder.add_edge("researcher", "supervisor")
    builder.add_edge("critic", "hil_gate")
    builder.add_edge("hil_gate", "supervisor")
    builder.add_edge("writer", "supervisor")
    
    checkpointer = get_checkpointer()
    return builder.compile(checkpointer=checkpointer)

# ── Smoke test ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uuid
    from dotenv import load_dotenv
    load_dotenv()

    graph = build_graph()
    job_id = str(uuid.uuid4())

    result = graph.invoke(
        {
            "query": "What are the latest breakthroughs in protein folding AI?",
            "depth": "quick",
            "messages": [],
            "sub_questions": [],
            "research_findings": [],
            "gaps_identified": [],
            "research_iterations": 0,
            "final_report": "",
            "sources": [],
            "next_agent": "",
            "job_id": job_id,
            "hil_decision": "none",
        },
        config={"configurable": {"thread_id": job_id}},
    )

    print("\n=== SMOKE TEST RESULT ===")
    print(f"Final report:\n{result['final_report']}")
    print(f"Research iterations: {result['research_iterations']}")
    print(f"Sources: {result['sources']}")
    print(f"Message count: {len(result['messages'])}")