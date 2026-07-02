import os
import subprocess
import sys
import time
from typing import Any, Callable

import yaml

from src.core.conference_catalog import ConferenceEntry

_CONFIG_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_FEEDS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL = 30  # seconds — config rarely changes


def load_config(config_path: str) -> dict[str, Any]:
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


def index_command(config_path: str, *, force: bool) -> list[str]:
    command = [sys.executable, "-m", "index_papers", "--config", config_path]
    if not force:
        command.append("--no-force")
    return command


def run_index_subprocess(
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


def job_store_dir(config: dict[str, Any]) -> str:
    configured = config.get("job_store_dir")
    if configured:
        return str(configured)
    output_dir = str(config.get("output_dir", "data"))
    return os.path.join(output_dir, "jobs")


def normalize_url_base(value: Any) -> str:
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


def with_url_base(path: str, url_base: str) -> str:
    if not url_base:
        return path
    if not path.startswith("/"):
        path = f"/{path}"
    if path == url_base or path.startswith(f"{url_base}/"):
        return path
    return f"{url_base}{path}"


def prefix_rule(url_base: str, rule: str) -> str:
    if rule == "/":
        return f"{url_base}/"
    return with_url_base(rule, url_base)


def queued_collection_logs_multi(
    conferences: list[ConferenceEntry],
    years: list[int],
    total_tasks: int,
) -> list[str]:
    year_str = ", ".join(str(y) for y in years)
    return [
        f"Queued {total_tasks} collection tasks for {len(conferences)} conferences across {len(years)} year(s) ({year_str}).",
        "RSS feeds will be available as each task completes.",
    ]


def resolve_collection_conferences(
    payload: dict[str, Any],
    config: dict[str, Any],
) -> tuple[list[ConferenceEntry], str | None]:
    from src.core.conference_catalog import find_conference

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


def resolve_collection_tasks(
    payload: dict[str, Any],
    config: dict[str, Any],
) -> tuple[list[tuple[ConferenceEntry, int]] | None, str | None]:
    raw_tasks = payload.get("tasks")
    if raw_tasks is None:
        return None, None
    if not isinstance(raw_tasks, list):
        return [], "Choose valid collection tasks."

    from src.core.conference_catalog import find_conference, valid_collection_year

    tasks: list[tuple[ConferenceEntry, int]] = []
    seen: set[tuple[str, int]] = set()
    for raw_task in raw_tasks:
        if not isinstance(raw_task, dict):
            return [], "Choose valid collection tasks."
        raw_conference = raw_task.get("conference") or raw_task.get("conference_id")
        if raw_conference in (None, ""):
            return [], "Choose conferences from config.yaml."
        conference = find_conference(config, str(raw_conference))
        if conference is None:
            return [], "Choose conferences from config.yaml."
        try:
            year = int(raw_task["year"])
        except (KeyError, TypeError, ValueError):
            return [], "Choose valid years."
        if not valid_collection_year(year):
            return [], "Choose a year between 1900 and two years from now."
        key = (conference.id, year)
        if key in seen:
            continue
        tasks.append((conference, year))
        seen.add(key)

    if not tasks:
        return [], "Choose at least one collection task."
    return tasks, None


def resolve_limit(value: Any, config: dict[str, Any]) -> int:
    if value in (None, ""):
        return int(config.get("limit_per_conference", 0))

    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Limit must be a non-negative integer.") from exc

    if limit < 0:
        raise ValueError("Limit must be a non-negative integer.")
    return limit


def optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def optional_bool(value: Any, *, default: bool) -> bool:
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


def request_list_args(*names: str) -> list[str]:
    from flask import request

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


def normalize_optional_text(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    return text or None


def known_ccf_tiers(config: dict[str, Any]) -> set[str]:
    from src.core.conference_catalog import normalize_conferences

    tiers = set()
    for entry in normalize_conferences(config):
        value = normalize_optional_text(entry.tier.get("ccf"))
        if value:
            tiers.add(value)
    return tiers


def saved_years_for_conference(output_dir: str, conference: ConferenceEntry) -> set[int]:
    from main import get_output_path

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


def feeds_cache() -> dict[str, tuple[float, dict[str, Any]]]:
    return _FEEDS_CACHE


def invalidate_output_cache(output_dir: str) -> None:
    cache = feeds_cache()
    output_key = str(output_dir)
    year_prefix = f"yp:{output_key}"
    for key in list(cache):
        if key == output_key or key == year_prefix or key.startswith(f"{year_prefix}:"):
            cache.pop(key, None)


def cache_ttl() -> int:
    return _CACHE_TTL
