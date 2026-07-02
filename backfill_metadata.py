import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backfill_limited_papers import DEFAULT_LIMITED_TASKS, parse_tasks
from main import get_output_path, load_config
from src.clients.openalex_client import OpenAlexClient
from src.core.conference_catalog import find_conference
from src.core.models import Paper
from src.services.metadata_manager import MetadataManager


@dataclass
class MetadataBackfillResult:
    total_count: int
    missing_before: int
    attempted_count: int
    completed_count: int
    remaining_missing: int


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill missing abstract/citation metadata in saved paper JSON files.")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument(
        "--task",
        action="append",
        default=[],
        help="Specific task as conference:year. Can be repeated. Defaults to the built-in limited-paper list.",
    )
    parser.add_argument(
        "--max-papers",
        type=int,
        default=500,
        help="Maximum incomplete papers to attempt in this run. Use 0 for no limit.",
    )
    parser.add_argument("--chunk-size", type=int, default=10, help="Save progress after this many enrichment attempts.")
    parser.add_argument("--threads", type=int, default=0, help="Metadata enrichment worker count. Defaults to config concurrency.")
    parser.add_argument(
        "--source-set",
        choices=["openalex", "all"],
        default="openalex",
        help="Metadata sources to use. 'openalex' is faster and gentler; 'all' tries every configured provider.",
    )
    parser.add_argument("--status-file", default="", help="JSON status output. Defaults to <output_dir>/backfill_metadata_status.json")
    args = parser.parse_args()

    if args.max_papers < 0:
        raise SystemExit("--max-papers must be >= 0")
    if args.chunk_size <= 0:
        raise SystemExit("--chunk-size must be > 0")

    config = load_config(args.config)
    if not config:
        raise SystemExit(f"Could not load config: {args.config}")

    output_dir = str(config.get("output_dir", "data"))
    status_file = args.status_file or os.path.join(output_dir, "backfill_metadata_status.json")
    tasks = parse_tasks(args.task) if args.task else DEFAULT_LIMITED_TASKS
    threads = args.threads or int(config.get("concurrency", {}).get("threads", 4))
    manager = build_metadata_manager(threads, args.source_set)
    remaining_budget = None if args.max_papers == 0 else args.max_papers
    status: list[dict[str, Any]] = read_status(status_file)

    for index, (conference_id, year) in enumerate(tasks, start=1):
        if remaining_budget == 0:
            break

        entry = find_conference(config, conference_id)
        if entry is None:
            result = {
                "conference": conference_id,
                "year": year,
                "status": "failed",
                "error": "conference not found",
            }
            status.append(result)
            write_status(status_file, status)
            print(f"[{index}/{len(tasks)}] {conference_id} {year}: conference not found", flush=True)
            continue

        output_path = get_output_path(output_dir, entry, year)
        if not os.path.exists(output_path):
            result = {
                "conference": entry.id,
                "display_name": entry.display_name,
                "year": year,
                "status": "skipped",
                "error": "saved paper file not found",
            }
            status.append(result)
            write_status(status_file, status)
            print(f"[{index}/{len(tasks)}] {entry.display_name} {year}: saved file not found", flush=True)
            continue

        print(f"[{index}/{len(tasks)}] Backfilling metadata for {entry.display_name} {year}", flush=True)
        result = enrich_metadata_file(
            Path(output_path),
            manager,
            max_papers=remaining_budget,
            chunk_size=args.chunk_size,
        )
        if remaining_budget is not None:
            remaining_budget -= result.attempted_count

        status_item = {
            "conference": entry.id,
            "display_name": entry.display_name,
            "year": year,
            "status": "completed",
            "source_set": args.source_set,
            "total_count": result.total_count,
            "missing_before": result.missing_before,
            "attempted_count": result.attempted_count,
            "completed_count": result.completed_count,
            "remaining_missing": result.remaining_missing,
        }
        status.append(status_item)
        write_status(status_file, status)
        print(
            "  completed: "
            f"attempted={result.attempted_count}, "
            f"completed={result.completed_count}, "
            f"remaining_missing={result.remaining_missing}",
            flush=True,
        )

    write_status(status_file, status)
    print(f"Metadata backfill status written to {status_file}")


def build_metadata_manager(threads: int, source_set: str) -> MetadataManager:
    manager = MetadataManager(threads=threads)
    if source_set == "openalex":
        manager.sources = [OpenAlexClient()]
    return manager


def enrich_metadata_file(
    path: Path,
    manager: MetadataManager,
    max_papers: int | None,
    chunk_size: int,
) -> MetadataBackfillResult:
    data = read_paper_items(path)
    missing_indexes = [index for index, item in enumerate(data) if needs_metadata(item)]
    selected_indexes = missing_indexes if max_papers is None else missing_indexes[:max_papers]
    completed_count = 0

    for start in range(0, len(selected_indexes), chunk_size):
        indexes = selected_indexes[start : start + chunk_size]
        papers = [paper_from_item(data[index]) for index in indexes]
        enriched = manager.enrich_papers(papers)

        for index, paper in zip(indexes, enriched):
            was_complete = not needs_metadata(data[index])
            update_item_from_paper(data[index], paper)
            if not was_complete and not needs_metadata(data[index]):
                completed_count += 1

        write_paper_items(path, data)
        print(
            f"  saved metadata progress {min(start + chunk_size, len(selected_indexes))}/{len(selected_indexes)}",
            flush=True,
        )

    return MetadataBackfillResult(
        total_count=len(data),
        missing_before=len(missing_indexes),
        attempted_count=len(selected_indexes),
        completed_count=completed_count,
        remaining_missing=sum(1 for item in data if needs_metadata(item)),
    )


def needs_metadata(item: dict[str, Any]) -> bool:
    return not (item.get("abstract") and item.get("citation_count") is not None)


def paper_from_item(item: dict[str, Any]) -> Paper:
    authors = item.get("authors") or []
    if not isinstance(authors, list):
        authors = [str(authors)]
    return Paper(
        title=str(item.get("title") or ""),
        authors=[str(author) for author in authors],
        year=int(item.get("year") or 0),
        venue=str(item.get("venue") or ""),
        dblp_key=item.get("dblp_key"),
        url=item.get("url"),
        abstract=item.get("abstract"),
        citation_count=item.get("citation_count"),
        reference_count=item.get("reference_count"),
        paper_id=item.get("source_id"),
        source=item.get("source"),
        source_url=item.get("source_url"),
    )


def update_item_from_paper(item: dict[str, Any], paper: Paper) -> None:
    item["title"] = paper.title
    item["authors"] = paper.authors
    item["venue"] = paper.venue
    item["year"] = paper.year
    item["abstract"] = paper.abstract
    item["citation_count"] = paper.citation_count
    item["reference_count"] = paper.reference_count
    item["url"] = paper.url
    item["dblp_key"] = paper.dblp_key
    item["source_id"] = paper.paper_id
    item["source"] = paper.source
    item["source_url"] = paper.source_url


def read_paper_items(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def write_paper_items(path: Path, data: list[dict[str, Any]]) -> None:
    temp = path.with_suffix(f"{path.suffix}.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def write_status(path: str, status: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(f"{target.suffix}.tmp")
    temp.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(target)


def read_status(path: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


if __name__ == "__main__":
    main()
