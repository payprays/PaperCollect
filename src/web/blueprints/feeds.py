import time
from urllib.parse import quote

from flask import Blueprint, Response, current_app, jsonify, request

from src.core.conference_catalog import (
    configured_years,
    find_conference,
    normalize_conferences,
)
from src.services.rss_service import build_rss_xml, count_papers, load_papers
from src.web.utils import (
    cache_ttl,
    feeds_cache,
    load_config,
    saved_years_for_conference,
    with_url_base,
)

feeds_bp = Blueprint("feeds", __name__)


def _config_path() -> str:
    return current_app.config["PAPERCOLLECT_CONFIG"]


def _url_base() -> str:
    return current_app.config["PAPERCOLLECT_URL_BASE"]


def _feed_url(conference, year: int) -> str:
    encoded = quote(conference.id, safe="")
    return with_url_base(f"/feed/{encoded}/{year}.xml", _url_base())


@feeds_bp.route("/api/feeds", methods=["GET"])
def feeds() -> Response:
    config = load_config(_config_path())
    output_dir = str(config.get("output_dir", "data"))
    _cache = feeds_cache()
    _ttl = cache_ttl()
    cache_key = output_dir
    now = time.time()
    cached = _cache.get(cache_key)
    if cached and now - cached[0] < _ttl:
        return jsonify(cached[1])
    feeds = []
    for conference in normalize_conferences(config):
        years = sorted(
            {
                int(year)
                for year in configured_years(config, conference)
            }
            | saved_years_for_conference(output_dir, conference)
        )
        for year in years:
            paper_count = count_papers(
                output_dir,
                conference.id,
                int(year),
                aliases=[conference.display_name, *conference.aliases],
            )
            if paper_count == 0:
                continue
            feeds.append(
                {
                    "conference": conference.id,
                    "display_name": conference.display_name,
                    "year": int(year),
                    "paper_count": paper_count,
                    "feed_url": _feed_url(conference, int(year)),
                }
            )
    result = {"feeds": feeds}
    _cache[cache_key] = (time.time(), result)
    return jsonify(result)


@feeds_bp.route("/feed/<path:conference>/<int:year>.xml", methods=["GET"])
def feed(conference: str, year: int) -> tuple[Response, int] | Response:
    config = load_config(_config_path())
    output_dir = str(config.get("output_dir", "data"))
    entry = find_conference(config, conference)
    if entry is None:
        return Response("Unknown conference.\n", status=404)

    papers = load_papers(
        output_dir,
        entry.id,
        year,
        aliases=[entry.display_name, *entry.aliases],
    )
    if not papers:
        return Response("No saved papers for this conference/year.\n", status=404)

    xml = build_rss_xml(
        papers,
        entry.display_name,
        year,
        request.url,
    )
    return Response(xml, mimetype="application/rss+xml; charset=utf-8")
