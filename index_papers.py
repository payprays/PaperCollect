import argparse
import json
from typing import Any

import yaml

from src.services.vector_index import build_vector_index, vector_index_status


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build or inspect the PaperCollect agentic Qdrant hybrid vector index.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--output-dir", default=None, help="Directory containing saved paper JSON files")
    parser.add_argument("--no-force", action="store_true", help="Do not recreate the collection before indexing")
    parser.add_argument("--status", action="store_true", help="Only print vector index status")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()

    config = _load_config(args.config)
    output_dir = args.output_dir or str(config.get("output_dir", "data"))

    result = (
        vector_index_status(config)
        if args.status
        else build_vector_index(config, output_dir, force=not args.no_force)
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    _print_result(result)


def _load_config(config_path: str) -> dict[str, Any]:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _print_result(result: dict[str, Any]) -> None:
    if "indexed" in result:
        state = "indexed" if result["indexed"] else "not indexed"
        print(f"Vector index {state}: {result['collection']} ({result['paper_count']} papers)")
        return

    print(
        "Indexed "
        f"{result['paper_count']} papers into {result['backend']} collection "
        f"{result['collection']} using {result['provider']}."
    )


if __name__ == "__main__":
    main()
