import requests
from typing import List
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from src.core.models import Paper
from src.core.interfaces import PaperSource

class DBLPClient(PaperSource):
    """
    Implementation of PaperSource using the DBLP API.
    """
    BASE_URL = "https://dblp.org/search/publ/api"

    def __init__(self):
        # Configure retry strategy for robustness
        self.session = requests.Session()
        retries = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
        self.session.mount('https://', HTTPAdapter(max_retries=retries))

    def fetch_papers(self, conference: str, year: int) -> List[Paper]:
        """
        Fetches papers for a given conference and year from DBLP.
        Note: conference name usually matches the DBLP venue short name (e.g., "ICSE", "NeurIPS", "CVPR").
        """
        # Query format: venue:Conference+year:Year
        # Handle special cases for DBLP queries if needed, though most work with simple names.
        # "sp" often needs specific handling if it conflicts, but usually "venue:sp:" works or "venue:IEEE_Symposium_on_Security_and_Privacy"
        # For simple mapping:
        query = f"venue:{conference} year:{year}"

        params = {
            "q": query,
            "h": 1000,  # Max results
            "format": "json"
        }

        try:
            response = self.session.get(self.BASE_URL, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            papers = []
            hits = data.get("result", {}).get("hits", {}).get("hit", [])

            for hit in hits:
                info = hit.get("info", {})

                # Extract authors
                authors_data = info.get("authors", {}).get("author", [])
                if isinstance(authors_data, dict):
                    authors = [authors_data.get("text", "")]
                elif isinstance(authors_data, list):
                    authors = [a.get("text", "") for a in authors_data]
                else:
                    authors = []

                # Create Paper object
                paper = Paper(
                    title=info.get("title", ""),
                    authors=authors,
                    year=int(info.get("year", 0)),
                    venue=info.get("venue", conference),
                    dblp_key=info.get("key"),
                    url=info.get("url")
                )
                papers.append(paper)

            return papers

        except requests.RequestException as e:
            print(f"Error fetching data from DBLP for {conference} {year}: {e}")
            return []
