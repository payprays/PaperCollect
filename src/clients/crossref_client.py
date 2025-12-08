import requests
import time
from typing import Optional
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from src.core.models import Paper
from src.core.interfaces import MetadataSource
from src.core.exceptions import RateLimitException

class CrossrefClient(MetadataSource):
    """
    Implementation of MetadataSource using the Crossref API.
    """
    BASE_URL = "https://api.crossref.org/works"

    def __init__(self):
        self.session = requests.Session()
        retries = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
        self.session.mount('https://', HTTPAdapter(max_retries=retries))

    def enrich_paper(self, paper: Paper) -> Paper:
        """
        Searches for the paper on Crossref by title and adds metadata.
        """
        # Crossref search is robust with titles
        params = {
            "query.bibliographic": paper.title,
            "rows": 1,
            "select": "DOI,title,abstract,is-referenced-by-count,reference-count"
        }

        try:
            headers = {
                "User-Agent": "PaperCollect/1.0 (mailto:papercollect@example.com)" # Replace with real email if possible
            }

            response = self.session.get(self.BASE_URL, params=params, headers=headers, timeout=30)

            if response.status_code == 200:
                data = response.json()
                items = data.get("message", {}).get("items", [])

                if items:
                    match = items[0]
                    # Check if title matches reasonably well? Crossref fuzzy search is usually good.
                    # For now, assume top hit is correct if we trust the query.

                    # Crossref abstracts are XML often, stripping tags might be needed,
                    # but for now let's just grab it if it exists.
                    if not paper.abstract:
                        abstract_raw = match.get("abstract")
                        if abstract_raw:
                            # Simple cleanup of <jats:p> tags if present
                            paper.abstract = abstract_raw.replace("<jats:p>", "").replace("</jats:p>", "").strip()

                    if not paper.citation_count:
                        paper.citation_count = match.get("is-referenced-by-count")

                    if not paper.reference_count:
                        paper.reference_count = match.get("reference-count")

                    if not paper.url:
                        paper.url = f"https://doi.org/{match.get('DOI')}"
                return paper

            elif response.status_code == 429:
                print(f"Rate limit hit (Crossref) for paper: {paper.title[:30]}")
                raise RateLimitException("Crossref rate limit hit")

        except requests.RequestException as e:
            print(f"Error fetching metadata from Crossref for {paper.title}: {e}")
            return paper

        return paper
