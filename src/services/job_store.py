import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _path_lock(path: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(path)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[path] = lock
        return lock


class JobStore:
    """Small JSON-backed job store for web jobs that must survive multi-worker reads."""

    def __init__(self, path: str) -> None:
        self.path = path
        os.makedirs(self.path, exist_ok=True)

    def create(self, values: dict[str, Any]) -> dict[str, Any]:
        job_id = uuid.uuid4().hex[:12]
        now = time.time()
        job = {
            "id": job_id,
            "created_at": now,
            "updated_at": now,
            **values,
        }
        self._write(job)
        return job

    def get(self, job_id: str) -> dict[str, Any] | None:
        try:
            with open(self._job_path(job_id), "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def update(self, job_id: str, **updates: Any) -> dict[str, Any]:
        lock = _path_lock(self._job_path(job_id))
        with lock:
            job = self.get(job_id) or {"id": job_id, "created_at": time.time()}
            job.update(updates)
            job["updated_at"] = time.time()
            self._write(job)
            return job

    def append_log(self, job_id: str, message: str, *, max_lines: int) -> dict[str, Any]:
        lock = _path_lock(self._job_path(job_id))
        with lock:
            job = self.get(job_id) or {"id": job_id, "created_at": time.time()}
            logs = list(job.get("logs") or [])
            logs.append(message)
            if len(logs) > max_lines:
                del logs[:-max_lines]
            job["logs"] = logs
            job["updated_at"] = time.time()
            self._write(job)
            return job

    def list(self, *, summary: bool = False) -> list[dict[str, Any]]:
        """List all jobs, sorted by created_at descending.

        When *summary* is True, omit large fields (queue, logs, results, errors).
        """
        jobs: list[dict[str, Any]] = []
        try:
            entries = os.listdir(self.path)
        except OSError:
            return jobs
        for name in entries:
            if not name.endswith(".json"):
                continue
            job_id = name[:-5]
            job = self.get(job_id)
            if not isinstance(job, dict):
                continue
            if summary:
                job = _extract_summary(job)
            jobs.append(job)
        jobs.sort(key=lambda j: j.get("created_at", 0), reverse=True)
        return jobs

    def delete(self, job_id: str) -> bool:
        """Delete a job file. Returns True if deleted, False if not found."""
        path = self._job_path(job_id)
        lock = _path_lock(path)
        with lock:
            try:
                os.unlink(path)
                return True
            except FileNotFoundError:
                return False

    def _job_path(self, job_id: str) -> str:
        normalized = "".join(char for char in str(job_id) if char.isalnum() or char in {"-", "_"})
        if not normalized:
            raise ValueError("Invalid job id.")
        return os.path.join(self.path, f"{normalized}.json")

    def _write(self, job: dict[str, Any]) -> None:
        os.makedirs(self.path, exist_ok=True)
        path = self._job_path(str(job["id"]))
        temp_path = f"{path}.tmp.{os.getpid()}.{threading.get_ident()}"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(job, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(temp_path, path)


@dataclass
class FileJobLock:
    path: str
    kind: str
    stale_after_seconds: int = 6 * 60 * 60
    _owned: bool = False

    def acquire(self, *, blocking: bool = False) -> bool:
        if blocking:
            while not self.acquire(blocking=False):
                time.sleep(0.2)
            return True

        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._clear_stale_lock()
        payload = {
            "kind": self.kind,
            "pid": os.getpid(),
            "created_at": time.time(),
        }
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            return False
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        self._owned = True
        return True

    def release(self) -> None:
        if not self._owned:
            return
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
        finally:
            self._owned = False

    def _clear_stale_lock(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return

        pid = int(payload.get("pid") or 0)
        created_at = float(payload.get("created_at") or 0)
        expired = created_at > 0 and time.time() - created_at > self.stale_after_seconds
        if (pid and not _pid_alive(pid)) or expired:
            try:
                os.unlink(self.path)
            except FileNotFoundError:
                pass


def _extract_summary(job: dict[str, Any]) -> dict[str, Any]:
    """Return a lightweight summary of a job, omitting queue/logs/results/errors."""
    summary: dict[str, Any] = {
        "id": job.get("id"),
        "type": job.get("type"),
        "status": job.get("status"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "conference_ids": job.get("conference_ids"),
        "years": job.get("years"),
        "paper_count": job.get("paper_count"),
    }
    queue = job.get("queue")
    if queue:
        summary["task_summary"] = queue_task_summary(queue)
        summary["task_count"] = len(queue)
    return summary


def build_queue_items(conferences: list, years: list[int] | None = None) -> list[dict[str, Any]]:
    """Build queue items from a list of ConferenceEntry objects.

    When *years* is provided, one queue item is created for each
    conference x year combination.  Otherwise a single item per
    conference is produced (legacy single-year behaviour).
    """
    if not years:
        years = []
    items: list[dict[str, Any]] = []
    for conference in conferences:
        for year in years:
            items.append(
                {
                    "task_id": uuid.uuid4().hex[:8],
                    "conference_id": conference.id,
                    "display_name": conference.display_name,
                    "year": year,
                    "status": "pending",
                    "paper_count": None,
                    "output_path": None,
                    "feed_url": None,
                    "error": None,
                    "started_at": None,
                    "finished_at": None,
                }
            )
    return items


def queue_task_summary(queue: list[dict[str, Any]]) -> dict[str, int]:
    """Count tasks by status."""
    summary: dict[str, int] = {
        "pending": 0,
        "running": 0,
        "completed": 0,
        "failed": 0,
        "skipped": 0,
    }
    for item in queue:
        status = item.get("status", "pending")
        if status in summary:
            summary[status] += 1
    return summary


def reset_skipped_tasks(queue: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reset skipped tasks to pending for resume."""
    for item in queue:
        if item["status"] == "skipped":
            item["status"] = "pending"
    return queue


def reset_failed_and_skipped_tasks(queue: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reset failed and skipped tasks to pending for retry."""
    for item in queue:
        if item["status"] in ("failed", "skipped"):
            item["status"] = "pending"
    return queue


def mark_pending_tasks_skipped(queue: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mark all pending tasks as skipped (used when stopping)."""
    for item in queue:
        if item["status"] == "pending":
            item["status"] = "skipped"
    return queue


def has_retryable_tasks(queue: list[dict[str, Any]]) -> bool:
    """Check if any tasks are in a retryable state."""
    return any(item.get("status") in ("failed", "skipped") for item in queue)


def has_resumable_tasks(queue: list[dict[str, Any]]) -> bool:
    """Check if any tasks are in a resumable state."""
    return any(item.get("status") in ("pending", "failed", "skipped") for item in queue)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
