from flask import Blueprint, Response, current_app, jsonify, request

from src.core.conference_catalog import (
    find_conference,
    valid_collection_year,
)
from src.services.job_store import (
    FileJobLock,
    build_queue_items,
    build_queue_items_for_tasks,
    has_resumable_tasks,
    has_retryable_tasks,
    queue_task_summary,
    reset_failed_and_skipped_tasks,
    reset_skipped_tasks,
)
from src.web.utils import (
    load_config,
    queued_collection_logs_multi,
    resolve_collection_conferences,
    resolve_collection_tasks,
    resolve_limit,
    with_url_base,
)
from src.web.workers.collection import spawn_collection_worker

MAX_JOB_LOG_LINES = 500

jobs_bp = Blueprint("jobs", __name__)


def _store():
    return current_app.config["PAPERCOLLECT_JOB_STORE"]


def _config_path() -> str:
    return current_app.config["PAPERCOLLECT_CONFIG"]


def _url_base() -> str:
    return current_app.config["PAPERCOLLECT_URL_BASE"]


def _collection_lock() -> FileJobLock:
    return current_app.config["PAPERCOLLECT_COLLECTION_LOCK"]


@jobs_bp.route("/api/jobs", methods=["GET"])
def list_jobs() -> Response:
    jobs = _store().list(summary=True)
    return jsonify({"jobs": jobs})


@jobs_bp.route("/api/jobs/<job_id>", methods=["GET"])
def job_status(job_id: str) -> tuple[Response, int] | Response:
    job = _store().get(job_id)
    if not job:
        return jsonify({"error": "Job not found."}), 404
    queue = job.get("queue")
    if queue:
        job["task_summary"] = queue_task_summary(queue)
    return jsonify(job)


@jobs_bp.route("/api/jobs/<job_id>/stop", methods=["POST"])
def job_stop(job_id: str) -> tuple[Response, int] | Response:
    store = _store()
    job = store.get(job_id)
    if not job:
        return jsonify({"error": "Job not found."}), 404
    if job.get("type") != "collection":
        return jsonify({"error": "Only collection jobs can be stopped."}), 400
    if job.get("status") not in {"queued", "running"}:
        return jsonify({"error": "Collection job is not running.", "job": job}), 409

    if not job.get("cancel_requested"):
        store.update(job_id, cancel_requested=True)
        store.append_log(
            job_id,
            "Stop requested; collection will stop after the current conference.",
            max_lines=MAX_JOB_LOG_LINES,
        )
    updated = store.get(job_id) or job
    queue = updated.get("queue")
    if queue:
        updated["task_summary"] = queue_task_summary(queue)
    return jsonify(updated), 202


@jobs_bp.route("/api/jobs/<job_id>/resume", methods=["POST"])
def job_resume(job_id: str) -> tuple[Response, int] | Response:
    store = _store()
    lock = _collection_lock()
    job = store.get(job_id)
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

    if not lock.acquire(blocking=False):
        return jsonify({"error": "A collection job is already running."}), 409

    reset_skipped_tasks(queue)
    store.update(
        job_id,
        status="running",
        cancel_requested=False,
        queue=queue,
        error=None,
    )
    store.append_log(job_id, "Resuming collection.", max_lines=MAX_JOB_LOG_LINES)

    config = load_config(_config_path())
    output_dir = str(config.get("output_dir", "data"))
    threads = int(config.get("concurrency", {}).get("threads", 4))
    spawn_collection_worker(job_id, output_dir, threads, lock, app=current_app._get_current_object())

    from flask import url_for

    return jsonify(
        {
            "job_id": job_id,
            "status_url": with_url_base(
                url_for("jobs.job_status", job_id=job_id),
                _url_base(),
            ),
        }
    ), 202


@jobs_bp.route("/api/jobs/<job_id>/retry", methods=["POST"])
def job_retry(job_id: str) -> tuple[Response, int] | Response:
    store = _store()
    lock = _collection_lock()
    job = store.get(job_id)
    if not job:
        return jsonify({"error": "Job not found."}), 404
    if job.get("type") != "collection":
        return jsonify({"error": "Only collection jobs can be retried."}), 400
    if job.get("status") not in {"stopped", "failed", "completed"}:
        return jsonify({"error": "Job cannot be retried from its current state."}), 400

    queue = job.get("queue") or []
    if not has_retryable_tasks(queue):
        return jsonify({"error": "No failed tasks to retry."}), 400

    if not lock.acquire(blocking=False):
        return jsonify({"error": "A collection job is already running."}), 409

    reset_failed_and_skipped_tasks(queue)
    store.update(
        job_id,
        status="running",
        cancel_requested=False,
        queue=queue,
        error=None,
    )
    store.append_log(job_id, "Retrying failed tasks.", max_lines=MAX_JOB_LOG_LINES)

    config = load_config(_config_path())
    output_dir = str(config.get("output_dir", "data"))
    threads = int(config.get("concurrency", {}).get("threads", 4))
    spawn_collection_worker(job_id, output_dir, threads, lock, app=current_app._get_current_object())

    from flask import url_for

    return jsonify(
        {
            "job_id": job_id,
            "status_url": with_url_base(
                url_for("jobs.job_status", job_id=job_id),
                _url_base(),
            ),
        }
    ), 202


@jobs_bp.route("/api/jobs/<job_id>/queue/<task_id>/retry", methods=["POST"])
def task_retry(job_id: str, task_id: str) -> tuple[Response, int] | Response:
    store = _store()
    lock = _collection_lock()
    job = store.get(job_id)
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
    store.update(job_id, queue=queue)
    store.append_log(
        job_id,
        f"Retrying task {task_id} ({target['display_name']}).",
        max_lines=MAX_JOB_LOG_LINES,
    )

    needs_worker = job.get("status") not in {"running", "queued"}
    if needs_worker:
        if not lock.acquire(blocking=False):
            return jsonify({"error": "A collection job is already running."}), 409
        store.update(job_id, status="running", cancel_requested=False)
        config = load_config(_config_path())
        output_dir = str(config.get("output_dir", "data"))
        threads = int(config.get("concurrency", {}).get("threads", 4))
        spawn_collection_worker(job_id, output_dir, threads, lock, app=current_app._get_current_object())

    updated = store.get(job_id) or job
    queue = updated.get("queue")
    if queue:
        updated["task_summary"] = queue_task_summary(queue)
    return jsonify(updated), 202


@jobs_bp.route("/api/jobs/<job_id>", methods=["DELETE"])
def job_delete(job_id: str) -> tuple[Response, int] | Response:
    store = _store()
    job = store.get(job_id)
    if not job:
        return jsonify({"error": "Job not found."}), 404
    if job.get("status") in {"running", "queued"}:
        return jsonify({"error": "Cannot delete a running job. Stop it first."}), 409
    store.delete(job_id)
    return jsonify({"deleted": job_id}), 200


@jobs_bp.route("/api/collect", methods=["POST"])
def collect() -> tuple[Response, int] | Response:
    store = _store()
    lock = _collection_lock()
    config_path = _config_path()
    payload = request.get_json(silent=True) or {}
    config = load_config(config_path)

    explicit_tasks, task_error = resolve_collection_tasks(payload, config)
    if task_error:
        return jsonify({"error": task_error}), 400

    if explicit_tasks is not None:
        conferences = []
        seen_conferences = set()
        years = []
        seen_years = set()
        for conference, year in explicit_tasks:
            if conference.id not in seen_conferences:
                conferences.append(conference)
                seen_conferences.add(conference.id)
            if year not in seen_years:
                years.append(year)
                seen_years.add(year)
        queue = build_queue_items_for_tasks(explicit_tasks)
    else:
        conferences, validation_error = resolve_collection_conferences(payload, config)
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
        queue = build_queue_items(conferences, years)

    try:
        limit = resolve_limit(payload.get("limit"), config)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if not lock.acquire(blocking=False):
        return jsonify({"error": "A collection job is already running."}), 409

    output_dir = str(config.get("output_dir", "data"))
    threads = int(config.get("concurrency", {}).get("threads", 4))

    total_tasks = len(queue)
    single_task = total_tasks == 1
    first = queue[0] if queue else {}
    job = store.create(
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
            "logs": queued_collection_logs_multi(conferences, years, total_tasks),
            "paper_count": None,
            "feed_url": None,
            "feed_urls": [],
            "cancel_requested": False,
            "stopped_count": 0,
            "queue": queue,
        }
    )

    spawn_collection_worker(job["id"], output_dir, threads, lock, app=current_app._get_current_object())

    from flask import url_for

    return jsonify(
        {
            "job_id": job["id"],
            "status_url": with_url_base(
                url_for("jobs.job_status", job_id=job["id"]),
                _url_base(),
            ),
        }
    ), 202
