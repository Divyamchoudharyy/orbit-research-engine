import os
from langchain_groq import ChatGroq
from src.graph.state import ReasearchState
from langchain_core.messages import AIMessage,SystemMessage,HumanMessage
from src.api.stream_manager import stream_manager 

_SYSTEM_PROMPT = """You are a critical research reviewer. Your job is to identify GAPS in research provided.

Review rules:
- Check if the original query is fully answered by the findings
- Check if any sub-questions are poorly covered or missing
- Identify specific missing topics, time periods, or perspectives
- Output ONLY a bulleted list of gaps, or output exactly: NO_GAPS if research is sufficient
- Be concise — max 3 gaps, each a single sentence
- Example output with gaps:
• Missing: recent post-2024 developments in the field
• Insufficient coverage of industrial applications
• No mention of regulatory or ethical challenges

Example output without gaps:
NO_GAPS
"""

def critic_node(state:ReasearchState)->dict:
    job_id =state.get("job_id")
    if job_id:
        stream_manager.publish(job_id,{
            "type":"log",
            "message":"Critic: Reviewing findings and identifying gaps..."
        })
    llm = ChatGroq(
        model="llama-3.3-70b-versatile",
        api_key=os.getenv("GROQ_API_KEY"),
        temperature=0,
    )
    findings_summary = "\n".join(state.get("research_findings",[])[:20]) #cap at 20 to stay in context 
    sub_questions_text = "\n".join(state.get("sub_questions",[]))
    
    review_prompt = f"""Original query: {state['query']}
    Sub-questions: that should be answered:{sub_questions_text}
    
    Research findings gathered so far:
    {findings_summary}
    
    identify any gaps in coverage.
    """ 
    response = llm.invoke([
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=review_prompt)
    ])
    
    content = response.content.strip()
    if "NO_GAPS" in content.upper():
        gaps = []
        msg = "Critic : research is sufficient, no gaps identified."
    else:
        #parse bulleted list
        gaps = [
            line.lstrip("•-* ").strip()
            for line in content.split("\n")
            if line.strip() and line.strip()[0] in ("•", "-", "*")
        ]
        msg = f"Critic: identified {len(gaps)} gap(s) — routing back to researcher."

    if job_id:
        stream_manager.publish(job_id,{
            "type":"log",
            "message": msg
        })

    return {
        "gaps_identified": gaps,
        "messages": [AIMessage(content=msg)],
    }