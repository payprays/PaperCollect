import os
import time
from typing import Any, Callable

from flask import Flask, Response, render_template, url_for

from src.core.conference_catalog import (
    configured_years,
    normalize_conferences,
)
from src.services.job_store import FileJobLock, JobStore
from src.services.rss_service import count_papers
from src.web.utils import (
    feeds_cache,
    job_store_dir,
    load_config,
    normalize_url_base,
    prefix_rule,
    saved_years_for_conference,
    with_url_base,
)


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
    initial_config = load_config(config_path)
    url_base = normalize_url_base(
        initial_config.get("url_base") or initial_config.get("base_path")
    )
    app.config["PAPERCOLLECT_URL_BASE"] = url_base

    job_store = JobStore(job_store_dir(initial_config))
    app.config["PAPERCOLLECT_JOB_STORE"] = job_store
    collection_lock = FileJobLock(os.path.join(job_store.path, "collection.lock"), "collection")
    index_lock = FileJobLock(os.path.join(job_store.path, "index.lock"), "index")
    sync_lock = FileJobLock(os.path.join(job_store.path, "sync.lock"), "sync")
    app.config["PAPERCOLLECT_COLLECTION_LOCK"] = collection_lock
    app.config["PAPERCOLLECT_INDEX_LOCK"] = index_lock
    app.config["PAPERCOLLECT_SYNC_LOCK"] = sync_lock

    def route(rule: str, **options: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            app.route(rule, **options)(func)
            if url_base:
                app.route(prefix_rule(url_base, rule), **options)(func)
                if rule == "/":
                    app.route(url_base, **options)(func)
            return func

        return decorator

    @app.context_processor
    def template_globals() -> dict[str, Any]:
        return {
            "url_base": url_base,
            "asset_url": lambda filename: with_url_base(
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

    # Register blueprints
    from src.web.blueprints.config import config_bp
    from src.web.blueprints.feeds import feeds_bp
    from src.web.blueprints.index import index_bp
    from src.web.blueprints.jobs import jobs_bp
    from src.web.blueprints.queue import queue_bp
    from src.web.blueprints.search import search_bp
    from src.web.blueprints.sync import sync_bp

    for bp in [config_bp, jobs_bp, queue_bp, search_bp, feeds_bp, index_bp, sync_bp]:
        app.register_blueprint(bp)

    # Mount app at url_base prefix so all routes are accessible under both / and /prefix/.
    if url_base:
        from werkzeug.middleware.dispatcher import DispatcherMiddleware

        app.wsgi_app = DispatcherMiddleware(
            app.wsgi_app,
            {url_base: app.wsgi_app},
        )

    # Pre-warm caches in background on startup.
    def _prewarm() -> None:
        import threading as _threading

        def _do() -> None:
            try:
                time.sleep(0.5)
                cfg = load_config(config_path)
                out = str(cfg.get("output_dir", "data"))
                _cache = feeds_cache()
                # Warm feeds cache
                all_feeds = []
                for conf in normalize_conferences(cfg):
                    yrs = sorted(
                        {int(y) for y in configured_years(cfg, conf)}
                        | saved_years_for_conference(out, conf)
                    )
                    for yr in yrs:
                        pc = count_papers(out, conf.id, yr, aliases=[conf.display_name, *conf.aliases])
                        if pc:
                            all_feeds.append({
                                "conference": conf.id, "display_name": conf.display_name,
                                "year": yr, "paper_count": pc,
                                "feed_url": _feed_url_prewarm(conf, yr, url_base),
                            })
                _cache[out] = (time.time(), {"feeds": all_feeds})
                # Warm year-progress cache
                default_years = [int(y) for y in cfg.get("years", [])]
                progress = []
                for conf in normalize_conferences(cfg):
                    conf_years = list(conf.years) if conf.years else default_years
                    saved = saved_years_for_conference(out, conf)
                    progress.append({
                        "conference_id": conf.id, "display_name": conf.display_name,
                        "category": conf.category,
                        "ccf": (conf.tier.get("ccf") or "").strip().upper() or None,
                        "configured_years": [int(y) for y in conf_years],
                        "saved_years": sorted(saved),
                        "missing_years": sorted(set(int(y) for y in conf_years) - saved),
                    })
                _cache[f"yp:{out}"] = (time.time(), {"progress": progress})
            except Exception:
                pass

        _threading.Thread(target=_do, daemon=True).start()

    _prewarm()

    return app


def _feed_url_prewarm(conference, year: int, url_base: str) -> str:
    from urllib.parse import quote
    encoded = quote(conference.id, safe="")
    return with_url_base(f"/feed/{encoded}/{year}.xml", url_base)
