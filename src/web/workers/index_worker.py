import os
from typing import Any

from src.services.job_store import FileJobLock
from src.services.vector_index import vector_index_status
from src.web.utils import index_command, run_index_subprocess

MAX_JOB_LOG_LINES = 500


def _get_store():
    """Get job store from current app config."""
    from flask import current_app
    return current_app.config["PAPERCOLLECT_JOB_STORE"]


def _update_job(job_id: str, **updates: Any) -> None:
    _get_store().update(job_id, **updates)


def _append_job_log(job_id: str, message: str) -> None:
    _get_store().append_log(job_id, message, max_lines=MAX_JOB_LOG_LINES)


def run_index_job(
    job_id: str,
    config: dict[str, Any],
    config_path: str,
    force: bool,
    active_lock: FileJobLock,
    app=None,
) -> None:
    if app is not None:
        with app.app_context():
            _run_index_job_inner(job_id, config, config_path, force, active_lock)
    else:
        _run_index_job_inner(job_id, config, config_path, force, active_lock)


def _run_index_job_inner(
    job_id: str,
    config: dict[str, Any],
    config_path: str,
    force: bool,
    active_lock: FileJobLock,
) -> None:
    try:
        _update_job(job_id, status="running")
        command = index_command(config_path, force=force)
        _append_job_log(job_id, f"Starting index subprocess: {' '.join(command)}")
        returncode = run_index_subprocess(
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
