import time
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
    SEARCH_PAGE_SIZE = 100
    SEARCH_PAGE_DELAY_SECONDS = 1.5

    def __init__(
        self,
        timeout: float | tuple[float, float] = DEFAULT_TIMEOUT,
        search_page_delay: float = SEARCH_PAGE_DELAY_SECONDS,
    ):
        # Configure retry strategy for robustness
        self.timeout = timeout
        self.search_page_delay = search_page_delay
        self.session = requests.Session()
        retries = Retry(
            total=4,
            connect=2,
            read=2,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET"]),
            respect_retry_after_header=True,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retries))
        self.session.headers.update({"User-Agent": "PaperCollect/0.1 research crawler"})

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
        "pldi": ["PLDI", "Proc. ACM Program. Lang."],
        "popl": ["POPL", "Proc. ACM Program. Lang."],
        "oopsla": ["OOPSLA", "Proc. ACM Program. Lang."],
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
        allowed_venues = [
            target_conference,
            target_conference.upper(),
            *self.VENUE_WHITELIST.get(target, []),
        ]
        
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
            toc_error = None
            try:
                papers = self._fetch_from_toc(conference, year, dblp_stream, venue_aliases)
            except DBLPFetchError as exc:
                toc_error = exc
            else:
                if papers is not None:
                    return papers

            try:
                return self._fetch_from_search(conference, year, dblp_stream=dblp_stream, venue_aliases=venue_aliases)
            except DBLPFetchError as exc:
                if toc_error is not None:
                    raise DBLPFetchError(f"{toc_error}; venue-search fallback also failed: {exc}") from exc
                raise

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
        trust_query_scope = query.startswith("stream:")

        try:
            papers = []
            first = 0
            page_count = 0
            while True:
                if page_count > 0:
                    time.sleep(self.search_page_delay)
                page_count += 1
                params = {
                    "q": query,
                    "h": self.SEARCH_PAGE_SIZE,
                    "f": first,
                    "format": "json",
                }
                try:
                    response = self.session.get(self.BASE_URL, params=params, timeout=self.timeout)
                    response.raise_for_status()
                except requests.RequestException:
                    raise
                data = response.json()
                hits_root = data.get("result", {}).get("hits", {})
                hits = self._as_hit_list(hits_root.get("hit", []))

                for hit in hits:
                    info = hit.get("info", {})
                    paper = self._paper_from_search_info(info, conference)

                    # Filter out workshops and other pollution
                    if trust_query_scope or self._is_valid_venue(paper.venue, conference, venue_aliases):
                        papers.append(paper)

                if not hits:
                    break

                sent = self._safe_int(hits_root.get("@sent"), len(hits))
                page_first = self._safe_int(hits_root.get("@first"), first)
                total = self._safe_int(hits_root.get("@total"), None)
                next_first = page_first + sent

                if sent <= 0:
                    break
                if total is not None:
                    if next_first >= total:
                        break
                elif sent < self.SEARCH_PAGE_SIZE:
                    break
                first = next_first

            return papers

        except (requests.RequestException, ValueError) as e:
            raise DBLPFetchError(f"Could not fetch DBLP search data for {conference} {year}: {e}") from e

    def _as_hit_list(self, hits: list[dict] | dict | None) -> list[dict]:
        if hits is None:
            return []
        if isinstance(hits, dict):
            return [hits]
        if isinstance(hits, list):
            return hits
        return []

    def _paper_from_search_info(self, info: dict, conference: str) -> Paper:
        authors_data = info.get("authors", {}).get("author", [])
        if isinstance(authors_data, dict):
            authors = [authors_data.get("text", "")]
        elif isinstance(authors_data, list):
            authors = [a.get("text", "") for a in authors_data]
        else:
            authors = []

        return Paper(
            title=info.get("title", ""),
            authors=authors,
            year=int(info.get("year", 0)),
            venue=info.get("venue", conference),
            dblp_key=info.get("key"),
            url=info.get("url"),
        )

    def _safe_int(self, value: object, default: int | None) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

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
        volume = self._toc_volume(parts[-1], year)
        return f"{self.DB_URL}/{'/'.join(parts)}/{volume}.xml"

    def _toc_volume(self, stream_name: str, year: int) -> str:
        if stream_name == "nips" and year >= 2018:
            return f"neurips{year}"
        return f"{stream_name}{year}"

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
