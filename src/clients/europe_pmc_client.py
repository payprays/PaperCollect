import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from src.core.models import Paper
from src.core.interfaces import MetadataSource
from src.core.exceptions import RateLimitException

class EuropePMCClient(MetadataSource):
    """
    Implementation of MetadataSource using the Europe PMC API.
    """
    BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

    def __init__(self):
        self.session = requests.Session()
        retries = Retry(total=2, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
        self.session.mount('https://', HTTPAdapter(max_retries=retries))

    def enrich_paper(self, paper: Paper) -> Paper:
        params = {
            "query": f'TITLE:"{paper.title}"',
            "format": "json",
            "pageSize": 1
        }
        
        headers = {
            "User-Agent": "PaperCollect/1.0 (mailto:papercollect@example.com)"
        }

        try:
            response = self.session.get(self.BASE_URL, params=params, headers=headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                result_list = data.get("resultList", {}).get("result", [])
                
                if result_list:
                    match = result_list[0]
                    
                    if not paper.abstract:
                        paper.abstract = match.get("abstractText")
                    
                    if not paper.citation_count:
                        paper.citation_count = match.get("citedByCount")
                        
                    if not paper.paper_id:
                        paper.paper_id = match.get("id")
                        
                    if not paper.url:
                        # Europe PMC often has full text links
                        if match.get("fullTextUrlList"):
                            urls = match.get("fullTextUrlList", {}).get("fullTextUrl", [])
                            if urls:
                                paper.url = urls[0].get("url")
            
            elif response.status_code == 429:
                print(f"Rate limit hit (EuropePMC) for paper: {paper.title[:30]}")
                raise RateLimitException("EuropePMC rate limit hit")

        except requests.RequestException as e:
            print(f"Error fetching from Europe PMC for {paper.title}: {e}")
        except Exception as e:
            print(f"Unexpected error in Europe PMC client for {paper.title}: {e}")
            
        return paper
