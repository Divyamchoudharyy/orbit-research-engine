import wikipedia

def wikipedia_search(query:str)->dict:
    """Returns {title,summary,url} or {error} or failure"""
    
    try:
        wikipedia.set_lang("en")
        page = wikipedia.page(query,auto_suggest=False)
        return{
            "title": page.title,
            "summary":wikipedia.summary(query,sentences=5,auto_suggest=False),
            "url": page.url
        }
    except wikipedia.DisambiguationError as e:
            try:
                page= wikipedia.page(e.options[0],auto_suggest=False)
                return{
                    "title": page.title,
                    "summary":wikipedia.summary(e.options[0],sentences=5,auto_suggest=False),
                    "url": page.url
                }
            except Exception:
                return {"error": f"DisambiguationError: {e.options[:3]}"}
    except Exception as e:
            return{"error": str(e)}