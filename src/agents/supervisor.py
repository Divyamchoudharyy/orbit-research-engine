from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage,HumanMessage
from langgraph.types import Command
from src.graph.state import ReasearchState
import os

AGENTS = ['planner','researcher','critic','writer','FINISH']

_SYSTEM_PROMPT = """You are a reasech supervisor. Given the current reasearch state, you will decide which agent to call next.

Roting rules (follow in order):
1. if sub_question is empty -> route to: planner
2-if reaserch_findings is empty -> route to: reasearcher
3- if gaps_identiified is empty -> route to: critic
4- if gaps exist AND reasearch_iterations < 3 -> route to: reasearcher
5- if gaps exist AND reasearch_iterations >= 3 -> route to: writer
6- if final_report is not_empty -> route to: FINISH

Respond with only one of these words :planner ,researcher,critic,writer,FINISH
"""


def supervisor_node(state:ReasearchState)->Command:
    # Check HIL override decisions from hil_gate first
    hil_decision = state.get("hil_decision", "")
    if hil_decision == "finalize":
        return Command(goto="writer", update={"next_agent": "writer", "hil_decision": "none"})
    elif hil_decision == "continue":
        return Command(goto="researcher", update={"next_agent": "researcher", "hil_decision": "none"})

    # hard coded safety :never loop more than 3 times regardless of llm decision
    if state.get("research_iterations",0)>=3 and not state.get("final_report"):
        job_id = state.get("job_id")
        if job_id:
            from src.persistence.db import log_hil_decision
            log_hil_decision(
                job_id=job_id,
                iteration=state.get("research_iterations", 0),
                decision="auto_capped",
                gaps=state.get("gaps_identified", []),
            )
        return Command(goto="writer", update={"next_agent": "writer"})
        
    if state.get("final_report"):
        return Command(goto="__end__")
        
    llm = ChatGroq(
        model="llama-3.3-70b-versatile",
        api_key=os.getenv("GROQ_API_KEY"),
        temperature=0,
    )
    state_summary = f"""
        query: {state.get('query')}
        sub_questions set: {bool(state.get('sub_questions'))}
        findings count: {len(state.get('research_findings', []))}
        gaps identified: {bool(state.get('gaps_identified'))}
        research_iterations: {state.get('research_iterations', 0)}
        final_report ready: {bool(state.get('final_report'))}
        """
        
    response = llm.invoke([
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=state_summary)
    ])
    
    next_agent = response.content.strip().lower()
    if next_agent not in AGENTS:
        next_agent = "writer" #safe fallback
    
    goto = "__end__" if next_agent == "finish" else next_agent
    return Command(goto=goto , update={"next_agent": next_agent})