import json
import os
from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Any
from xml.etree import ElementTree as ET

from main import get_output_path
from src.services.paper_search import _is_noise_paper


def load_papers(
    output_dir: str,
    conference: str,
    year: int,
    aliases: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Load saved papers for one conference/year pair."""
    output_path = _find_existing_output(output_dir, conference, year, aliases or [])
    if not os.path.exists(output_path):
        return []

    with open(output_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        return []
    return [
        item
        for item in data
        if isinstance(item, dict) and not _is_noise_paper(item)
    ]


def _find_existing_output(output_dir: str, conference: str, year: int, aliases: list[str]) -> str:
    candidates = []
    for value in [conference, *aliases]:
        if value and value not in candidates:
            candidates.append(value)

    for value in candidates:
        output_path = get_output_path(output_dir, value, year)
        if os.path.exists(output_path):
            return output_path

    return get_output_path(output_dir, conference, year)


def build_rss_xml(
    papers: list[dict[str, Any]],
    conference: str,
    year: int,
    feed_url: str | None = None,
) -> str:
    """Build an RSS 2.0 XML document from saved paper dictionaries."""
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")

    title = f"PaperCollect: {conference} {year}"
    now = format_datetime(datetime.now(timezone.utc))

    ET.SubElement(channel, "title").text = title
    ET.SubElement(channel, "link").text = feed_url or ""
    ET.SubElement(channel, "description").text = (
        f"Collected papers for {conference} {year} from PaperCollect."
    )
    ET.SubElement(channel, "language").text = "en-us"
    ET.SubElement(channel, "lastBuildDate").text = now

    for paper in papers:
        item = ET.SubElement(channel, "item")
        paper_title = str(paper.get("title") or "Untitled paper")
        paper_url = str(paper.get("url") or "")
        guid = str(
            paper.get("dblp_key")
            or paper.get("source_id")
            or paper_url
            or f"{conference}-{year}-{paper_title}"
        )

        ET.SubElement(item, "title").text = paper_title
        ET.SubElement(item, "link").text = paper_url
        ET.SubElement(item, "guid", isPermaLink="false").text = guid
        ET.SubElement(item, "pubDate").text = now
        ET.SubElement(item, "description").text = _build_description(paper)

    return ET.tostring(rss, encoding="unicode", xml_declaration=True)


def _build_description(paper: dict[str, Any]) -> str:
    authors = paper.get("authors") or []
    if isinstance(authors, list):
        author_text = ", ".join(str(author) for author in authors if author)
    else:
        author_text = str(authors)

    parts = []
    venue = paper.get("venue")
    year = paper.get("year")
    if venue or year:
        parts.append(f"Venue: {venue or 'Unknown'} {year or ''}".strip())
    if author_text:
        parts.append(f"Authors: {author_text}")
    if paper.get("abstract"):
        parts.append(str(paper["abstract"]))

    return "\n\n".join(parts) if parts else "No summary available."
