import os
import subprocess
import sys
import threading
import time

import requests
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
from src.services.job_store import (
    FileJobLock,
    JobStore,
    _extract_summary,
    build_queue_items,
    has_resumable_tasks,
    has_retryable_tasks,
    mark_pending_tasks_skipped,
    queue_task_summary,
    reset_failed_and_skipped_tasks,
    reset_skipped_tasks,
)
from src.services.metadata_manager import MetadataManager
from src.services.paper_search import search_saved_papers
from src.services.rss_service import build_rss_xml, count_papers, load_papers
from src.services.vector_index import VectorIndexError, vector_index_status
from src.services.webdav_sync import (
    WebDAVClient,
    load_webdav_config,
    sync_download,
    sync_status,
    sync_upload,
)

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
    sync_lock = FileJobLock(os.path.join(job_store.path, "sync.lock"), "sync")

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

    @route("/api/year-progress", methods=["GET"])
    def year_progress() -> Response:
        config = _load_config(config_path)
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

        cache_key = f"yp:{output_dir}" + (f":{','.join(str(y) for y in custom_years)}" if custom_years else "")
        now = time.time()
        cached = _FEEDS_CACHE.get(cache_key)
        if cached and now - cached[0] < _CACHE_TTL:
            return jsonify(cached[1])
        default_years = [int(y) for y in config.get("years", [])]
        progress = []
        for conference in normalize_conferences(config):
            conf_years = list(conference.years) if conference.years else default_years
            if custom_years:
                conf_years = sorted(set(int(y) for y in conf_years) | set(custom_years))
            saved = _saved_years_for_conference(output_dir, conference)
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
        _FEEDS_CACHE[cache_key] = (time.time(), result)
        return jsonify(result)

    @route("/api/collect", methods=["POST"])
    def collect() -> tuple[Response, int] | Response:
        payload = request.get_json(silent=True) or {}
        config = _load_config(config_path)
        conferences, validation_error = _resolve_collection_conferences(payload, config)
        if validation_error:
            return jsonify({"error": validation_error}), 400

        # Accept years array or single year (backward compatible).
        raw_years = payload.get("years")
        if isinstance(raw_years, list) and raw_years:
            try:
                years = [int(y) for y in raw_years]
            except (TypeError, ValueError):
                return jsonify({"error": "Choose valid years."}), 400
        else:
            try:
                years = [int(payload["year"])]
            except (KeyError, TypeError, ValueError):
                return jsonify({"error": "Choose a valid year from config.yaml."}), 400
        for year in years:
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

        queue = build_queue_items(conferences, years)
        total_tasks = len(queue)
        feed_urls = [item["feed_url"] or "" for item in queue if item.get("feed_url")]
        single_task = total_tasks == 1
        first = queue[0] if queue else {}
        job = job_store.create(
            {
                "type": "collection",
                "status": "queued",
                "conference": first.get("conference_id", conferences[0].id),
                "display_name": first.get("display_name", conferences[0].display_name)
                if single_task
                else f"{total_tasks} tasks",
                "conferences": [conference.id for conference in conferences],
                "display_names": [conference.display_name for conference in conferences],
                "conference_count": len(conferences),
                "years": years,
                "year": years[0],
                "completed_count": 0,
                "failed_count": 0,
                "results": [],
                "errors": [],
                "limit": limit,
                "logs": _queued_collection_logs_multi(conferences, years, total_tasks),
                "paper_count": None,
                "feed_url": None,
                "feed_urls": [],
                "cancel_requested": False,
                "stopped_count": 0,
                "queue": queue,
            }
        )

        _spawn_collection_worker(job["id"], output_dir, threads, collection_lock)

        return jsonify(
            {
                "job_id": job["id"],
                "status_url": _with_url_base(
                    url_for("job_status", job_id=job["id"]),
                    url_base,
                ),
            }
        ), 202

    @route("/api/jobs", methods=["GET"])
    def list_jobs() -> Response:
        jobs = job_store.list(summary=True)
        return jsonify({"jobs": jobs})

    @route("/api/jobs/<job_id>", methods=["GET"])
    def job_status(job_id: str) -> tuple[Response, int] | Response:
        job = job_store.get(job_id)
        if not job:
            return jsonify({"error": "Job not found."}), 404
        queue = job.get("queue")
        if queue:
            job["task_summary"] = queue_task_summary(queue)
        return jsonify(job)

    @route("/api/jobs/<job_id>/stop", methods=["POST"])
    def job_stop(job_id: str) -> tuple[Response, int] | Response:
        job = job_store.get(job_id)
        if not job:
            return jsonify({"error": "Job not found."}), 404
        if job.get("type") != "collection":
            return jsonify({"error": "Only collection jobs can be stopped."}), 400
        if job.get("status") not in {"queued", "running"}:
            return jsonify({"error": "Collection job is not running.", "job": job}), 409

        if not job.get("cancel_requested"):
            job_store.update(job_id, cancel_requested=True)
            job_store.append_log(
                job_id,
                "Stop requested; collection will stop after the current conference.",
                max_lines=MAX_JOB_LOG_LINES,
            )
        updated = job_store.get(job_id) or job
        queue = updated.get("queue")
        if queue:
            updated["task_summary"] = queue_task_summary(queue)
        return jsonify(updated), 202

    @route("/api/jobs/<job_id>/resume", methods=["POST"])
    def job_resume(job_id: str) -> tuple[Response, int] | Response:
        job = job_store.get(job_id)
        if not job:
            return jsonify({"error": "Job not found."}), 404
        if job.get("type") != "collection":
            return jsonify({"error": "Only collection jobs can be resumed."}), 400
        if job.get("status") == "running":
            return jsonify({"error": "Job is already running."}), 409
        if job.get("status") not in {"stopped", "failed"}:
            return jsonify({"error": "Job cannot be resumed from its current state."}), 400

        queue = job.get("queue") or []
        if not has_resumable_tasks(queue):
            return jsonify({"error": "No tasks to resume."}), 400

        if not collection_lock.acquire(blocking=False):
            return jsonify({"error": "A collection job is already running."}), 409

        reset_skipped_tasks(queue)
        job_store.update(
            job_id,
            status="running",
            cancel_requested=False,
            queue=queue,
            error=None,
        )
        job_store.append_log(job_id, "Resuming collection.", max_lines=MAX_JOB_LOG_LINES)

        config = _load_config(config_path)
        output_dir = str(config.get("output_dir", "data"))
        threads = int(config.get("concurrency", {}).get("threads", 4))
        _spawn_collection_worker(job_id, output_dir, threads, collection_lock)

        return jsonify(
            {
                "job_id": job_id,
                "status_url": _with_url_base(
                    url_for("job_status", job_id=job_id),
                    url_base,
                ),
            }
        ), 202

    @route("/api/jobs/<job_id>/retry", methods=["POST"])
    def job_retry(job_id: str) -> tuple[Response, int] | Response:
        job = job_store.get(job_id)
        if not job:
            return jsonify({"error": "Job not found."}), 404
        if job.get("type") != "collection":
            return jsonify({"error": "Only collection jobs can be retried."}), 400
        if job.get("status") not in {"stopped", "failed", "completed"}:
            return jsonify({"error": "Job cannot be retried from its current state."}), 400

        queue = job.get("queue") or []
        if not has_retryable_tasks(queue):
            return jsonify({"error": "No failed tasks to retry."}), 400

        if not collection_lock.acquire(blocking=False):
            return jsonify({"error": "A collection job is already running."}), 409

        reset_failed_and_skipped_tasks(queue)
        job_store.update(
            job_id,
            status="running",
            cancel_requested=False,
            queue=queue,
            error=None,
        )
        job_store.append_log(job_id, "Retrying failed tasks.", max_lines=MAX_JOB_LOG_LINES)

        config = _load_config(config_path)
        output_dir = str(config.get("output_dir", "data"))
        threads = int(config.get("concurrency", {}).get("threads", 4))
        _spawn_collection_worker(job_id, output_dir, threads, collection_lock)

        return jsonify(
            {
                "job_id": job_id,
                "status_url": _with_url_base(
                    url_for("job_status", job_id=job_id),
                    url_base,
                ),
            }
        ), 202

    @route("/api/jobs/<job_id>/queue/<task_id>/retry", methods=["POST"])
    def task_retry(job_id: str, task_id: str) -> tuple[Response, int] | Response:
        job = job_store.get(job_id)
        if not job:
            return jsonify({"error": "Job not found."}), 404
        if job.get("type") != "collection":
            return jsonify({"error": "Only collection jobs support task retry."}), 400

        queue = job.get("queue") or []
        target = None
        for item in queue:
            if item.get("task_id") == task_id:
                target = item
                break
        if target is None:
            return jsonify({"error": "Task not found."}), 404
        if target["status"] not in {"failed", "skipped"}:
            return jsonify({"error": "Task cannot be retried in its current state."}), 400

        target["status"] = "pending"
        target["error"] = None
        target["started_at"] = None
        target["finished_at"] = None
        job_store.update(job_id, queue=queue)
        job_store.append_log(
            job_id,
            f"Retrying task {task_id} ({target['display_name']}).",
            max_lines=MAX_JOB_LOG_LINES,
        )

        needs_worker = job.get("status") not in {"running", "queued"}
        if needs_worker:
            if not collection_lock.acquire(blocking=False):
                return jsonify({"error": "A collection job is already running."}), 409
            job_store.update(job_id, status="running", cancel_requested=False)
            config = _load_config(config_path)
            output_dir = str(config.get("output_dir", "data"))
            threads = int(config.get("concurrency", {}).get("threads", 4))
            _spawn_collection_worker(job_id, output_dir, threads, collection_lock)

        updated = job_store.get(job_id) or job
        queue = updated.get("queue")
        if queue:
            updated["task_summary"] = queue_task_summary(queue)
        return jsonify(updated), 202

    @route("/api/jobs/<job_id>", methods=["DELETE"])
    def job_delete(job_id: str) -> tuple[Response, int] | Response:
        job = job_store.get(job_id)
        if not job:
            return jsonify({"error": "Job not found."}), 404
        if job.get("status") in {"running", "queued"}:
            return jsonify({"error": "Cannot delete a running job. Stop it first."}), 409
        job_store.delete(job_id)
        return jsonify({"deleted": job_id}), 200

    @route("/api/jobs/<job_id>/queue", methods=["POST"])
    def queue_add_task(job_id: str) -> tuple[Response, int] | Response:
        job = job_store.get(job_id)
        if not job:
            return jsonify({"error": "Job not found."}), 404
        if job.get("type") != "collection":
            return jsonify({"error": "Only collection jobs support queue operations."}), 400
        if job.get("status") not in {"queued", "stopped", "failed", "completed"}:
            return jsonify({"error": "Cannot modify queue while job is running."}), 409

        payload = request.get_json(silent=True) or {}
        conference_id = payload.get("conference_id")
        year = payload.get("year")
        if not conference_id or not year:
            return jsonify({"error": "conference_id and year are required."}), 400

        config = _load_config(config_path)
        conference = find_conference(config, str(conference_id))
        if not conference:
            return jsonify({"error": f"Unknown conference: {conference_id}"}), 400

        import uuid as _uuid
        task = {
            "task_id": _uuid.uuid4().hex[:8],
            "conference_id": conference.id,
            "display_name": conference.display_name,
            "year": int(year),
            "status": "pending",
            "paper_count": None,
            "output_path": None,
            "feed_url": None,
            "error": None,
            "started_at": None,
            "finished_at": None,
        }
        queue = job.get("queue") or []
        queue.append(task)
        job_store.update(job_id, queue=queue)
        job_store.append_log(
            job_id,
            f"Added task: {conference.display_name} {year}",
            max_lines=MAX_JOB_LOG_LINES,
        )
        updated = job_store.get(job_id) or job
        updated["task_summary"] = queue_task_summary(updated.get("queue") or [])
        return jsonify(updated), 201

    @route("/api/jobs/<job_id>/queue/<task_id>", methods=["DELETE"])
    def queue_remove_task(job_id: str, task_id: str) -> tuple[Response, int] | Response:
        job = job_store.get(job_id)
        if not job:
            return jsonify({"error": "Job not found."}), 404
        if job.get("status") in {"running"}:
            return jsonify({"error": "Cannot modify queue while job is running."}), 409

        queue = job.get("queue") or []
        target = None
        for item in queue:
            if item.get("task_id") == task_id:
                target = item
                break
        if target is None:
            return jsonify({"error": "Task not found."}), 404
        if target["status"] not in {"pending", "skipped"}:
            return jsonify({"error": "Only pending or skipped tasks can be removed."}), 400

        queue = [item for item in queue if item.get("task_id") != task_id]
        job_store.update(job_id, queue=queue)
        job_store.append_log(
            job_id,
            f"Removed task: {target['display_name']} {target['year']}",
            max_lines=MAX_JOB_LOG_LINES,
        )
        updated = job_store.get(job_id) or job
        updated["task_summary"] = queue_task_summary(updated.get("queue") or [])
        return jsonify(updated), 200

    @route("/api/jobs/<job_id>/queue/reorder", methods=["POST"])
    def queue_reorder(job_id: str) -> tuple[Response, int] | Response:
        job = job_store.get(job_id)
        if not job:
            return jsonify({"error": "Job not found."}), 404
        if job.get("status") in {"running"}:
            return jsonify({"error": "Cannot reorder queue while job is running."}), 409

        payload = request.get_json(silent=True) or {}
        new_order = payload.get("task_ids")
        if not isinstance(new_order, list):
            return jsonify({"error": "task_ids array is required."}), 400

        queue = job.get("queue") or []
        queue_by_id = {item["task_id"]: item for item in queue}
        reordered: list[dict[str, Any]] = []
        for tid in new_order:
            if tid in queue_by_id:
                reordered.append(queue_by_id.pop(tid))
        # append any remaining items not in the reorder list
        reordered.extend(queue_by_id.values())
        job_store.update(job_id, queue=reordered)
        updated = job_store.get(job_id) or job
        updated["task_summary"] = queue_task_summary(updated.get("queue") or [])
        return jsonify(updated), 200

    @route("/api/feeds", methods=["GET"])
    def feeds() -> Response:
        config = _load_config(config_path)
        output_dir = str(config.get("output_dir", "data"))
        cache_key = output_dir
        now = time.time()
        cached = _FEEDS_CACHE.get(cache_key)
        if cached and now - cached[0] < _CACHE_TTL:
            return jsonify(cached[1])
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
        _FEEDS_CACHE[cache_key] = (time.time(), result)
        return jsonify(result)

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
            args=(job["id"], config, config_path, force, index_lock),
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

    @route("/api/sync/status", methods=["GET"])
    def sync_status_endpoint() -> tuple[Response, int] | Response:
        config = _load_config(config_path)
        webdav_config = load_webdav_config(config)
        if not webdav_config:
            return jsonify({"error": "WebDAV is not configured."}), 503
        output_dir = str(config.get("output_dir", "data"))
        client = WebDAVClient(
            webdav_config["url"],
            webdav_config["username"],
            webdav_config["password"],
            verify_ssl=webdav_config.get("verify_ssl", True),
        )
        remote_path = webdav_config.get("remote_path", "/")
        # Quick connectivity check — fail fast if server is unreachable.
        try:
            client.session.head(
                webdav_config["url"],
                timeout=(5, 5),
            )
        except requests.RequestException:
            return jsonify({
                "error": f"Cannot reach WebDAV server at {webdav_config['url']}",
                "remote_path": remote_path,
                "remote_url": webdav_config["url"],
                "local_only": [],
                "remote_only": [],
                "both": [],
                "remote_files": [],
            }), 502
        try:
            result = sync_status(client, output_dir, remote_path, timeout=10)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 502
        result["remote_path"] = remote_path
        result["remote_url"] = webdav_config["url"]
        return jsonify(result)

    @route("/api/sync/upload", methods=["POST"])
    def sync_upload_endpoint() -> tuple[Response, int] | Response:
        config = _load_config(config_path)
        webdav_config = load_webdav_config(config)
        if not webdav_config:
            return jsonify({"error": "WebDAV is not configured."}), 503
        if not sync_lock.acquire(blocking=False):
            return jsonify({"error": "A sync job is already running."}), 409
        output_dir = str(config.get("output_dir", "data"))
        remote_path = webdav_config.get("remote_path", "/")
        job = job_store.create(
            {
                "type": "sync",
                "direction": "upload",
                "status": "queued",
                "remote_url": webdav_config["url"],
                "remote_path": remote_path,
                "logs": ["Queued sync upload to remote."],
                "result": None,
            }
        )
        thread = threading.Thread(
            target=_run_sync_upload_job,
            args=(job["id"], webdav_config, output_dir, remote_path, sync_lock),
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

    @route("/api/sync/download", methods=["POST"])
    def sync_download_endpoint() -> tuple[Response, int] | Response:
        config = _load_config(config_path)
        webdav_config = load_webdav_config(config)
        if not webdav_config:
            return jsonify({"error": "WebDAV is not configured."}), 503
        if not sync_lock.acquire(blocking=False):
            return jsonify({"error": "A sync job is already running."}), 409
        output_dir = str(config.get("output_dir", "data"))
        remote_path = webdav_config.get("remote_path", "/")
        job = job_store.create(
            {
                "type": "sync",
                "direction": "download",
                "status": "queued",
                "remote_url": webdav_config["url"],
                "remote_path": remote_path,
                "logs": ["Queued sync download from remote."],
                "result": None,
            }
        )
        thread = threading.Thread(
            target=_run_sync_download_job,
            args=(job["id"], webdav_config, output_dir, remote_path, sync_lock),
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

    def _run_sync_upload_job(
        job_id: str,
        webdav_config: dict[str, str],
        output_dir: str,
        remote_path: str,
        active_lock: FileJobLock,
    ) -> None:
        try:
            _update_job(job_id, status="running")
            client = WebDAVClient(
                webdav_config["url"],
                webdav_config["username"],
                webdav_config["password"],
            )
            _append_job_log(job_id, "Starting sync upload...")
            result = sync_upload(client, output_dir, remote_path)
            _append_job_log(
                job_id,
                f"Upload complete: {len(result['uploaded'])} uploaded, "
                f"{len(result['skipped'])} skipped, {len(result['errors'])} errors.",
            )
            if result["errors"]:
                for err in result["errors"]:
                    _append_job_log(job_id, f"Error uploading {err['file']}: {err['error']}")
            _update_job(job_id, status="completed", result=result)
        except Exception as exc:
            _append_job_log(job_id, f"Sync upload failed: {exc}")
            _update_job(job_id, status="failed", error=str(exc))
        finally:
            active_lock.release()

    def _run_sync_download_job(
        job_id: str,
        webdav_config: dict[str, str],
        output_dir: str,
        remote_path: str,
        active_lock: FileJobLock,
    ) -> None:
        try:
            _update_job(job_id, status="running")
            client = WebDAVClient(
                webdav_config["url"],
                webdav_config["username"],
                webdav_config["password"],
            )
            _append_job_log(job_id, "Starting sync download...")
            result = sync_download(client, output_dir, remote_path)
            _append_job_log(
                job_id,
                f"Download complete: {len(result['downloaded'])} downloaded, "
                f"{len(result['skipped'])} skipped, {len(result['errors'])} errors.",
            )
            if result["errors"]:
                for err in result["errors"]:
                    _append_job_log(job_id, f"Error downloading {err['file']}: {err['error']}")
            _update_job(job_id, status="completed", result=result)
        except Exception as exc:
            _append_job_log(job_id, f"Sync download failed: {exc}")
            _update_job(job_id, status="failed", error=str(exc))
        finally:
            active_lock.release()

    # Pre-warm caches in background on startup.
    def _prewarm() -> None:
        import threading as _threading
        def _do() -> None:
            try:
                time.sleep(0.5)
                cfg = _load_config(config_path)
                out = str(cfg.get("output_dir", "data"))
                # Warm feeds cache
                all_feeds = []
                for conf in normalize_conferences(cfg):
                    yrs = sorted(
                        {int(y) for y in configured_years(cfg, conf)}
                        | _saved_years_for_conference(out, conf)
                    )
                    for yr in yrs:
                        pc = count_papers(out, conf.id, yr, aliases=[conf.display_name, *conf.aliases])
                        if pc:
                            all_feeds.append({
                                "conference": conf.id, "display_name": conf.display_name,
                                "year": yr, "paper_count": pc,
                                "feed_url": _feed_url(conf, yr),
                            })
                _FEEDS_CACHE[out] = (time.time(), {"feeds": all_feeds})
                # Warm year-progress cache
                default_years = [int(y) for y in cfg.get("years", [])]
                progress = []
                for conf in normalize_conferences(cfg):
                    conf_years = list(conf.years) if conf.years else default_years
                    saved = _saved_years_for_conference(out, conf)
                    progress.append({
                        "conference_id": conf.id, "display_name": conf.display_name,
                        "category": conf.category,
                        "ccf": (conf.tier.get("ccf") or "").strip().upper() or None,
                        "configured_years": [int(y) for y in conf_years],
                        "saved_years": sorted(saved),
                        "missing_years": sorted(set(int(y) for y in conf_years) - saved),
                    })
                _FEEDS_CACHE[f"yp:{out}"] = (time.time(), {"progress": progress})
            except Exception:
                pass
        _threading.Thread(target=_do, daemon=True).start()

    _prewarm()

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

    def _spawn_collection_worker(
        job_id: str,
        output_dir: str,
        threads: int,
        active_lock: FileJobLock,
    ) -> None:
        thread = threading.Thread(
            target=_run_collection_job,
            args=(job_id, output_dir, threads, active_lock),
            daemon=True,
        )
        thread.start()

    def _run_collection_job(
        job_id: str,
        output_dir: str,
        threads: int,
        active_lock: FileJobLock,
    ) -> None:
        job = job_store.get(job_id) or {}
        limit = int(job["limit"])
        conference_ids = job.get("conferences") or []
        _update_job(job_id, status="running")
        queue: list[dict[str, Any]] = job.get("queue") or []
        total = len(queue)
        try:
            os.makedirs(output_dir, exist_ok=True)

            config = _load_config(config_path)
            conference_map: dict[str, ConferenceEntry] = {}
            for cid in conference_ids:
                entry = find_conference(config, cid)
                if entry is not None:
                    conference_map[cid] = entry

            for index, task in enumerate(queue):
                if task["status"] != "pending":
                    continue

                if _collection_cancel_requested(job_id):
                    _mark_collection_stopped(job_id, queue)
                    return

                task_year = int(task.get("year") or job.get("year"))
                conference = conference_map.get(task["conference_id"])
                if conference is None:
                    task["status"] = "failed"
                    task["error"] = f"Conference {task['conference_id']} not found in config."
                    task["finished_at"] = time.time()
                    _sync_queue_to_job(job_id, queue)
                    continue

                task["status"] = "running"
                task["started_at"] = time.time()
                _sync_queue_to_job(job_id, queue)

                progress = f" ({index + 1}/{total})" if total > 1 else ""
                _append_job_log(job_id, f"Started collection for {conference.display_name} {task_year}{progress}.")
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
                            task_year,
                            DBLPClient(),
                            MetadataManager(threads=threads),
                            output_dir,
                            limit,
                        )
                    log_writer.flush()

                    papers = load_papers(
                        output_dir,
                        conference.id,
                        task_year,
                        aliases=[conference.display_name, *conference.aliases],
                    )
                    output_path = get_output_path(output_dir, conference, task_year)
                    task["status"] = "completed"
                    task["paper_count"] = len(papers)
                    task["output_path"] = output_path
                    task["feed_url"] = _feed_url(conference, task_year)
                    task["finished_at"] = time.time()

                    if total == 1:
                        _append_job_log(job_id, f"Completed collection with {len(papers)} saved papers.")
                    else:
                        _append_job_log(job_id, f"Completed {conference.display_name} with {len(papers)} saved papers.")
                    _append_job_log(job_id, f"Saved JSON output to {output_path}.")

                    _sync_queue_to_job(job_id, queue)
                    if _collection_cancel_requested(job_id):
                        _mark_collection_stopped(job_id, queue)
                        return
                except Exception as exc:
                    log_writer.flush()
                    task["status"] = "failed"
                    task["error"] = str(exc)
                    task["finished_at"] = time.time()
                    if total == 1:
                        _append_job_log(job_id, f"Collection failed: {exc}")
                    else:
                        _append_job_log(job_id, f"Collection failed for {conference.display_name}: {exc}")
                    _sync_queue_to_job(job_id, queue)
                    if _collection_cancel_requested(job_id):
                        _mark_collection_stopped(job_id, queue)
                        return

            summary = queue_task_summary(queue)
            results = [
                {
                    "conference": item["conference_id"],
                    "display_name": item["display_name"],
                    "year": item.get("year"),
                    "paper_count": item["paper_count"] or 0,
                    "output_path": item["output_path"],
                    "feed_url": item["feed_url"],
                }
                for item in queue
                if item["status"] == "completed"
            ]
            errors = [
                {
                    "conference": item["conference_id"],
                    "display_name": item["display_name"],
                    "year": item.get("year"),
                    "error": item["error"],
                }
                for item in queue
                if item["status"] == "failed"
            ]

            if results:
                if total > 1:
                    _append_job_log(
                        job_id,
                        f"Batch completed: {summary['completed']} succeeded, {summary['failed']} failed.",
                    )
                _update_job(
                    job_id,
                    status="completed",
                    paper_count=sum(r["paper_count"] for r in results),
                    output_path=results[0]["output_path"] if total == 1 else None,
                    output_paths=[r["output_path"] for r in results],
                    feed_url=results[0]["feed_url"] if total == 1 else None,
                    feed_urls=[r["feed_url"] for r in results],
                    results=results,
                    errors=errors,
                    completed_count=summary["completed"],
                    failed_count=summary["failed"],
                    stopped_count=summary["skipped"],
                    queue=queue,
                )
                return

            error_message = "All selected conferences failed."
            if errors:
                if total == 1:
                    error_message = errors[0]["error"]
                else:
                    error_message = "; ".join(
                        f"{error['display_name']}: {error['error']}" for error in errors
                    )
            _update_job(
                job_id,
                status="failed",
                error=error_message,
                errors=errors,
                failed_count=summary["failed"],
                stopped_count=summary["skipped"],
                queue=queue,
            )
        finally:
            active_lock.release()

    def _sync_queue_to_job(job_id: str, queue: list[dict[str, Any]]) -> None:
        """Update job with current queue state and derived fields."""
        summary = queue_task_summary(queue)
        results = [
            {
                "conference": item["conference_id"],
                "display_name": item["display_name"],
                "year": item.get("year"),
                "paper_count": item["paper_count"] or 0,
                "output_path": item["output_path"],
                "feed_url": item["feed_url"],
            }
            for item in queue
            if item["status"] == "completed"
        ]
        errors = [
            {
                "conference": item["conference_id"],
                "display_name": item["display_name"],
                "year": item.get("year"),
                "error": item["error"],
            }
            for item in queue
            if item["status"] == "failed"
        ]
        _update_job(
            job_id,
            queue=list(queue),
            results=results,
            errors=errors,
            completed_count=summary["completed"],
            failed_count=summary["failed"],
            stopped_count=summary["skipped"],
            paper_count=sum(r["paper_count"] for r in results),
            output_paths=[r["output_path"] for r in results],
            feed_urls=[r["feed_url"] for r in results],
        )

    def _run_index_job(
        job_id: str,
        config: dict[str, Any],
        config_path: str,
        force: bool,
        active_lock: FileJobLock,
    ) -> None:
        try:
            _update_job(job_id, status="running")
            command = _index_command(config_path, force=force)
            _append_job_log(job_id, f"Starting index subprocess: {' '.join(command)}")
            returncode = _run_index_subprocess(
                command,
                cwd=os.getcwd(),
                append_log=lambda line: _append_job_log(job_id, line),
            )
            if returncode != 0:
                raise RuntimeError(f"pc-index exited with status {returncode}")
            stats = vector_index_status(config)
            _append_job_log(job_id, f"Indexed {stats['paper_count']} papers into {stats['collection']}.")
            _update_job(
                job_id,
                status="completed",
                paper_count=stats["paper_count"],
                source_count=stats.get("source_count"),
                backend=stats["backend"],
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

    def _collection_cancel_requested(job_id: str) -> bool:
        job = job_store.get(job_id) or {}
        return bool(job.get("cancel_requested"))

    def _mark_collection_stopped(
        job_id: str,
        queue: list[dict[str, Any]],
    ) -> None:
        mark_pending_tasks_skipped(queue)
        summary = queue_task_summary(queue)
        results = [
            {
                "conference": item["conference_id"],
                "display_name": item["display_name"],
                "year": item.get("year"),
                "paper_count": item["paper_count"] or 0,
                "output_path": item["output_path"],
                "feed_url": item["feed_url"],
            }
            for item in queue
            if item["status"] == "completed"
        ]
        errors = [
            {
                "conference": item["conference_id"],
                "display_name": item["display_name"],
                "year": item.get("year"),
                "error": item["error"],
            }
            for item in queue
            if item["status"] == "failed"
        ]
        _append_job_log(
            job_id,
            f"Collection stopped by user; {summary['skipped']} tasks were not started.",
        )
        _update_job(
            job_id,
            status="stopped",
            cancel_requested=True,
            paper_count=sum(r["paper_count"] for r in results),
            output_path=results[0]["output_path"] if len(results) == 1 else None,
            output_paths=[r["output_path"] for r in results],
            feed_url=results[0]["feed_url"] if len(results) == 1 else None,
            feed_urls=[r["feed_url"] for r in results],
            results=results,
            errors=errors,
            completed_count=summary["completed"],
            failed_count=summary["failed"],
            stopped_count=summary["skipped"],
            queue=queue,
        )

    def _feed_url(conference: ConferenceEntry, year: int) -> str:
        encoded = quote(conference.id, safe="")
        return _with_url_base(f"/feed/{encoded}/{year}.xml", url_base)

    return app


_CONFIG_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_FEEDS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL = 5  # seconds


def _load_config(config_path: str) -> dict[str, Any]:
    now = time.time()
    cached = _CONFIG_CACHE.get(config_path)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]
    if not os.path.exists(config_path):
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    _CONFIG_CACHE[config_path] = (now, config)
    return config


def _index_command(config_path: str, *, force: bool) -> list[str]:
    command = [sys.executable, "-m", "index_papers", "--config", config_path]
    if not force:
        command.append("--no-force")
    return command


def _run_index_subprocess(
    command: list[str],
    *,
    cwd: str,
    append_log: Callable[[str], None],
) -> int:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    for line in process.stdout:
        text = line.rstrip()
        if text:
            append_log(text)
    return process.wait()


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


def _queued_collection_logs_multi(
    conferences: list[ConferenceEntry],
    years: list[int],
    total_tasks: int,
) -> list[str]:
    year_str = ", ".join(str(y) for y in years)
    return [
        f"Queued {total_tasks} collection tasks for {len(conferences)} conferences across {len(years)} year(s) ({year_str}).",
        "RSS feeds will be available as each task completes.",
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
