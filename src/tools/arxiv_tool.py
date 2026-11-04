import time 
import arxiv

def arxiv_search(query:str ,max_results:int = 3)->list[dict]:
    """Returns a list of dicts :[{title , authors,summary,pdf_url,published},...]
    the sleep(3)is rate limit fix Arxiv 503s on rapid successive calls.
    """
    try: 
        client=arxiv.Client()
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.Relevance
        )
        results = []
        for paper in client.results(search):
            results.append({
                "title": paper.title,
                "authors": [a.name for a in paper.authors[:3]],  # first 3 authors
                "summary": paper.summary[:500],  # first 500 chars of summary
                "pdf_url": paper.pdf_url,
                "published": str(paper.published.date()),
            })
            time.sleep(3)  # rate limit fix
        return results
    except Exception as e:
        return [{"title":"Error","authors":[],"summary":f"Arxiv Error: {e}","pdf_url":"","published":""}]