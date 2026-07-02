import threading

from flask import Blueprint, Response, current_app, jsonify, request

from src.services.job_store import FileJobLock
from src.services.vector_index import VectorIndexError, vector_index_status
from src.web.utils import load_config, optional_bool, with_url_base
from src.web.workers.index_worker import run_index_job

MAX_JOB_LOG_LINES = 500

index_bp = Blueprint("index", __name__)


def _store():
    return current_app.config["PAPERCOLLECT_JOB_STORE"]


def _config_path() -> str:
    return current_app.config["PAPERCOLLECT_CONFIG"]


def _url_base() -> str:
    return current_app.config["PAPERCOLLECT_URL_BASE"]


def _index_lock() -> FileJobLock:
    return current_app.config["PAPERCOLLECT_INDEX_LOCK"]


@index_bp.route("/api/index/status", methods=["GET"])
def index_status() -> tuple[Response, int] | Response:
    config = load_config(_config_path())
    try:
        return jsonify(vector_index_status(config))
    except (VectorIndexError, OSError, RuntimeError, ValueError) as exc:
        return jsonify({"error": str(exc), "indexed": False}), 503


@index_bp.route("/api/index", methods=["POST"])
def index_build() -> tuple[Response, int] | Response:
    store = _store()
    lock = _index_lock()
    payload = request.get_json(silent=True) or {}
    config = load_config(_config_path())
    try:
        force = optional_bool(payload.get("force"), default=True)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if not lock.acquire(blocking=False):
        return jsonify({"error": "A vector index job is already running."}), 409

    output_dir = str(config.get("output_dir", "data"))
    index_config = dict(config.get("vector_index") or {})
    collection = str(index_config.get("collection") or "papercollect_papers")
    job = store.create(
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
        target=run_index_job,
        args=(job["id"], config, _config_path(), force, lock, current_app._get_current_object()),
        daemon=True,
    )
    thread.start()

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
