from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request

from src.core.conference_catalog import find_conference
from src.services.job_store import queue_task_summary
from src.web.utils import load_config

MAX_JOB_LOG_LINES = 500

queue_bp = Blueprint("queue", __name__)


def _store():
    return current_app.config["PAPERCOLLECT_JOB_STORE"]


def _config_path() -> str:
    return current_app.config["PAPERCOLLECT_CONFIG"]


@queue_bp.route("/api/jobs/<job_id>/queue", methods=["POST"])
def queue_add_task(job_id: str) -> tuple[Response, int] | Response:
    store = _store()
    job = store.get(job_id)
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

    config = load_config(_config_path())
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
    store.update(job_id, queue=queue)
    store.append_log(
        job_id,
        f"Added task: {conference.display_name} {year}",
        max_lines=MAX_JOB_LOG_LINES,
    )
    updated = store.get(job_id) or job
    updated["task_summary"] = queue_task_summary(updated.get("queue") or [])
    return jsonify(updated), 201


@queue_bp.route("/api/jobs/<job_id>/queue/<task_id>", methods=["DELETE"])
def queue_remove_task(job_id: str, task_id: str) -> tuple[Response, int] | Response:
    store = _store()
    job = store.get(job_id)
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
    store.update(job_id, queue=queue)
    store.append_log(
        job_id,
        f"Removed task: {target['display_name']} {target['year']}",
        max_lines=MAX_JOB_LOG_LINES,
    )
    updated = store.get(job_id) or job
    updated["task_summary"] = queue_task_summary(updated.get("queue") or [])
    return jsonify(updated), 200


@queue_bp.route("/api/jobs/<job_id>/queue/reorder", methods=["POST"])
def queue_reorder(job_id: str) -> tuple[Response, int] | Response:
    store = _store()
    job = store.get(job_id)
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
    store.update(job_id, queue=reordered)
    updated = store.get(job_id) or job
    updated["task_summary"] = queue_task_summary(updated.get("queue") or [])
    return jsonify(updated), 200
