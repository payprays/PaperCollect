import time

from flask import Blueprint, Response, current_app, jsonify, request

from src.core.conference_catalog import (
    catalog_categories,
    configured_years,
    focus_tag_options,
    normalize_conferences,
    valid_collection_year,
)
from src.web.utils import (
    cache_ttl,
    feeds_cache,
    load_config,
    saved_years_for_conference,
)

config_bp = Blueprint("config", __name__)


def _config_path() -> str:
    return current_app.config["PAPERCOLLECT_CONFIG"]


@config_bp.route("/api/options", methods=["GET"])
def options() -> Response:
    config = load_config(_config_path())
    years = configured_years(config)
    return jsonify(
        {
            "conferences": [
                conference.option(years)
                for conference in normalize_conferences(config)
            ],
            "categories": catalog_categories(config),
            "focus_tags": focus_tag_options(config),
            "years": years,
            "limit_per_conference": config.get("limit_per_conference", 0),
        }
    )


@config_bp.route("/api/year-progress", methods=["GET"])
def year_progress() -> Response:
    config = load_config(_config_path())
    output_dir = str(config.get("output_dir", "data"))

    # Support custom years via ?years=2020,2021,2023
    custom_years_param = request.args.get("years")
    if custom_years_param:
        try:
            custom_years = sorted(set(int(y.strip()) for y in custom_years_param.split(",") if y.strip()))
        except (ValueError, TypeError):
            custom_years = []
    else:
        custom_years = []

    _cache = feeds_cache()
    _ttl = cache_ttl()
    cache_key = f"yp:{output_dir}" + (f":{','.join(str(y) for y in custom_years)}" if custom_years else "")
    now = time.time()
    cached = _cache.get(cache_key)
    if cached and now - cached[0] < _ttl:
        return jsonify(cached[1])
    default_years = [int(y) for y in config.get("years", [])]
    progress = []
    for conference in normalize_conferences(config):
        conf_years = list(conference.years) if conference.years else default_years
        if custom_years:
            conf_years = sorted(set(int(y) for y in conf_years) | set(custom_years))
        saved = saved_years_for_conference(output_dir, conference)
        conf_years_int = [int(y) for y in conf_years]
        saved_int = sorted(saved)
        missing = sorted(set(conf_years_int) - saved)
        progress.append(
            {
                "conference_id": conference.id,
                "display_name": conference.display_name,
                "category": conference.category,
                "ccf": (conference.tier.get("ccf") or "").strip().upper() or None,
                "configured_years": conf_years_int,
                "saved_years": saved_int,
                "missing_years": missing,
            }
        )
    result = {"progress": progress}
    _cache[cache_key] = (time.time(), result)
    return jsonify(result)
