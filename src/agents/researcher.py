import os
from src.tools.arxiv_tool import arxiv_search
from src.tools.wikipedia_tool import wikipedia_search
from src.tools.tavily_tool import tavily_search
from src.graph.state import ReasearchState
from langchain_core.messages import AIMessage
from src.api.stream_manager import stream_manager

_DEPTH_TOOLS ={
    "quick": {"tavily": 3 ,"arxiv":False, "wikipedia":False},
    "standard": {"tavily": 5 ,"arxiv":True, "wikipedia":True},
    "deep": {"tavily": 7 ,"arxiv":True, "wikipedia":True},
}

def research_node(state:ReasearchState)->dict:
    job_id = state.get("job_id")
    depth = state.get("depth","standard")
    tool_config = _DEPTH_TOOLS[depth]
    iteration = state.get("research_iterations",0) 
    sub_questions = state.get("sub_questions",[])
    
    #each call to researcher handles one sub sub-questions (indexeed by iterations)
    #if we've exhuasted sub_questions do a sirect search on gaps_ideentified in previous iterations
    gaps = state.get("gaps_identified",[])
    if iteration <len(sub_questions):
        current_query = sub_questions[iteration]
    elif gaps:
        current_query = gaps[0] 
    else:
        current_query = state["query"] #fallback to original query if no sub-questions or gaps left
        
    if job_id:
        stream_manager.publish(job_id, {
            "type": "log",
            "message": f"Researcher: starting search iteration {iteration+1} for query: '{current_query[:60]}'"
        })
        
    findings = []
    sources = list(state.get("sources",[]))
    
    #-------Tavily web search --------
    web_results = tavily_search(current_query, max_results=tool_config["tavily"])
    for r in web_results:
        if r.get("content"):
            findings.append(f"[Web] {r['title']}: {r['content'][:400]}")  
        if r.get("url"):
            sources.append(r["url"])
            
    #------- ArXiv paper search --------
    if tool_config["arxiv"]:
        papers = arxiv_search(current_query, max_results=2)
        for p in papers:
            if p.get("summary"):
                    findings.append(f"[ArXiv] {p['title']} ({p.get('published','')}) — {p['summary']}")
            if p.get("pdf_url"):
                sources.append(p["pdf_url"])

    #------- Wikipedia search --------
    if tool_config["wikipedia"]:
        wiki_result = wikipedia_search(current_query)
        if wiki_result.get("summary"):
            findings.append(f"[Wikipedia] {wiki_result['title']}: {wiki_result['summary']}")
        if wiki_result.get("url"):
            sources.append(wiki_result["url"])
            
    if job_id:
        stream_manager.publish(job_id, {
            "type": "log",
            "message": f"Researcher: completed iteration {iteration+1} with {len(findings)} findings."
        })
            
    return{
        "research_findings": state.get("research_findings",[])+findings,
        "research_iterations": iteration +1,
        "sources": sources,
        "messages":[AIMessage(content=f"Researcher: completed iteration {iteration+1} for query: '{current_query[:60]}' with {len(findings)} findings.")]
    }