import requests
import time
from typing import Optional
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from src.core.models import Paper
from src.core.interfaces import MetadataSource
from src.core.exceptions import RateLimitException

class OpenAlexClient(MetadataSource):
    """
    Implementation of MetadataSource using the OpenAlex API.
    OpenAlex is a free and open catalog of the world's scholarly papers.
    """
    BASE_URL = "https://api.openalex.org/works"

    def __init__(self):
        # Configure retry strategy
        self.session = requests.Session()
        retries = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
        self.session.mount('https://', HTTPAdapter(max_retries=retries))


    def _reconstruct_abstract(self, inverted_index: dict) -> str | None:
        """
        Reconstructs the abstract from the inverted index provided by OpenAlex.
        """
        if not inverted_index:
            return None

        # Create a list of (index, word) tuples
        word_index_pairs = []
        for word, positions in inverted_index.items():
            for pos in positions:
                word_index_pairs.append((pos, word))

        # Sort by index
        word_index_pairs.sort(key=lambda x: x[0])

        # Join words to form the abstract
        return " ".join([word for _, word in word_index_pairs])


    def enrich_paper(self, paper: Paper) -> Paper:
        """
        Searches for the paper on OpenAlex by title and adds metadata.
        """
        # Search query using the title
        params = {
            "search": paper.title,
            "per-page": 1,
        }

        try:
            # Using a polite email is good practice for OpenAlex
            headers = {
                "User-Agent": "PaperCollect/1.0 (mailto:your-email@example.com)"
            }

            response = self.session.get(self.BASE_URL, params=params, headers=headers, timeout=30)

            if response.status_code == 200:
                data = response.json()
                results = data.get("results", [])

                if results:
                    match = results[0]

                    # Reconstruct abstract if present
                    if not paper.abstract:
                        inverted_index = match.get("abstract_inverted_index")
                        paper.abstract = self._reconstruct_abstract(inverted_index)

                    if not paper.citation_count:
                        paper.citation_count = match.get("cited_by_count")

                    # OpenAlex provides referenced_works list
                    if not paper.reference_count:
                        paper.reference_count = len(match.get("referenced_works", []))

                    if not paper.paper_id:
                        paper.paper_id = match.get("id") # OpenAlex ID

                    # If we don't have a URL yet, OpenAlex might have a DOI or landing page
                    if not paper.url:
                        paper.url = match.get("doi") or match.get("id")
                return paper

            elif response.status_code == 429:
                print(f"Rate limit hit (OpenAlex) for paper: {paper.title[:30]}")
                raise RateLimitException("OpenAlex rate limit hit")

            else:
                pass
                # print(f"Failed to find metadata (OpenAlex) for: {paper.title} (Status: {response.status_code})")
                return paper

        except requests.RequestException as e:
            print(f"Error fetching metadata from OpenAlex for {paper.title}: {e}")
            return paper

        return paper
