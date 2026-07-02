import threading

import requests
from flask import Blueprint, Response, current_app, jsonify

from src.services.job_store import FileJobLock
from src.services.webdav_sync import (
    WebDAVClient,
    load_webdav_config,
    sync_download,
    sync_status,
    sync_upload,
)
from src.web.utils import load_config, with_url_base
from src.web.workers.sync_worker import run_sync_download_job, run_sync_upload_job

sync_bp = Blueprint("sync", __name__)


def _store():
    return current_app.config["PAPERCOLLECT_JOB_STORE"]


def _config_path() -> str:
    return current_app.config["PAPERCOLLECT_CONFIG"]


def _url_base() -> str:
    return current_app.config["PAPERCOLLECT_URL_BASE"]


def _sync_lock() -> FileJobLock:
    return current_app.config["PAPERCOLLECT_SYNC_LOCK"]


@sync_bp.route("/api/sync/status", methods=["GET"])
def sync_status_endpoint() -> tuple[Response, int] | Response:
    config = load_config(_config_path())
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


@sync_bp.route("/api/sync/upload", methods=["POST"])
def sync_upload_endpoint() -> tuple[Response, int] | Response:
    store = _store()
    lock = _sync_lock()
    config = load_config(_config_path())
    webdav_config = load_webdav_config(config)
    if not webdav_config:
        return jsonify({"error": "WebDAV is not configured."}), 503
    if not lock.acquire(blocking=False):
        return jsonify({"error": "A sync job is already running."}), 409
    output_dir = str(config.get("output_dir", "data"))
    remote_path = webdav_config.get("remote_path", "/")
    job = store.create(
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
        target=run_sync_upload_job,
        args=(job["id"], webdav_config, output_dir, remote_path, lock, current_app._get_current_object()),
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


@sync_bp.route("/api/sync/download", methods=["POST"])
def sync_download_endpoint() -> tuple[Response, int] | Response:
    store = _store()
    lock = _sync_lock()
    config = load_config(_config_path())
    webdav_config = load_webdav_config(config)
    if not webdav_config:
        return jsonify({"error": "WebDAV is not configured."}), 503
    if not lock.acquire(blocking=False):
        return jsonify({"error": "A sync job is already running."}), 409
    output_dir = str(config.get("output_dir", "data"))
    remote_path = webdav_config.get("remote_path", "/")
    job = store.create(
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
        target=run_sync_download_job,
        args=(job["id"], webdav_config, output_dir, remote_path, lock, current_app._get_current_object()),
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
