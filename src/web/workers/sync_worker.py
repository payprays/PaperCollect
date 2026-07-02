from typing import Any

from src.services.job_store import FileJobLock
from src.services.webdav_sync import (
    WebDAVClient,
    sync_download,
    sync_upload,
)

MAX_JOB_LOG_LINES = 500


def _get_store():
    """Get job store from current app config."""
    from flask import current_app
    return current_app.config["PAPERCOLLECT_JOB_STORE"]


def _update_job(job_id: str, **updates: Any) -> None:
    _get_store().update(job_id, **updates)


def _append_job_log(job_id: str, message: str) -> None:
    _get_store().append_log(job_id, message, max_lines=MAX_JOB_LOG_LINES)


def run_sync_upload_job(
    job_id: str,
    webdav_config: dict[str, str],
    output_dir: str,
    remote_path: str,
    active_lock: FileJobLock,
    app=None,
) -> None:
    if app is not None:
        with app.app_context():
            _run_sync_upload_job_inner(job_id, webdav_config, output_dir, remote_path, active_lock)
    else:
        _run_sync_upload_job_inner(job_id, webdav_config, output_dir, remote_path, active_lock)


def _run_sync_upload_job_inner(
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


def run_sync_download_job(
    job_id: str,
    webdav_config: dict[str, str],
    output_dir: str,
    remote_path: str,
    active_lock: FileJobLock,
    app=None,
) -> None:
    if app is not None:
        with app.app_context():
            _run_sync_download_job_inner(job_id, webdav_config, output_dir, remote_path, active_lock)
    else:
        _run_sync_download_job_inner(job_id, webdav_config, output_dir, remote_path, active_lock)


def _run_sync_download_job_inner(
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
