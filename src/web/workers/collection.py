import os
import threading
import time
from contextlib import redirect_stdout
from typing import Any

from main import get_output_path, process_conference_year
from src.clients.dblp_client import DBLPClient
from src.core.conference_catalog import ConferenceEntry, find_conference
from src.services.job_store import (
    FileJobLock,
    JobStore,
    mark_pending_tasks_skipped,
    queue_task_summary,
)
from src.services.metadata_manager import MetadataManager
from src.services.rss_service import load_papers
from src.web.utils import invalidate_output_cache, load_config


class _JobLogWriter:
    def __init__(self, append_line):
        self._append_line = append_line
        self._buffer = ""

    def write(self, value: str) -> int:
        if not value:
            return 0
        self._buffer += value
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                try:
                    self._append_line(line.rstrip())
                except RuntimeError:
                    # Thread pool workers may lack Flask app context; silently drop
                    pass
        return len(value)

    def flush(self) -> None:
        if self._buffer.strip():
            self._append_line(self._buffer.rstrip())
        self._buffer = ""

MAX_JOB_LOG_LINES = 500


def _get_store() -> JobStore:
    """Get job store from current app config."""
    from flask import current_app
    return current_app.config["PAPERCOLLECT_JOB_STORE"]


def _update_job(job_id: str, **updates: Any) -> None:
    _get_store().update(job_id, **updates)


def _append_job_log(job_id: str, message: str) -> None:
    _get_store().append_log(job_id, message, max_lines=MAX_JOB_LOG_LINES)


def _collection_cancel_requested(job_id: str) -> bool:
    job = _get_store().get(job_id) or {}
    return bool(job.get("cancel_requested"))


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
    output_paths = [r["output_path"] for r in results]
    if output_paths:
        invalidate_output_cache(os.path.dirname(output_paths[0]))
    _update_job(
        job_id,
        status="stopped",
        cancel_requested=True,
        paper_count=sum(r["paper_count"] for r in results),
        output_path=results[0]["output_path"] if len(results) == 1 else None,
        output_paths=output_paths,
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
    from urllib.parse import quote
    from flask import current_app
    from src.web.utils import with_url_base

    url_base = current_app.config["PAPERCOLLECT_URL_BASE"]
    encoded = quote(conference.id, safe="")
    return with_url_base(f"/feed/{encoded}/{year}.xml", url_base)


def spawn_collection_worker(
    job_id: str,
    output_dir: str,
    threads: int,
    active_lock: FileJobLock,
    app=None,
) -> None:
    thread = threading.Thread(
        target=run_collection_job,
        args=(job_id, output_dir, threads, active_lock, app),
        daemon=True,
    )
    thread.start()


def run_collection_job(
    job_id: str,
    output_dir: str,
    threads: int,
    active_lock: FileJobLock,
    app=None,
) -> None:
    if app is not None:
        with app.app_context():
            _run_collection_job_inner(job_id, output_dir, threads, active_lock)
    else:
        _run_collection_job_inner(job_id, output_dir, threads, active_lock)


def _run_collection_job_inner(
    job_id: str,
    output_dir: str,
    threads: int,
    active_lock: FileJobLock,
) -> None:
    from flask import current_app

    store = _get_store()
    job = store.get(job_id) or {}
    limit = int(job["limit"])
    conference_ids = job.get("conferences") or []
    _update_job(job_id, status="running")
    queue: list[dict[str, Any]] = job.get("queue") or []
    total = len(queue)
    try:
        os.makedirs(output_dir, exist_ok=True)

        config_path = current_app.config["PAPERCOLLECT_CONFIG"]
        config = load_config(config_path)
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
                invalidate_output_cache(output_dir)

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
