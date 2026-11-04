from typing import Annotated,TypedDict 
# pyrefly: ignore [missing-import]
from langgraph.graph.message import add_messages

class ReasearchState(TypedDict):
    
    #------------Input ------ 
    query: str
    depth: str 
    
    # ------Agent working memory ----- 
    messages: Annotated[list,add_messages] # reducer:appends,never overwrites 
    sub_questions: list[str] #planner fills this 
    research_findings: list[str] #reasearcher accumulates this
    gaps_identified: list[str] #critics fill this
    research_iterations: int #superviser incremets this
    
    #output 
    final_report: str 
    sources: list[str]
    
    #routing 
    next_agent: str #superviser sets this each turn 
    
    # HIL tracking
    job_id: str
    hil_decision: str # "continue" | "finalize" | "auto_finalize" | "auto_capped"