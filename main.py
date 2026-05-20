import argparse
import json
import yaml
import os
import threading
from typing import List, Dict
from src.clients.dblp_client import DBLPClient
from src.clients.official_source_client import OfficialSourceClient
from src.services.metadata_manager import MetadataManager
from src.core.models import Paper
from src.core.conference_catalog import ConferenceEntry, normalize_conference, normalize_conferences

def load_config(config_path: str):
    if not os.path.exists(config_path):
        print(f"Config file {config_path} not found.")
        return None
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

def get_output_path(output_dir: str, conference: str | ConferenceEntry, year: int) -> str:
    """Returns the file path for a specific conference and year."""
    # Ensure safe filename
    if isinstance(conference, ConferenceEntry):
        conference = conference.id
    safe_conf = "".join(c for c in conference if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')
    return os.path.join(output_dir, f"{safe_conf}_{year}.json")

def load_existing_papers(output_path: str) -> Dict[str, Paper]:
    """Loads existing papers from the output file to support incremental updates."""
    existing_papers = {}
    if os.path.exists(output_path):
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data:
                    # Create Paper object from dict
                    p = Paper(
                        title=item.get("title"),
                        authors=item.get("authors", []),
                        year=item.get("year"),
                        venue=item.get("venue"),
                        dblp_key=item.get("dblp_key"),
                        url=item.get("url"),
                        abstract=item.get("abstract"),
                        citation_count=item.get("citation_count"),
                        reference_count=item.get("reference_count"),
                        paper_id=item.get("source_id"),
                        source=item.get("source"),
                        source_url=item.get("source_url"),
                    )
                    # Use title or DBLP key as unique identifier
                    key = paper_key(p)
                    existing_papers[key] = p
            # print(f"Loaded {len(existing_papers)} existing papers from {output_path}.")
        except json.JSONDecodeError:
            print(f"Could not decode {output_path}, starting fresh.")
    return existing_papers

def save_papers(papers_map: Dict[str, Paper], output_path: str):
    """Saves the current state of papers to the output file."""
    output_data = [
        {
            "title": p.title,
            "authors": p.authors,
            "venue": p.venue,
            "year": p.year,
            "abstract": p.abstract,
            "citation_count": p.citation_count,
            "reference_count": p.reference_count,
            "url": p.url,
            "dblp_key": p.dblp_key,
            "source_id": p.paper_id,
            "source": p.source,
            "source_url": p.source_url,
        }
        for p in papers_map.values()
    ]

    # Create directory if it doesn't exist
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Write to a temp file first then move to avoid corruption on interrupt
    temp_file = output_path + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    os.replace(temp_file, output_path)
    # print(f"Saved {len(output_data)} papers to {output_path}")


def paper_key(paper: Paper) -> str:
    return paper.dblp_key or paper.paper_id or paper.title


def fetch_papers_with_fallback(
    conference: ConferenceEntry,
    year: int,
    dblp_client: DBLPClient,
    official_source_client: OfficialSourceClient | None = None,
) -> list[Paper]:
    print(f"  Fetching from DBLP...")
    papers = dblp_client.fetch_papers(
        conference.display_name,
        year,
        dblp_stream=conference.dblp_stream,
        dblp_query=conference.dblp_query,
        venue_aliases=list(conference.aliases),
    )
    print(f"  Found {len(papers)} papers on DBLP.")

    if papers or not conference.official_source:
        return papers

    official_source_client = official_source_client or OfficialSourceClient()
    source_type = conference.official_source.get("type", "official")
    print(f"  DBLP has no TOC entries; trying official {source_type} fallback...")
    papers = official_source_client.fetch_papers(conference, year)
    print(f"  Found {len(papers)} papers from official fallback.")
    return papers


def process_conference_year(conf: str | ConferenceEntry, year: int, dblp_client: DBLPClient, metadata_manager: MetadataManager, output_dir: str, limit: int):
    """Processes a single conference year: fetches, loads existing, enriches, and saves."""
    conference = normalize_conference(conf)
    output_path = get_output_path(output_dir, conference, year)
    print(f"Processing {conference.display_name} {year} -> {output_path}")

    # 1. Load existing
    existing_papers_map = load_existing_papers(output_path)
    final_papers_map = existing_papers_map.copy()

    # 2. Fetch from DBLP, then from a whitelisted official source if configured.
    papers = fetch_papers_with_fallback(conference, year, dblp_client)

    if limit > 0:
        papers = papers[:limit]

    papers_to_process = []
    for paper in papers:
        key = paper_key(paper)

        if key in final_papers_map:
            existing = final_papers_map[key]
            # Check if we need to update/enrich
            if existing.abstract and existing.citation_count is not None:
                continue # Already done
            else:
                # Update basic info and re-queue for enrichment
                existing.venue = paper.venue
                existing.url = paper.url or existing.url
                existing.source = paper.source or existing.source
                existing.source_url = paper.source_url or existing.source_url
                papers_to_process.append(existing)
        else:
            # New paper
            final_papers_map[key] = paper
            papers_to_process.append(paper)

    if not papers_to_process:
        print(f"  No new papers to enrich for {conference.display_name} {year}.")
        # Ensure we save even if no new processing (in case we just fetched DBLP data for the first time but limit was 0 or something)
        # But actually if papers_to_process is empty, it means we either have no papers or all are already enriched.
        # We should still save to ensure the file exists if it was empty.
        if final_papers_map:
             save_papers(final_papers_map, output_path)
        return

    print(f"  Enriching {len(papers_to_process)} papers...")

    # 3. Enrich in chunks
    chunk_size = 5 # Smaller chunk size per conference to save more frequently
    for i in range(0, len(papers_to_process), chunk_size):
        chunk = papers_to_process[i : i + chunk_size]
        enriched_chunk = metadata_manager.enrich_papers(chunk)

        for p in enriched_chunk:
            key = paper_key(p)
            final_papers_map[key] = p

        save_papers(final_papers_map, output_path)
        print(f"  Saved progress for {conference.display_name} {year} ({min(i + chunk_size, len(papers_to_process))}/{len(papers_to_process)})")

    print(f"  Completed {conference.display_name} {year}.")


def main():
    parser = argparse.ArgumentParser(description="Fetch paper data from DBLP and enrich with metadata.")
    parser.add_argument("--config", default="config.yaml", help="Path to configuration file")

    args = parser.parse_args()

    config = load_config(args.config)
    if not config:
        return

    conferences = normalize_conferences(config)
    years = config.get("years", [])
    threads = config.get("concurrency", {}).get("threads", 4)
    limit_per_conf = config.get("limit_per_conference", 0)
    output_dir = config.get("output_dir", "data")

    print(f"Starting job with {threads} threads.")
    print(f"Output directory: {output_dir}")

    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    dblp_client = DBLPClient()
    metadata_manager = MetadataManager(threads=threads)

    # Process each conference/year sequentially to avoid too many open files/threads confusion,
    # but inside each conference processing we use threads for enrichment.
    # This is also better for rate limits as we focus on one set of papers at a time.

    for conf in conferences:
        for year in years:
            process_conference_year(conf, year, dblp_client, metadata_manager, output_dir, limit_per_conf)

    print("All jobs completed.")

if __name__ == "__main__":
    main()
