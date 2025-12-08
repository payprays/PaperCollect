import argparse
import json
import yaml
import os
import threading
from typing import List, Dict
from src.clients.dblp_client import DBLPClient
from src.services.metadata_manager import MetadataManager
from src.core.models import Paper

def load_config(config_path: str):
    if not os.path.exists(config_path):
        print(f"Config file {config_path} not found.")
        return None
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

def get_output_path(output_dir: str, conference: str, year: int) -> str:
    """Returns the file path for a specific conference and year."""
    # Ensure safe filename
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
                        paper_id=item.get("source_id")
                    )
                    # Use title or DBLP key as unique identifier
                    key = p.dblp_key if p.dblp_key else p.title
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
            "source_id": p.paper_id
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


def process_conference_year(conf: str, year: int, dblp_client: DBLPClient, metadata_manager: MetadataManager, output_dir: str, limit: int):
    """Processes a single conference year: fetches, loads existing, enriches, and saves."""
    output_path = get_output_path(output_dir, conf, year)
    print(f"Processing {conf} {year} -> {output_path}")

    # 1. Load existing
    existing_papers_map = load_existing_papers(output_path)
    final_papers_map = existing_papers_map.copy()

    # 2. Fetch from DBLP
    print(f"  Fetching from DBLP...")
    papers = dblp_client.fetch_papers(conf, year)
    print(f"  Found {len(papers)} papers on DBLP.")

    if limit > 0:
        papers = papers[:limit]

    papers_to_process = []
    for paper in papers:
        key = paper.dblp_key if paper.dblp_key else paper.title

        if key in final_papers_map:
            existing = final_papers_map[key]
            # Check if we need to update/enrich
            if existing.abstract and existing.citation_count is not None:
                continue # Already done
            else:
                # Update basic info and re-queue for enrichment
                existing.venue = paper.venue
                existing.url = paper.url or existing.url
                papers_to_process.append(existing)
        else:
            # New paper
            final_papers_map[key] = paper
            papers_to_process.append(paper)

    if not papers_to_process:
        print(f"  No new papers to enrich for {conf} {year}.")
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
            key = p.dblp_key if p.dblp_key else p.title
            final_papers_map[key] = p

        save_papers(final_papers_map, output_path)
        print(f"  Saved progress for {conf} {year} ({min(i + chunk_size, len(papers_to_process))}/{len(papers_to_process)})")

    print(f"  Completed {conf} {year}.")


def main():
    parser = argparse.ArgumentParser(description="Fetch paper data from DBLP and enrich with metadata.")
    parser.add_argument("--config", default="config.yaml", help="Path to configuration file")

    args = parser.parse_args()

    config = load_config(args.config)
    if not config:
        return

    conferences = config.get("conferences", [])
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
