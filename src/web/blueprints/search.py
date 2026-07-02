from flask import Blueprint, Response, current_app, jsonify, request

from src.core.conference_catalog import (
    catalog_categories,
    find_conference,
    focus_tag_options,
    valid_collection_year,
)
from src.services.paper_search import search_saved_papers
from src.services.vector_index import VectorIndexError, vector_index_status
from src.web.utils import (
    known_ccf_tiers,
    load_config,
    normalize_optional_text,
    optional_int,
    request_list_args,
)

search_bp = Blueprint("search", __name__)


def _config_path() -> str:
    return current_app.config["PAPERCOLLECT_CONFIG"]


@search_bp.route("/api/search", methods=["GET"])
def search() -> tuple[Response, int] | Response:
    config = load_config(_config_path())
    output_dir = str(config.get("output_dir", "data"))
    query = request.args.get("q", "").strip()
    category = request.args.get("category") or None
    focus = request.args.get("focus") or None
    conferences = request_list_args("conference", "conferences")
    ccf = normalize_optional_text(request.args.get("ccf") or request.args.get("tier"))
    year = optional_int(request.args.get("year"))
    limit = optional_int(request.args.get("limit")) or 25
    offset = optional_int(request.args.get("offset")) or 0
    mode = request.args.get("mode") or "agentic"
    if mode == "vector":
        mode = "agentic"

    for conference in conferences:
        if find_conference(config, conference) is None:
            return jsonify({"error": "Choose conferences from config.yaml."}), 400
    if ccf and ccf not in known_ccf_tiers(config):
        return jsonify({"error": "Choose a known CCF tier."}), 400
    if category and category not in {item["id"] for item in catalog_categories(config)}:
        return jsonify({"error": "Choose a known category."}), 400
    if focus and focus not in {item["id"] for item in focus_tag_options(config)}:
        return jsonify({"error": "Choose a known focus area."}), 400
    if limit < 1 or limit > 100:
        return jsonify({"error": "Limit must be between 1 and 100."}), 400
    if year is not None and not valid_collection_year(year):
        return jsonify({"error": "Choose a valid year."}), 400
    if mode not in {"keyword", "concept", "agentic"}:
        return jsonify({"error": "Search mode must be keyword, concept, or agentic."}), 400

    results = search_saved_papers(
        config,
        output_dir,
        query,
        category=category,
        focus=focus,
        conferences=conferences,
        ccf=ccf,
        year=year,
        limit=limit,
        mode=mode,
        offset=offset,
    )
    payload = {"results": results, "mode": mode, "conferences": conferences, "ccf": ccf}
    if mode == "agentic":
        try:
            payload["index_status"] = vector_index_status(config)
        except (VectorIndexError, OSError, RuntimeError, ValueError) as exc:
            payload["index_status"] = {"indexed": False, "error": str(exc)}
    return jsonify(payload)
