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

    # Whitelist of valid venue strings for each conference
    # Keys should be lowercased conference names (or aliases)
    VENUE_WHITELIST = {
        "icse": ["ICSE"],
        "ase": ["ASE"],
        "fse": ["FSE", "ESEC/SIGSOFT FSE", "SIGSOFT FSE"],
        "issta": ["ISSTA"],
        "ndss": ["NDSS"],
        "sp": ["SP", "IEEE Symposium on Security and Privacy", "S&P"],
        "usenix security": ["USENIX Security Symposium", "USENIX Security"],
        "ccs": ["CCS", "ACM Conference on Computer and Communications Security"],
        "esorics": ["ESORICS"],
        "dsn": ["DSN", "Dependable Systems and Networks"],
        "dimva": ["DIMVA"],
        "pldi": ["PLDI"],
        "popl": ["POPL"],
        "osdi": ["OSDI", "USENIX Symposium on Operating Systems Design and Implementation"],
        "sosp": ["SOSP", "ACM Symposium on Operating Systems Principles"],
        "fm": ["FM", "International Symposium on Formal Methods"],
        "raid": ["RAID"],
        "acsac": ["ACSAC"],
        "asiaccs": ["ASIACCS", "ACM Asia Conference on Computer and Communications Security"],
        "euro s&p": ["EuroS&P", "IEEE European Symposium on Security and Privacy"],
        "euros&p": ["EuroS&P", "IEEE European Symposium on Security and Privacy"],
    }

    def _is_valid_venue(self, paper_venue: str | List[str], target_conference: str) -> bool:
        """
        Validates if the paper venue matches the target conference main track,
        using a strict whitelist approach.
        """
        if not paper_venue:
            return False # If no venue info, reject it (strict)
            
        if isinstance(paper_venue, str):
            venues = [paper_venue]
        else:
            venues = paper_venue
            
        target = target_conference.lower()
        
        # Get allowed venues for this target
        allowed_venues = self.VENUE_WHITELIST.get(target)
        
        if not allowed_venues:
            # Fallback to old logic if not in whitelist (or just strict equality)
            # For now, let's be strict but allow exact match of target
            allowed_venues = [target_conference, target_conference.upper()]
            
        # Check if ANY of the paper's venues match ANY of the allowed venues EXACTLY
        for v in venues:
            # Check exact match against whitelist
            if v in allowed_venues:
                return True
                
        return False

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
        elif conference.lower() == "ccs":
             # ACM CCS
             query = f"venue:CCS year:{year}"
        elif conference.lower() == "esorics":
             # ESORICS
             query = f"venue:ESORICS year:{year}"
        elif conference.lower() == "raid":
             # RAID
             query = f"venue:RAID year:{year}"
        elif conference.lower() == "acsac":
             # ACSAC
             query = f"venue:ACSAC year:{year}"
        elif conference.lower() == "asiaccs":
             # ASIACCS
             query = f"venue:ASIACCS year:{year}"
        elif "euro" in conference.lower() and "s&p" in conference.lower():
             # IEEE EuroS&P
             query = f"venue:EuroS&P year:{year}"
        elif conference.lower() == "dsn":
             # DSN (Dependable Systems and Networks)
             query = f"venue:DSN year:{year}"
        elif conference.lower() == "dimva":
             # DIMVA
             query = f"venue:DIMVA year:{year}"
        elif conference.lower() == "fm":
             # Formal Methods (International Symposium on Formal Methods)
             # Use stream to avoid ambiguity
             query = f"stream:conf/fm: year:{year}"
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
