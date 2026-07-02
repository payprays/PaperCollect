import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from main import (
    fetch_papers_with_fallback,
    get_output_path,
    load_config,
    load_existing_papers,
    paper_key,
    process_conference_year,
    save_papers,
)
from src.clients.dblp_client import DBLPClient
from src.core.conference_catalog import ConferenceEntry, find_conference
from src.services.metadata_manager import MetadataManager


DEFAULT_LIMITED_TASKS: list[tuple[str, int]] = [
    ("neurips", 2023),
    ("neurips", 2024),
    ("neurips", 2025),
    ("icml", 2022),
    ("icml", 2023),
    ("icml", 2024),
    ("icml", 2025),
    ("iclr", 2022),
    ("iclr", 2023),
    ("iclr", 2024),
    ("iclr", 2025),
    ("aaai", 2022),
    ("aaai", 2023),
    ("aaai", 2024),
    ("aaai", 2025),
    ("aaai", 2026),
    ("acl", 2022),
    ("acl", 2023),
    ("acl", 2024),
    ("acl", 2025),
    ("emnlp", 2022),
    ("emnlp", 2023),
    ("emnlp", 2024),
    ("naacl", 2025),
    ("esorics", 2025),
    ("esorics", 2026),
    ("fm", 2025),
    ("asplos", 2023),
    ("asplos", 2024),
    ("asplos", 2025),
    ("asplos", 2026),
    ("pldi", 2025),
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill conference/year files that were previously collected with a local paper limit."
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument(
        "--task",
        action="append",
        default=[],
        help="Specific task as conference:year. Can be repeated. Defaults to the built-in limited-paper list.",
    )
    parser.add_argument(
        "--metadata",
        choices=["none", "full"],
        default="none",
        help="Use 'none' for fast count backfill; use 'full' to enrich new papers through metadata providers.",
    )
    parser.add_argument("--sleep-between", type=float, default=15.0, help="Seconds to sleep between DBLP tasks.")
    parser.add_argument(
        "--search-page-delay",
        type=float,
        default=5.0,
        help="Seconds to sleep between paginated DBLP search requests.",
    )
    parser.add_argument("--status-file", default="", help="JSON status output. Defaults to <output_dir>/backfill_limited_status.json")
    parser.add_argument("--retry-completed", action="store_true", help="Do not skip tasks already marked completed in the status file.")
    args = parser.parse_args()

    config = load_config(args.config)
    if not config:
        raise SystemExit(f"Could not load config: {args.config}")

    output_dir = str(config.get("output_dir", "data"))
    os.makedirs(output_dir, exist_ok=True)
    status_file = args.status_file or os.path.join(output_dir, "backfill_limited_status.json")
    tasks = parse_tasks(args.task) if args.task else DEFAULT_LIMITED_TASKS
    status: list[dict[str, Any]] = read_status(status_file)
    completed = {
        (str(item.get("conference")), int(item.get("year")))
        for item in status
        if item.get("status") == "completed" and item.get("year") is not None
    }

    dblp_client = DBLPClient(search_page_delay=args.search_page_delay)
    metadata_manager = MetadataManager(threads=int(config.get("concurrency", {}).get("threads", 4)))

    for index, (conference_id, year) in enumerate(tasks, start=1):
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

        if not args.retry_completed and (entry.id, year) in completed:
            print(f"[{index}/{len(tasks)}] Skipping {entry.display_name} {year}; already completed in {status_file}", flush=True)
            continue

        print(f"[{index}/{len(tasks)}] Backfilling {entry.display_name} {year} with limit=0", flush=True)
        started_at = time.time()
        try:
            if args.metadata == "full":
                before, after = backfill_with_full_metadata(entry, year, dblp_client, metadata_manager, output_dir)
                source_count = None
            else:
                before, source_count, after = backfill_without_metadata(entry, year, dblp_client, output_dir)

            result = {
                "conference": entry.id,
                "display_name": entry.display_name,
                "year": year,
                "status": "completed",
                "before_count": before,
                "source_count": source_count,
                "after_count": after,
                "added_count": max(after - before, 0),
                "metadata": args.metadata,
                "elapsed_seconds": round(time.time() - started_at, 2),
            }
            print(
                f"  completed: before={before}, source={source_count if source_count is not None else 'n/a'}, after={after}",
                flush=True,
            )
        except Exception as exc:
            result = {
                "conference": entry.id,
                "display_name": entry.display_name,
                "year": year,
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "metadata": args.metadata,
                "elapsed_seconds": round(time.time() - started_at, 2),
            }
            print(f"  failed: {result['error']}", flush=True)

        status.append(result)
        write_status(status_file, status)

        if index < len(tasks) and args.sleep_between > 0:
            time.sleep(args.sleep_between)

    print(f"Backfill status written to {status_file}")


def parse_tasks(values: list[str]) -> list[tuple[str, int]]:
    tasks: list[tuple[str, int]] = []
    for value in values:
        conference, sep, raw_year = value.partition(":")
        if not sep or not conference.strip() or not raw_year.strip():
            raise SystemExit(f"Invalid task {value!r}; expected conference:year")
        try:
            year = int(raw_year)
        except ValueError as exc:
            raise SystemExit(f"Invalid year in task {value!r}") from exc
        tasks.append((conference.strip(), year))
    return tasks


def backfill_with_full_metadata(
    conference: ConferenceEntry,
    year: int,
    dblp_client: DBLPClient,
    metadata_manager: MetadataManager,
    output_dir: str,
) -> tuple[int, int]:
    output_path = get_output_path(output_dir, conference, year)
    before = len(load_existing_papers(output_path))
    process_conference_year(conference, year, dblp_client, metadata_manager, output_dir, limit=0)
    after = len(load_existing_papers(output_path))
    return before, after


def backfill_without_metadata(
    conference: ConferenceEntry,
    year: int,
    dblp_client: DBLPClient,
    output_dir: str,
) -> tuple[int, int, int]:
    output_path = get_output_path(output_dir, conference, year)
    existing_papers = load_existing_papers(output_path)
    merged = existing_papers.copy()

    papers = fetch_papers_with_fallback(conference, year, dblp_client)
    for paper in papers:
        key = paper_key(paper)
        if key in merged:
            existing = merged[key]
            existing.venue = paper.venue or existing.venue
            existing.url = paper.url or existing.url
            existing.dblp_key = paper.dblp_key or existing.dblp_key
            existing.source = paper.source or existing.source
            existing.source_url = paper.source_url or existing.source_url
        else:
            merged[key] = paper

    save_papers(merged, output_path)
    return len(existing_papers), len(papers), len(merged)


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
