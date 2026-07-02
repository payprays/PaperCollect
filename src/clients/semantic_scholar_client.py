import requests
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from src.core.models import Paper
from src.core.interfaces import MetadataSource
from src.core.exceptions import RateLimitException

class SemanticScholarClient(MetadataSource):
    """
    Implementation of MetadataSource using the Semantic Scholar API.
    """
    BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/search"

    def __init__(self):
        self.session = requests.Session()
        retries = Retry(total=2, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
        self.session.mount('https://', HTTPAdapter(max_retries=retries))

    def enrich_paper(self, paper: Paper) -> Paper:
        """
        Searches for the paper on Semantic Scholar by title and adds metadata.
        """
        # Search query using the title
        params = {
            "query": paper.title,
            "limit": 1,
            "fields": "abstract,citationCount,referenceCount,paperId"
        }

        try:
            # Semantic Scholar has rate limits, adding a small delay is polite if we don't have an API key
            time.sleep(1)

            response = self.session.get(self.BASE_URL, params=params, timeout=30)

            if response.status_code == 200:
                data = response.json()
                if data.get("total", 0) > 0 and data.get("data"):
                    match = data["data"][0]

                    # Update paper with found metadata
                    if not paper.abstract:
                        paper.abstract = match.get("abstract")
                    
                    if not paper.citation_count:
                        paper.citation_count = match.get("citationCount")
                    
                    if not paper.reference_count:
                        paper.reference_count = match.get("referenceCount")
                        
                    if not paper.paper_id:
                        paper.paper_id = match.get("paperId")
                return paper # Success or not found, but request completed

            elif response.status_code == 429:
                print(f"Rate limit hit (Semantic Scholar) for paper: {paper.title[:30]}")
                raise RateLimitException("Semantic Scholar rate limit hit")

            else:
                # print(f"Failed to find metadata for: {paper.title} (Status: {response.status_code})")
                return paper

        except requests.RequestException as e:
            print(f"Error fetching metadata from Semantic Scholar for {paper.title}: {e}")
            return paper

        return paper
