import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.core.conference_catalog import ConferenceEntry
from src.core.models import Paper


class OfficialSourceFetchError(RuntimeError):
    """Raised when an official fallback source cannot be fetched reliably."""


class OfficialSourceClient:
    """Fetches papers from whitelisted official conference sources."""

    DEFAULT_TIMEOUT = (10, 30)

    def __init__(self, timeout: float | tuple[float, float] = DEFAULT_TIMEOUT):
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

    def fetch_papers(self, conference: ConferenceEntry, year: int) -> list[Paper]:
        source = conference.official_source
        source_type = source.get("type")
        if not source_type:
            return []
        if source_type == "miniconf":
            return self._fetch_miniconf(conference, year, source)
        if source_type == "ieee_sp_accepted":
            return self._fetch_ieee_sp_accepted(conference, year, source)
        if source_type == "researchr_accepted":
            return self._fetch_researchr_accepted(conference, year, source)
        raise OfficialSourceFetchError(
            f"Unsupported official source type for {conference.display_name}: {source_type}"
        )

    def _fetch_miniconf(
        self,
        conference: ConferenceEntry,
        year: int,
        source: dict[str, Any],
    ) -> list[Paper]:
        papers_url = self._format_url(source.get("papers_url"), year)
        if not papers_url:
            return []

        payload = self._get_json(papers_url)
        if payload is None:
            return []
        results = payload.get("results", []) if isinstance(payload, dict) else []
        if not isinstance(results, list):
            raise OfficialSourceFetchError(
                f"Official source for {conference.display_name} {year} returned invalid results."
            )

        abstracts = self._fetch_optional_abstracts(source, year)
        event_type = str(source.get("event_type") or "Poster")
        page_url = self._format_url(source.get("page_url"), year) or papers_url
        papers = []
        seen = set()
        for raw in results:
            if not isinstance(raw, dict):
                continue
            if event_type and raw.get("eventtype") != event_type:
                continue
            if raw.get("visible") is False:
                continue

            paper_id = str(raw.get("id") or raw.get("uid") or "").strip()
            title = str(raw.get("name") or "").strip()
            if not title:
                continue
            key = paper_id or title
            if key in seen:
                continue
            seen.add(key)

            authors = [
                str(author.get("fullname") or "").strip()
                for author in raw.get("authors", [])
                if isinstance(author, dict) and str(author.get("fullname") or "").strip()
            ]
            paper_url = self._absolute_url(page_url, raw.get("virtualsite_url") or raw.get("url"))
            abstract = abstracts.get(paper_id) if paper_id else None

            papers.append(
                Paper(
                    title=title,
                    authors=authors,
                    year=year,
                    venue=conference.display_name,
                    url=paper_url or page_url,
                    abstract=abstract,
                    paper_id=f"official:{conference.id}:{year}:{key}",
                    source=f"official:{source.get('type')}",
                    source_url=page_url,
                )
            )

        return papers

    def _fetch_ieee_sp_accepted(
        self,
        conference: ConferenceEntry,
        year: int,
        source: dict[str, Any],
    ) -> list[Paper]:
        page_url = self._format_url(source.get("page_url"), year)
        if not page_url:
            return []

        html = self._get_text(page_url)
        if html is None:
            return []

        parser = _IEEESPAcceptedPapersParser(page_url)
        parser.feed(html)

        papers = []
        seen_titles = set()
        for index, item in enumerate(parser.items):
            title = item.get("title", "").strip()
            if not title:
                continue
            normalized_title = re.sub(r"\s+", " ", title).casefold()
            if normalized_title in seen_titles:
                continue
            seen_titles.add(normalized_title)

            authors = item.get("authors", [])
            item_url = item.get("url") or page_url
            key = item.get("fragment") or str(index)
            papers.append(
                Paper(
                    title=title,
                    authors=authors,
                    year=year,
                    venue=conference.display_name,
                    url=item_url,
                    paper_id=f"official:{conference.id}:{year}:{key}",
                    source=f"official:{source.get('type')}",
                    source_url=page_url,
                )
            )

        return papers

    def _fetch_researchr_accepted(
        self,
        conference: ConferenceEntry,
        year: int,
        source: dict[str, Any],
    ) -> list[Paper]:
        page_url = self._format_url(source.get("page_url"), year)
        if not page_url:
            return []

        html = self._get_text(page_url)
        if html is None:
            return []

        parser = _ResearchrAcceptedPapersParser(page_url)
        parser.feed(html)
        parser.close()

        papers = []
        seen_titles = set()
        for index, item in enumerate(parser.items):
            title = item.get("title", "").strip()
            if not title:
                continue
            normalized_title = re.sub(r"\s+", " ", title).casefold()
            if normalized_title in seen_titles:
                continue
            seen_titles.add(normalized_title)

            event_id = item.get("event_id") or str(index)
            papers.append(
                Paper(
                    title=title,
                    authors=item.get("authors", []),
                    year=year,
                    venue=conference.display_name,
                    url=item.get("url") or page_url,
                    paper_id=f"official:{conference.id}:{year}:{event_id}",
                    source=f"official:{source.get('type')}",
                    source_url=page_url,
                )
            )

        return papers

    def _fetch_optional_abstracts(self, source: dict[str, Any], year: int) -> dict[str, str]:
        abstracts_url = self._format_url(source.get("abstracts_url"), year)
        if not abstracts_url:
            return {}
        payload = self._get_json(abstracts_url, allow_missing=True)
        if not isinstance(payload, dict):
            return {}
        return {
            str(key): str(value)
            for key, value in payload.items()
            if value is not None
        }

    def _get_json(self, url: str, allow_missing: bool = False) -> Any:
        try:
            response = self.session.get(url, timeout=self.timeout)
            if response.status_code == 404 and allow_missing:
                return None
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            raise OfficialSourceFetchError(f"Could not fetch official source data from {url}: {exc}") from exc

    def _get_text(self, url: str, allow_missing: bool = False) -> str | None:
        try:
            response = self.session.get(url, timeout=self.timeout)
            if response.status_code == 404 and allow_missing:
                return None
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            raise OfficialSourceFetchError(f"Could not fetch official source data from {url}: {exc}") from exc

    def _format_url(self, template: str | None, year: int) -> str | None:
        if not template:
            return None
        return str(template).format(year=year)

    def _absolute_url(self, base_url: str, value: str | None) -> str | None:
        if not value:
            return None
        return urljoin(base_url, str(value))


class _IEEESPAcceptedPapersParser(HTMLParser):
    """Parses the static IEEE S&P accepted-papers Bootstrap list."""

    def __init__(self, page_url: str):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.items: list[dict[str, Any]] = []
        self._current: dict[str, Any] | None = None
        self._item_div_depth = 0
        self._author_div_depth = 0
        self._sup_depth = 0
        self._capture_title = False
        self._capture_authors = False
        self._author_line_done = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {name: value or "" for name, value in attrs}
        classes = set(attrs_map.get("class", "").split())

        if tag == "div" and "list-group-item" in classes:
            self._finish_item()
            self._current = {
                "title_parts": [],
                "author_parts": [],
                "fragment": "",
            }
            self._item_div_depth = 1
            self._author_div_depth = 0
            self._capture_title = False
            self._capture_authors = False
            self._author_line_done = False
            return

        if self._current is None:
            return

        if tag == "div":
            self._item_div_depth += 1
            if "authorlist" in classes:
                self._capture_authors = True
                self._author_div_depth = self._item_div_depth
                self._author_line_done = False
            return

        if tag == "a" and attrs_map.get("data-toggle") == "collapse":
            self._capture_title = True
            href = attrs_map.get("href", "")
            if href.startswith("#"):
                self._current["fragment"] = href[1:]
            return

        if tag == "br" and self._capture_authors:
            self._author_line_done = True
            return

        if tag == "sup" and self._capture_authors:
            self._sup_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._current is None:
            return

        if tag == "a" and self._capture_title:
            self._capture_title = False
            return

        if tag == "sup" and self._sup_depth:
            self._sup_depth -= 1
            return

        if tag == "div":
            if self._capture_authors and self._item_div_depth == self._author_div_depth:
                self._capture_authors = False
                self._author_div_depth = 0

            if self._item_div_depth == 1:
                self._finish_item()
                return

            self._item_div_depth = max(0, self._item_div_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._current is None:
            return

        if self._capture_title:
            self._current["title_parts"].append(data)
            return

        if self._capture_authors and not self._author_line_done and not self._sup_depth:
            self._current["author_parts"].append(data)

    def close(self) -> None:
        self._finish_item()
        super().close()

    def _finish_item(self) -> None:
        if self._current is None:
            return

        title = _normalize_text(" ".join(self._current.get("title_parts", [])))
        if title:
            fragment = self._current.get("fragment") or ""
            authors_text = _normalize_text(" ".join(self._current.get("author_parts", [])))
            self.items.append(
                {
                    "title": title,
                    "authors": _split_authors(authors_text),
                    "fragment": fragment,
                    "url": f"{self.page_url}#{fragment}" if fragment else self.page_url,
                }
            )

        self._current = None
        self._item_div_depth = 0
        self._author_div_depth = 0
        self._sup_depth = 0
        self._capture_title = False
        self._capture_authors = False
        self._author_line_done = False


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _split_authors(value: str) -> list[str]:
    if not value:
        return []
    authors = []
    for author in re.split(r"\s*,\s*", value):
        author = _normalize_text(author)
        if author:
            authors.append(author)
    return authors


class _ResearchrAcceptedPapersParser(HTMLParser):
    """Parses conf.researchr.org accepted-papers tables."""

    def __init__(self, page_url: str):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.items: list[dict[str, Any]] = []
        self._in_overview = False
        self._overview_depth = 0
        self._current: dict[str, Any] | None = None
        self._capture_title = False
        self._title_parts: list[str] = []
        self._capture_performers = False
        self._performers_depth = 0
        self._capture_author = False
        self._author_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {name: value or "" for name, value in attrs}
        classes = set(attrs_map.get("class", "").split())

        if tag == "div" and attrs_map.get("id") == "event-overview":
            self._in_overview = True
            self._overview_depth = 1
            return

        if not self._in_overview:
            return

        if tag == "div":
            self._overview_depth += 1
            if "performers" in classes and self._current is not None:
                self._capture_performers = True
                self._performers_depth = self._overview_depth
            return

        if tag == "a" and attrs_map.get("data-event-modal"):
            self._finish_current()
            event_id = attrs_map["data-event-modal"]
            self._current = {
                "event_id": event_id,
                "authors": [],
                "fallback_url": f"{self.page_url}#{event_id}",
                "details_url": None,
                "publication_url": None,
            }
            self._capture_title = True
            self._title_parts = []
            return

        if tag == "a" and self._capture_performers:
            self._capture_author = True
            self._author_parts = []
            return

        if tag == "a" and self._current is not None and "publication-link" in classes:
            href = attrs_map.get("href")
            if href:
                url = urljoin(self.page_url, href)
                if "/details/" in url:
                    self._current["details_url"] = url
                elif not self._current.get("publication_url"):
                    self._current["publication_url"] = url

    def handle_endtag(self, tag: str) -> None:
        if not self._in_overview:
            return

        if tag == "a" and self._capture_title:
            if self._current is not None:
                self._current["title"] = _normalize_text(" ".join(self._title_parts))
            self._capture_title = False
            self._title_parts = []
            return

        if tag == "a" and self._capture_author:
            author = _normalize_text(" ".join(self._author_parts))
            if author and self._current is not None:
                self._current.setdefault("authors", []).append(author)
            self._capture_author = False
            self._author_parts = []
            return

        if tag == "div":
            if self._capture_performers and self._overview_depth == self._performers_depth:
                self._capture_performers = False
                self._performers_depth = 0

            self._overview_depth -= 1
            if self._overview_depth <= 0:
                self._finish_current()
                self._in_overview = False
                self._overview_depth = 0

    def handle_data(self, data: str) -> None:
        if self._capture_title:
            self._title_parts.append(data)
        elif self._capture_author:
            self._author_parts.append(data)

    def close(self) -> None:
        self._finish_current()
        super().close()

    def _finish_current(self) -> None:
        if self._current is None:
            return

        title = str(self._current.get("title") or "").strip()
        if title:
            url = (
                self._current.get("details_url")
                or self._current.get("publication_url")
                or self._current.get("fallback_url")
                or self.page_url
            )
            self.items.append(
                {
                    "title": title,
                    "authors": self._current.get("authors", []),
                    "event_id": self._current.get("event_id"),
                    "url": url,
                }
            )

        self._current = None
        self._capture_title = False
        self._title_parts = []
        self._capture_performers = False
        self._performers_depth = 0
        self._capture_author = False
        self._author_parts = []
