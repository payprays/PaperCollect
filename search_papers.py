import argparse
import json
from typing import Any

import yaml

from src.services.paper_search import search_saved_papers


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search saved PaperCollect JSON files with agentic hybrid retrieval.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("query", type=str, help="The search query.")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--output-dir", default=None, help="Directory containing saved paper JSON files")
    parser.add_argument("--top_k", "--limit", dest="limit", type=int, default=20, help="Number of papers to return")
    parser.add_argument(
        "--mode",
        choices=["agentic", "vector", "concept", "keyword", "search", "ask"],
        default="agentic",
        help="'agentic' uses the Qdrant hybrid vector index with concept fallback; 'search' and 'ask' are kept as concept aliases",
    )
    parser.add_argument("--year", type=int, help="Filter by year, e.g. 2026")
    parser.add_argument(
        "--conference",
        "--venue",
        dest="conferences",
        action="append",
        help="Filter by conference id, display name, or alias; can be repeated",
    )
    parser.add_argument("--ccf", "--tier", dest="ccf", help="Filter by CCF tier, e.g. A, B, C, or N")
    parser.add_argument("--category", help="Filter by CCFDDL category, e.g. SC, SE, DS")
    parser.add_argument("--focus", help="Filter by focus tag, e.g. cloud_native or cloud_security")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument("--abstract-chars", type=int, default=260, help="Characters of abstract preview to print")
    args = parser.parse_args()

    config = _load_config(args.config)
    output_dir = args.output_dir or str(config.get("output_dir", "data"))
    mode = _normalize_mode(args.mode)

    results = search_saved_papers(
        config,
        output_dir,
        args.query,
        category=args.category,
        focus=args.focus,
        conferences=args.conferences,
        ccf=args.ccf,
        year=args.year,
        limit=args.limit,
        mode=mode,
    )

    if args.json:
        print(json.dumps({"mode": mode, "results": results}, ensure_ascii=False, indent=2))
        return

    _print_results(args.query, mode, results, abstract_chars=args.abstract_chars)


def _load_config(config_path: str) -> dict[str, Any]:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _normalize_mode(value: str) -> str:
    if value == "vector":
        return "agentic"
    if value in {"agentic", "keyword"}:
        return value
    if value in {"search", "ask"}:
        return "concept"
    return value


def _print_results(query: str, mode: str, results: list[dict[str, Any]], abstract_chars: int) -> None:
    print(f"\nTop {len(results)} {mode} results for '{query}':\n")
    if not results:
        print("No saved papers match the query.")
        return

    for index, paper in enumerate(results, start=1):
        title = paper.get("title") or "Untitled paper"
        venue = paper.get("display_name") or paper.get("venue") or paper.get("conference") or "Unknown venue"
        year = paper.get("year") or "unknown year"
        score = float(paper.get("score") or 0.0)
        print(f"{index}. [{score:.4f}] {title} ({venue} {year})")

        meta = [
            paper.get("conference"),
            paper.get("category"),
            ", ".join(paper.get("focus_tags") or []),
        ]
        meta_text = " · ".join(str(item) for item in meta if item)
        if meta_text:
            print(f"   {meta_text}")

        concepts = paper.get("matched_concepts") or []
        if concepts:
            print(f"   concepts: {', '.join(concepts)}")

        if paper.get("url"):
            print(f"   url: {paper['url']}")

        abstract = (paper.get("abstract") or "").strip()
        if abstract and abstract_chars > 0:
            print(f"   abstract: {_truncate(abstract, abstract_chars)}")
        print()


def _truncate(value: str, length: int) -> str:
    if len(value) <= length:
        return value
    return f"{value[: max(0, length - 1)]}…"


if __name__ == "__main__":
    main()
