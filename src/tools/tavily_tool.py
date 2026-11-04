import os 
from tavily import TavilyClient

def tavily_search(query: str, max_results:int = 5)->list[dict]:
    """Returns a list of dicts :[{title, url,content score},...]
    Returns [] on any error so the researcher never crashes
    """
    try: 
        client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
        response = client.search(
            query=query,
            max_results=max_results,
            search_depth="basic",
            include_answer=True, #short ai summary alongside raw results
        )
        return response.get("results", [])
    except Exception as e:
        return [{"title":"Error","url":"","content":f"Tavily Error: {e}","score":0}]