import os
import threading
from contextlib import redirect_stdout
from typing import Any, Callable
from urllib.parse import quote

import yaml
from flask import Flask, Response, jsonify, render_template, request, url_for

from main import get_output_path, process_conference_year
from src.clients.dblp_client import DBLPClient
from src.core.conference_catalog import (
    ConferenceEntry,
    catalog_categories,
    configured_years,
    find_conference,
    focus_tag_options,
    normalize_conferences,
    valid_collection_year,
)
from src.services.metadata_manager import MetadataManager
from src.services.job_store import FileJobLock, JobStore
from src.services.paper_search import search_saved_papers
from src.services.rss_service import build_rss_xml, load_papers
from src.services.vector_index import VectorIndexError, build_vector_index, vector_index_status

MAX_JOB_LOG_LINES = 500


class _JobLogWriter:
    def __init__(self, append_line: Callable[[str], None]) -> None:
        self._append_line = append_line
        self._buffer = ""

    def write(self, value: str) -> int:
        if not value:
            return 0

        self._buffer += value
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self._append_line(line.rstrip())
        return len(value)

    def flush(self) -> None:
        if self._buffer.strip():
            self._append_line(self._buffer.rstrip())
        self._buffer = ""


def create_app(config_path: str = "config.yaml") -> Flask:
    app = Flask(__name__)
    app.config["PAPERCOLLECT_CONFIG"] = config_path
    initial_config = _load_config(config_path)
    url_base = _normalize_url_base(
        initial_config.get("url_base") or initial_config.get("base_path")
    )
    app.config["PAPERCOLLECT_URL_BASE"] = url_base

    job_store = JobStore(_job_store_dir(initial_config))
    collection_lock = FileJobLock(os.path.join(job_store.path, "collection.lock"), "collection")
    index_lock = FileJobLock(os.path.join(job_store.path, "index.lock"), "index")

    def route(rule: str, **options: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            app.route(rule, **options)(func)
            if url_base:
                app.route(_prefix_rule(url_base, rule), **options)(func)
                if rule == "/":
                    app.route(url_base, **options)(func)
            return func

        return decorator

    @app.context_processor
    def template_globals() -> dict[str, Any]:
        return {
            "url_base": url_base,
            "asset_url": lambda filename: _with_url_base(
                url_for("static", filename=filename),
                url_base,
            ),
        }

    if url_base:
        @app.get(f"{url_base}/static/<path:filename>")
        def prefixed_static(filename: str) -> Response:
            return app.send_static_file(filename)

    @route("/", methods=["GET"])
    def index() -> str:
        return render_template("index.html")

    @route("/api/options", methods=["GET"])
    def options() -> Response:
        config = _load_config(config_path)
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

    @route("/api/collect", methods=["POST"])
    def collect() -> tuple[Response, int] | Response:
        payload = request.get_json(silent=True) or {}
        config = _load_config(config_path)
        conferences, validation_error = _resolve_collection_conferences(payload, config)
        if validation_error:
            return jsonify({"error": validation_error}), 400

        try:
            year = int(payload["year"])
        except (KeyError, TypeError, ValueError):
            return jsonify({"error": "Choose a valid year from config.yaml."}), 400
        if not valid_collection_year(year):
            return jsonify({"error": "Choose a year between 1900 and two years from now."}), 400

        try:
            limit = _resolve_limit(payload.get("limit"), config)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        if not collection_lock.acquire(blocking=False):
            return jsonify({"error": "A collection job is already running."}), 409

        output_dir = str(config.get("output_dir", "data"))
        threads = int(config.get("concurrency", {}).get("threads", 4))

        feed_urls = [_feed_url(conference, year) for conference in conferences]
        single_conference = len(conferences) == 1
        job = job_store.create(
            {
                "type": "collection",
                "status": "queued",
                "conference": conferences[0].id,
                "display_name": conferences[0].display_name
                if single_conference
                else f"{len(conferences)} conferences",
                "conferences": [conference.id for conference in conferences],
                "display_names": [conference.display_name for conference in conferences],
                "conference_count": len(conferences),
                "completed_count": 0,
                "failed_count": 0,
                "results": [],
                "errors": [],
                "year": year,
                "limit": limit,
                "logs": _queued_collection_logs(conferences, year, feed_urls),
                "paper_count": None,
                "feed_url": feed_urls[0] if single_conference else None,
                "feed_urls": feed_urls,
            }
        )

        thread = threading.Thread(
            target=_run_collection_job,
            args=(job["id"], conferences, output_dir, threads, collection_lock),
            daemon=True,
        )
        thread.start()

        return jsonify(
            {
                "job_id": job["id"],
                "status_url": _with_url_base(
                    url_for("job_status", job_id=job["id"]),
                    url_base,
                ),
            }
        ), 202

    @route("/api/jobs/<job_id>", methods=["GET"])
    def job_status(job_id: str) -> tuple[Response, int] | Response:
        job = job_store.get(job_id)
        if not job:
            return jsonify({"error": "Job not found."}), 404
        return jsonify(job)

    @route("/api/feeds", methods=["GET"])
    def feeds() -> Response:
        config = _load_config(config_path)
        output_dir = str(config.get("output_dir", "data"))
        feeds = []
        for conference in normalize_conferences(config):
            years = sorted(
                {
                    int(year)
                    for year in configured_years(config, conference)
                }
                | _saved_years_for_conference(output_dir, conference)
            )
            for year in years:
                output_path = _find_saved_output(output_dir, conference, int(year))
                if output_path:
                    papers = load_papers(
                        output_dir,
                        conference.id,
                        int(year),
                        aliases=[conference.display_name, *conference.aliases],
                    )
                    if not papers:
                        continue
                    feeds.append(
                        {
                            "conference": conference.id,
                            "display_name": conference.display_name,
                            "year": int(year),
                            "paper_count": len(papers),
                            "feed_url": _feed_url(conference, int(year)),
                        }
                    )
        return jsonify({"feeds": feeds})

    @route("/api/search", methods=["GET"])
    def search() -> tuple[Response, int] | Response:
        config = _load_config(config_path)
        output_dir = str(config.get("output_dir", "data"))
        query = request.args.get("q", "").strip()
        category = request.args.get("category") or None
        focus = request.args.get("focus") or None
        conferences = _request_list_args("conference", "conferences")
        ccf = _normalize_optional_text(request.args.get("ccf") or request.args.get("tier"))
        year = _optional_int(request.args.get("year"))
        limit = _optional_int(request.args.get("limit")) or 25
        mode = request.args.get("mode") or "agentic"
        if mode == "vector":
            mode = "agentic"

        for conference in conferences:
            if find_conference(config, conference) is None:
                return jsonify({"error": "Choose conferences from config.yaml."}), 400
        if ccf and ccf not in _known_ccf_tiers(config):
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
        )
        payload = {"results": results, "mode": mode, "conferences": conferences, "ccf": ccf}
        if mode == "agentic":
            try:
                payload["index_status"] = vector_index_status(config)
            except (VectorIndexError, OSError, RuntimeError, ValueError) as exc:
                payload["index_status"] = {"indexed": False, "error": str(exc)}
        return jsonify(payload)

    @route("/api/index/status", methods=["GET"])
    def index_status() -> tuple[Response, int] | Response:
        config = _load_config(config_path)
        try:
            return jsonify(vector_index_status(config))
        except (VectorIndexError, OSError, RuntimeError, ValueError) as exc:
            return jsonify({"error": str(exc), "indexed": False}), 503

    @route("/api/index", methods=["POST"])
    def index_build() -> tuple[Response, int] | Response:
        payload = request.get_json(silent=True) or {}
        config = _load_config(config_path)
        try:
            force = _optional_bool(payload.get("force"), default=True)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        if not index_lock.acquire(blocking=False):
            return jsonify({"error": "A vector index job is already running."}), 409

        output_dir = str(config.get("output_dir", "data"))
        index_config = dict(config.get("vector_index") or {})
        collection = str(index_config.get("collection") or "papercollect_papers")
        job = job_store.create(
            {
                "type": "index",
                "status": "queued",
                "force": force,
                "output_dir": output_dir,
                "collection": collection,
                "logs": [
                    f"Queued vector index rebuild for {collection}.",
                    f"Source JSON directory: {output_dir}.",
                ],
                "paper_count": None,
                "source_count": None,
            }
        )
        thread = threading.Thread(
            target=_run_index_job,
            args=(job["id"], config, output_dir, force, index_lock),
            daemon=True,
        )
        thread.start()
        return jsonify(
            {
                "job_id": job["id"],
                "status_url": _with_url_base(
                    url_for("job_status", job_id=job["id"]),
                    url_base,
                ),
            }
        ), 202

    @route("/feed/<path:conference>/<int:year>.xml", methods=["GET"])
    def feed(conference: str, year: int) -> tuple[Response, int] | Response:
        config = _load_config(config_path)
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

    def _run_collection_job(
        job_id: str,
        conferences: list[ConferenceEntry],
        output_dir: str,
        threads: int,
        active_lock: FileJobLock,
    ) -> None:
        job = job_store.get(job_id) or {}
        year = int(job["year"])
        limit = int(job["limit"])
        _update_job(job_id, status="running")
        total = len(conferences)
        results: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        try:
            os.makedirs(output_dir, exist_ok=True)

            for index, conference in enumerate(conferences, start=1):
                progress = f" ({index}/{total})" if total > 1 else ""
                _append_job_log(job_id, f"Started collection for {conference.display_name} {year}{progress}.")
                _append_job_log(
                    job_id,
                    "Using "
                    f"DBLP stream {conference.dblp_stream or conference.display_name}; "
                    f"limit={limit}; metadata_threads={threads}.",
                )
                _append_job_log(job_id, "Fetching DBLP entries and metadata. This can take a while.")
                log_writer = _JobLogWriter(lambda line: _append_job_log(job_id, line))
                try:
                    with redirect_stdout(log_writer):
                        process_conference_year(
                            conference,
                            year,
                            DBLPClient(),
                            MetadataManager(threads=threads),
                            output_dir,
                            limit,
                        )
                    log_writer.flush()

                    papers = load_papers(
                        output_dir,
                        conference.id,
                        year,
                        aliases=[conference.display_name, *conference.aliases],
                    )
                    output_path = get_output_path(output_dir, conference, year)
                    result = {
                        "conference": conference.id,
                        "display_name": conference.display_name,
                        "paper_count": len(papers),
                        "output_path": output_path,
                        "feed_url": _feed_url(conference, year),
                    }
                    results.append(result)
                    if total == 1:
                        _append_job_log(job_id, f"Completed collection with {len(papers)} saved papers.")
                    else:
                        _append_job_log(job_id, f"Completed {conference.display_name} with {len(papers)} saved papers.")
                    _append_job_log(job_id, f"Saved JSON output to {output_path}.")
                    _update_job(
                        job_id,
                        completed_count=len(results),
                        failed_count=len(errors),
                        results=list(results),
                        errors=list(errors),
                        paper_count=sum(result["paper_count"] for result in results),
                        output_paths=[result["output_path"] for result in results],
                    )
                except Exception as exc:
                    log_writer.flush()
                    error = {
                        "conference": conference.id,
                        "display_name": conference.display_name,
                        "error": str(exc),
                    }
                    errors.append(error)
                    if total == 1:
                        _append_job_log(job_id, f"Collection failed: {exc}")
                        _update_job(
                            job_id,
                            status="failed",
                            error=str(exc),
                            failed_count=1,
                            errors=list(errors),
                        )
                        return
                    _append_job_log(job_id, f"Collection failed for {conference.display_name}: {exc}")
                    _update_job(
                        job_id,
                        completed_count=len(results),
                        failed_count=len(errors),
                        errors=list(errors),
                    )

            if results:
                if total > 1:
                    _append_job_log(
                        job_id,
                        f"Batch completed: {len(results)} succeeded, {len(errors)} failed.",
                    )
                _update_job(
                    job_id,
                    status="completed",
                    paper_count=sum(result["paper_count"] for result in results),
                    output_path=results[0]["output_path"] if total == 1 else None,
                    output_paths=[result["output_path"] for result in results],
                    feed_url=results[0]["feed_url"] if total == 1 else None,
                    feed_urls=[result["feed_url"] for result in results],
                    results=list(results),
                    errors=list(errors),
                    completed_count=len(results),
                    failed_count=len(errors),
                )
                return

            error_message = "All selected conferences failed."
            if errors:
                error_message = "; ".join(
                    f"{error['display_name']}: {error['error']}" for error in errors
                )
            _update_job(
                job_id,
                status="failed",
                error=error_message,
                errors=list(errors),
                failed_count=len(errors),
            )
        finally:
            active_lock.release()

    def _run_index_job(
        job_id: str,
        config: dict[str, Any],
        output_dir: str,
        force: bool,
        active_lock: FileJobLock,
    ) -> None:
        try:
            _update_job(job_id, status="running")
            _append_job_log(job_id, "Building Qdrant hybrid vector index.")
            stats = build_vector_index(config, output_dir, force=force)
            _append_job_log(job_id, f"Indexed {stats['paper_count']} papers into {stats['collection']}.")
            _update_job(
                job_id,
                status="completed",
                paper_count=stats["paper_count"],
                source_count=stats["source_count"],
                backend=stats["backend"],
                provider=stats["provider"],
                collection=stats["collection"],
                result=stats,
            )
        except Exception as exc:
            _append_job_log(job_id, f"Index build failed: {exc}")
            _update_job(job_id, status="failed", error=str(exc))
        finally:
            active_lock.release()

    def _update_job(job_id: str, **updates: Any) -> None:
        job_store.update(job_id, **updates)

    def _append_job_log(job_id: str, message: str) -> None:
        job_store.append_log(job_id, message, max_lines=MAX_JOB_LOG_LINES)

    def _feed_url(conference: ConferenceEntry, year: int) -> str:
        encoded = quote(conference.id, safe="")
        return _with_url_base(f"/feed/{encoded}/{year}.xml", url_base)

    return app


def _load_config(config_path: str) -> dict[str, Any]:
    if not os.path.exists(config_path):
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _job_store_dir(config: dict[str, Any]) -> str:
    configured = config.get("job_store_dir")
    if configured:
        return str(configured)
    output_dir = str(config.get("output_dir", "data"))
    return os.path.join(output_dir, "jobs")


def _normalize_url_base(value: Any) -> str:
    if value in (None, "", "/"):
        return ""

    base = str(value).strip()
    if not base or base == "/":
        return ""
    if "://" in base:
        raise ValueError("url_base must be a path prefix such as /papercollect, not a full URL.")
    if not base.startswith("/"):
        base = f"/{base}"
    return base.rstrip("/")


def _with_url_base(path: str, url_base: str) -> str:
    if not url_base:
        return path
    if not path.startswith("/"):
        path = f"/{path}"
    if path == url_base or path.startswith(f"{url_base}/"):
        return path
    return f"{url_base}{path}"


def _prefix_rule(url_base: str, rule: str) -> str:
    if rule == "/":
        return f"{url_base}/"
    return _with_url_base(rule, url_base)


def _queued_collection_logs(conferences: list[ConferenceEntry], year: int, feed_urls: list[str]) -> list[str]:
    if len(conferences) == 1:
        return [
            f"Queued collection for {conferences[0].display_name} {year}.",
            f"RSS feed will be available at {feed_urls[0]}.",
        ]

    return [
        f"Queued collection for {len(conferences)} conferences in {year}.",
        "RSS feeds will be available as each conference completes.",
    ]


def _resolve_collection_conferences(
    payload: dict[str, Any],
    config: dict[str, Any],
) -> tuple[list[ConferenceEntry], str | None]:
    raw_values = payload.get("conferences")
    if raw_values is None:
        raw_value = payload.get("conference")
        raw_values = [raw_value] if raw_value not in (None, "") else []
    elif isinstance(raw_values, str):
        raw_values = [raw_values]

    if not isinstance(raw_values, list):
        return [], "Choose conferences from config.yaml."

    conferences = []
    seen = set()
    for raw_value in raw_values:
        if raw_value in (None, ""):
            continue
        entry = find_conference(config, str(raw_value))
        if entry is None:
            return [], "Choose conferences from config.yaml."
        if entry.id in seen:
            continue
        conferences.append(entry)
        seen.add(entry.id)

    if not conferences:
        return [], "Choose at least one conference from config.yaml."
    return conferences, None


def _validate_collection_payload(payload: dict[str, Any], config: dict[str, Any]) -> str | None:
    _, conference_error = _resolve_collection_conferences(payload, config)
    if conference_error:
        return conference_error

    try:
        year = int(payload.get("year"))
    except (TypeError, ValueError):
        return "Choose a valid year from config.yaml."

    if not valid_collection_year(year):
        return "Choose a year between 1900 and two years from now."

    try:
        _resolve_limit(payload.get("limit"), config)
    except ValueError as exc:
        return str(exc)

    return None


def _resolve_limit(value: Any, config: dict[str, Any]) -> int:
    if value in (None, ""):
        return int(config.get("limit_per_conference", 0))

    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Limit must be a non-negative integer.") from exc

    if limit < 0:
        raise ValueError("Limit must be a non-negative integer.")
    return limit


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError("Boolean fields must be true or false.")


def _request_list_args(*names: str) -> list[str]:
    values = []
    seen = set()
    for name in names:
        for raw_value in request.args.getlist(name):
            for value in str(raw_value).split(","):
                text = value.strip()
                key = text.lower()
                if text and key not in seen:
                    values.append(text)
                    seen.add(key)
    return values


def _normalize_optional_text(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    return text or None


def _known_ccf_tiers(config: dict[str, Any]) -> set[str]:
    tiers = set()
    for entry in normalize_conferences(config):
        value = _normalize_optional_text(entry.tier.get("ccf"))
        if value:
            tiers.add(value)
    return tiers


def _find_saved_output(output_dir: str, conference: ConferenceEntry, year: int) -> str | None:
    candidates = [conference.id, conference.display_name, *conference.aliases]
    for candidate in candidates:
        output_path = get_output_path(output_dir, candidate, year)
        if os.path.exists(output_path):
            return output_path
    return None


def _saved_years_for_conference(output_dir: str, conference: ConferenceEntry) -> set[int]:
    if not os.path.isdir(output_dir):
        return set()

    stems = {
        os.path.basename(get_output_path(output_dir, candidate, 2000)).removesuffix("_2000.json")
        for candidate in [conference.id, conference.display_name, *conference.aliases]
    }
    years = set()
    for filename in os.listdir(output_dir):
        if not filename.endswith(".json"):
            continue
        stem, _, year_part = filename.removesuffix(".json").rpartition("_")
        if stem in stems and year_part.isdigit() and len(year_part) == 4:
            years.add(int(year_part))
    return years
