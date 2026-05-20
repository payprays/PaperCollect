from typing import List
from xml.etree import ElementTree

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.core.interfaces import PaperSource
from src.core.models import Paper


class DBLPFetchError(RuntimeError):
    """Raised when DBLP could not be queried reliably."""


class DBLPClient(PaperSource):
    """
    Implementation of PaperSource using the DBLP API.
    """
    BASE_URL = "https://dblp.org/search/publ/api"
    DB_URL = "https://dblp.org/db"
    DEFAULT_TIMEOUT = (10, 30)

    def __init__(self, timeout: float | tuple[float, float] = DEFAULT_TIMEOUT):
        # Configure retry strategy for robustness
        self.timeout = timeout
        self.session = requests.Session()
        retries = Retry(
            total=2,
            connect=2,
            read=0,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=frozenset(["GET"]),
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retries))

    # Fallback aliases for legacy string-only configs. New code should pass
    # venue_aliases from src.core.conference_catalog.
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

    def _is_valid_venue(
        self,
        paper_venue: str | List[str],
        target_conference: str,
        venue_aliases: list[str] | None = None,
    ) -> bool:
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
        allowed_venues = self.VENUE_WHITELIST.get(target, [])
        
        if venue_aliases:
            allowed_venues = [*allowed_venues, *venue_aliases]

        if not allowed_venues:
            # Fallback to old logic if not in whitelist (or just strict equality)
            # For now, let's be strict but allow exact match of target
            allowed_venues = [target_conference, target_conference.upper()]

        allowed_lookup = {str(value).lower() for value in allowed_venues}

        # Check if ANY of the paper's venues match ANY of the allowed venues EXACTLY
        for v in venues:
            # Check exact match against whitelist
            if str(v).lower() in allowed_lookup:
                return True
                
        return False

    def fetch_papers(
        self,
        conference: str,
        year: int,
        dblp_stream: str | None = None,
        dblp_query: str | None = None,
        venue_aliases: list[str] | None = None,
    ) -> List[Paper]:
        """
        Fetches papers for a given conference and year from DBLP.
        Note: conference name usually matches the DBLP venue short name (e.g., "ICSE", "NeurIPS", "CVPR").
        """
        if dblp_stream and not dblp_query:
            papers = self._fetch_from_toc(conference, year, dblp_stream, venue_aliases)
            return papers or []

        return self._fetch_from_search(
            conference,
            year,
            dblp_stream=dblp_stream,
            dblp_query=dblp_query,
            venue_aliases=venue_aliases,
        )

    def _fetch_from_search(
        self,
        conference: str,
        year: int,
        dblp_stream: str | None = None,
        dblp_query: str | None = None,
        venue_aliases: list[str] | None = None,
    ) -> list[Paper]:
        if dblp_query:
            query = dblp_query.format(year=year)
        elif dblp_stream:
            query = f"stream:{dblp_stream}: year:{year}"
        else:
            query = f"venue:{conference} year:{year}"

        params = {
            "q": query,
            "h": 1000,  # Max results
            "format": "json"
        }

        try:
            response = self.session.get(self.BASE_URL, params=params, timeout=self.timeout)
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
                if self._is_valid_venue(paper.venue, conference, venue_aliases):
                    papers.append(paper)

            return papers

        except (requests.RequestException, ValueError) as e:
            raise DBLPFetchError(f"Could not fetch DBLP search data for {conference} {year}: {e}") from e

    def _fetch_from_toc(
        self,
        conference: str,
        year: int,
        dblp_stream: str,
        venue_aliases: list[str] | None = None,
    ) -> list[Paper] | None:
        toc_url = self._toc_url(dblp_stream, year)
        if toc_url is None:
            return None

        try:
            response = self.session.get(toc_url, timeout=self.timeout)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            root = ElementTree.fromstring(response.content)
        except (ElementTree.ParseError, requests.RequestException) as e:
            raise DBLPFetchError(f"Could not fetch DBLP TOC data for {conference} {year}: {e}") from e

        papers = []
        for item in self._publication_items(root):
            paper_year = self._first_text(item, "year")
            if paper_year and not self._year_matches(paper_year, year):
                continue

            venues = self._venue_values(item)
            if not self._is_valid_venue(venues, conference, venue_aliases):
                continue

            papers.append(
                Paper(
                    title=self._element_text(item.find("title")),
                    authors=[self._element_text(author) for author in item.findall("author")],
                    year=year,
                    venue=venues[0] if venues else conference,
                    dblp_key=item.get("key"),
                    url=self._first_text(item, "ee") or self._dblp_record_url(item.get("key")),
                )
            )

        return papers

    def _publication_items(self, root: ElementTree.Element) -> list[ElementTree.Element]:
        return [
            item
            for tag in ("article", "inproceedings")
            for item in root.findall(f".//{tag}")
        ]

    def _toc_url(self, dblp_stream: str, year: int) -> str | None:
        parts = [part for part in dblp_stream.strip("/").split("/") if part]
        if len(parts) < 2:
            return None
        volume = f"{parts[-1]}{year}"
        return f"{self.DB_URL}/{'/'.join(parts)}/{volume}.xml"

    def _venue_values(self, item: ElementTree.Element) -> list[str]:
        return [
            value
            for value in [
                self._first_text(item, "booktitle"),
                self._first_text(item, "journal"),
            ]
            if value
        ]

    def _first_text(self, item: ElementTree.Element, tag: str) -> str | None:
        child = item.find(tag)
        value = self._element_text(child)
        return value or None

    def _year_matches(self, value: str, year: int) -> bool:
        try:
            return int(value) == year
        except ValueError:
            return False

    def _element_text(self, item: ElementTree.Element | None) -> str:
        if item is None:
            return ""
        return " ".join("".join(item.itertext()).split())

    def _dblp_record_url(self, key: str | None) -> str | None:
        if not key:
            return None
        return f"https://dblp.org/rec/{key}"
