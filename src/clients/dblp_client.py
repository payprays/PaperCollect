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

    def _is_valid_venue(self, paper_venue: str | List[str], target_conference: str) -> bool:
        """
        Validates if the paper venue matches the target conference main track,
        filtering out workshops, companions, etc.
        """
        if not paper_venue:
            return True # If no venue info, keep it (conservative)
            
        if isinstance(paper_venue, str):
            venues = [paper_venue]
        else:
            venues = paper_venue
            
        target = target_conference.lower()
        
        # Keywords that usually indicate non-main-track papers
        exclusion_keywords = [
            "workshop", "companion", "adjunct", "doctoral", "demonstration", 
            "poster", "tool", "demo", "tutorial", "panel", "keynote"
        ]
        
        # Specific exclusions for known conferences
        if "ase" in target:
            exclusion_keywords.extend(["asew", "rene", "nier"])
        elif "icse" in target:
            exclusion_keywords.extend(["seip", "seis", "nier", "icse-c", "icse-seip", "icse-seis"])
        elif "fse" in target:
            exclusion_keywords.extend(["fsen", "games", "nier", "ideas", "visions"])
        elif "issta" in target:
            exclusion_keywords.extend(["debt", "vortex", "ecoop"]) # ECOOP sometimes co-located
        elif "usenix" in target:
            exclusion_keywords.extend(["soups", "woot", "cset", "leet", "foci", "hotsec"])
            
        for v in venues:
            v_lower = v.lower()
            
            # Check for exclusion keywords
            if any(kw in v_lower for kw in exclusion_keywords):
                return False
                
            # Check for "@" which often indicates a workshop (e.g., "A-TEST@FSE")
            if "@" in v_lower:
                return False
                
        return True

    def fetch_papers(self, conference: str, year: int) -> List[Paper]:
        """
        Fetches papers for a given conference and year from DBLP.
        Note: conference name usually matches the DBLP venue short name (e.g., "ICSE", "NeurIPS", "CVPR").
        """
        # Query format: venue:Conference+year:Year
        # Handle special cases for DBLP queries if needed, though most work with simple names.
        # "sp" often needs specific handling if it conflicts, but usually "venue:sp:" works or "venue:IEEE_Symposium_on_Security_and_Privacy"
        
        # Special handling for "SP" (IEEE Symposium on Security and Privacy)
        # DBLP uses "IEEE Symposium on Security and Privacy" or "S&P" which is tricky.
        # The venue key is often "conf/sp".
        if conference.lower() == "sp":
             # Try searching by the short venue code directly which is more reliable
             # DBLP venue code for S&P is "conf/sp"
             # The query syntax stream:conf/sp: matches the stream (series)
             query = f"stream:conf/sp: year:{year}"
        else:
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
                
                # Filter out workshops and other pollution
                if self._is_valid_venue(paper.venue, conference):
                    papers.append(paper)

            return papers

        except requests.RequestException as e:
            print(f"Error fetching data from DBLP for {conference} {year}: {e}")
            return []
