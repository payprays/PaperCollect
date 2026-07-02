import json
import re
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml
from werkzeug.serving import make_server

from main import get_output_path
from src.web import create_app

playwright_sync_api = pytest.importorskip("playwright.sync_api")
Error = playwright_sync_api.Error
expect = playwright_sync_api.expect
sync_playwright = playwright_sync_api.sync_playwright


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Error as exc:
            pytest.skip(f"Playwright Chromium browser is not installed: {exc}")
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    context = browser.new_context()
    page = context.new_page()
    yield page
    context.close()


@contextmanager
def live_server(config_path: Path):
    app = create_app(str(config_path))
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def write_config(tmp_path, *, webdav=False):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    config = {
        "include_ccfddl_catalog": False,
        "conferences": [
            {
                "id": "icse",
                "display_name": "ICSE",
                "dblp_stream": "conf/icse",
                "category": "SE",
                "category_name": "Software Engineering",
                "tier": {"ccf": "A"},
                "focus_tags": ["software_engineering"],
            },
            {
                "id": "fse",
                "display_name": "FSE",
                "dblp_stream": "conf/sigsoft",
                "category": "SE",
                "category_name": "Software Engineering",
                "tier": {"ccf": "B"},
                "focus_tags": ["software_engineering"],
            },
            {
                "id": "ndss",
                "display_name": "NDSS",
                "dblp_stream": "conf/ndss",
                "category": "SC",
                "category_name": "Security",
                "tier": {"ccf": "A"},
                "focus_tags": ["security", "cloud_native"],
            },
        ],
        "years": [2024, 2025],
        "output_dir": str(data_dir),
        "job_store_dir": str(data_dir / "jobs"),
        "limit_per_conference": 1,
        "concurrency": {"threads": 1},
        "vector_index": {"collection": "ui_test_papers"},
    }
    if webdav:
        config["webdav"] = {
            "url": "https://webdav.example.test/",
            "username": "tester",
            "password": "secret",
            "remote_path": "/papers",
        }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return config_path, data_dir


def write_paper(data_dir: Path, filename: str, title: str, *, venue="ICSE", year=2025):
    (data_dir / filename).write_text(
        json.dumps(
            [
                {
                    "title": title,
                    "authors": ["A. Researcher"],
                    "venue": venue,
                    "year": year,
                    "abstract": f"{title} abstract.",
                    "url": f"https://example.test/{filename}",
                }
            ]
        ),
        encoding="utf-8",
    )


def patch_fast_collection(monkeypatch, data_dir: Path):
    def fake_process_conference_year(conf, year, dblp_client, metadata_manager, output_dir, limit):
        output_path = get_output_path(output_dir, conf, year)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(
                [
                    {
                        "title": f"{conf.display_name} UI Paper {year}",
                        "authors": ["A. Researcher"],
                        "venue": conf.display_name,
                        "year": year,
                        "abstract": "Collected through the UI test.",
                        "url": f"https://example.test/{conf.id}/{year}",
                    }
                ],
                f,
            )

    monkeypatch.setattr("src.web.workers.collection.process_conference_year", fake_process_conference_year)


def patch_fast_index(monkeypatch):
    def fake_run_index_job(job_id, config, config_path, force, active_lock, app=None):
        store = app.config["PAPERCOLLECT_JOB_STORE"]
        try:
            store.update(job_id, status="running")
            store.append_log(job_id, "mock index completed", max_lines=500)
            store.update(
                job_id,
                status="completed",
                paper_count=2,
                source_count=2,
                backend="qdrant",
                collection=config["vector_index"]["collection"],
                result={
                    "indexed": True,
                    "paper_count": 2,
                    "source_count": 2,
                    "backend": "qdrant",
                    "collection": config["vector_index"]["collection"],
                },
            )
        finally:
            active_lock.release()

    monkeypatch.setattr("src.web.blueprints.index.run_index_job", fake_run_index_job)


def patch_fast_sync(monkeypatch):
    class DummySession:
        def head(self, url, timeout):
            class Response:
                status_code = 200
            return Response()

    class DummyWebDAVClient:
        def __init__(self, url, username, password, verify_ssl=True):
            self.session = DummySession()

    def fake_sync_status(client, output_dir, remote_path, timeout=10):
        return {
            "local_only": ["icse_2025.json"],
            "remote_only": ["ndss_2025.json"],
            "both": ["fse_2025.json"],
            "remote_files": [
                {"name": "fse_2025.json", "size": 10, "modified": "today"},
                {"name": "ndss_2025.json", "size": 20, "modified": "today"},
            ],
        }

    def fake_run_sync_upload_job(job_id, webdav_config, output_dir, remote_path, active_lock, app=None):
        store = app.config["PAPERCOLLECT_JOB_STORE"]
        try:
            store.update(job_id, status="running")
            store.append_log(job_id, "mock upload completed", max_lines=500)
            store.update(job_id, status="completed", result={"uploaded": ["icse_2025.json"], "skipped": [], "errors": []})
        finally:
            active_lock.release()

    monkeypatch.setattr("src.web.blueprints.sync.WebDAVClient", DummyWebDAVClient)
    monkeypatch.setattr("src.web.blueprints.sync.sync_status", fake_sync_status)
    monkeypatch.setattr("src.web.blueprints.sync.run_sync_upload_job", fake_run_sync_upload_job)


def test_collect_filters_year_progress_preview_and_validation(page, tmp_path):
    config_path, data_dir = write_config(tmp_path)
    write_paper(data_dir, "icse_2024.json", "Saved ICSE Paper", year=2024)

    with live_server(config_path) as base_url:
        page.goto(base_url)
        expect(page.locator("#conference-picker input[value='icse']")).to_be_visible()
        expect(page.locator("#year-select-missing")).to_have_count(0)
        page.check("#conference-picker input[value='ndss']")

        page.select_option("#collect-category", "SE")
        page.select_option("#collect-ccf", "A")
        expect(page.locator("#conference-picker")).to_contain_text("ICSE")
        expect(page.locator("#conference-picker")).not_to_contain_text("FSE")
        expect(page.locator("#conference-picker")).not_to_contain_text("NDSS")

        page.click("#collect-select-visible")
        expect(page.locator(".year-checkbox[value='2024']")).to_be_checked()
        expect(page.locator(".year-checkbox[value='2025']")).to_be_checked()
        expect(page.locator("#conference-count")).to_contain_text("1 selected · 1 visible")
        expect(page.locator("#collect-preview")).to_contain_text("1 conference × 2 tasks")
        expect(page.locator("#collect-preview")).to_contain_text("ICSE")
        expect(page.locator("#collect-preview")).to_contain_text("2024, 2025")
        expect(page.locator("#collect-preview")).not_to_contain_text("NDSS")
        page.click("#collect-select-missing-years")
        expect(page.locator(".year-checkbox[value='2024']")).not_to_be_checked()
        expect(page.locator(".year-checkbox[value='2025']")).to_be_checked()
        expect(page.locator("#collect-preview")).to_contain_text("1 conference × 1 missing task")

        page.fill("#custom-year-input", "2026")
        page.click("#custom-year-add")
        expect(page.locator("#collect-preview")).to_contain_text("1 conference × 2 tasks")

        page.click("#collect-clear-visible")
        page.click("#collect-button")
        expect(page.locator("#status")).to_contain_text("Choose at least one conference")


def test_collection_flow_updates_queue_feeds_and_history(page, tmp_path, monkeypatch):
    config_path, data_dir = write_config(tmp_path)
    write_paper(data_dir, "icse_2024.json", "Saved ICSE Paper", year=2024)
    patch_fast_collection(monkeypatch, data_dir)

    with live_server(config_path) as base_url:
        page.goto(base_url)
        expect(page.locator("#conference-picker input[value='icse']")).to_be_visible()

        page.click("#collect-select-visible")
        page.click("#collect-select-missing-years")
        expect(page.locator("#collect-preview")).to_contain_text("3 conferences × 5 missing tasks")
        expect(page.locator("#collect-preview")).to_contain_text("ICSE")
        expect(page.locator("#collect-preview")).to_contain_text("2025")

        page.click("#collect-button")
        expect(page.locator("#status", has_text="Completed")).to_be_visible(timeout=15000)
        expect(page.locator("#task-queue .task-item[data-status='completed']")).to_have_count(5)
        expect(page.locator("#rss-link")).to_be_visible()
        expect(page.locator("#feeds")).to_contain_text("ICSE 2024")
        expect(page.locator("#feeds")).to_contain_text("NDSS 2025")
        expect(page.locator("#job-history")).to_contain_text("Completed")
        expect(page.locator("#job-history")).to_contain_text("5 done")


def test_search_tab_filters_index_job_and_persists_tab(page, tmp_path, monkeypatch):
    config_path, data_dir = write_config(tmp_path)
    write_paper(data_dir, "icse_2025.json", "Fuzzing Runtime APIs", venue="ICSE", year=2025)
    write_paper(data_dir, "fse_2025.json", "Fuzzing Compiler Pipelines", venue="FSE", year=2025)
    write_paper(data_dir, "ndss_2025.json", "Malware Sandbox Measurement", venue="NDSS", year=2025)
    patch_fast_index(monkeypatch)

    with live_server(config_path) as base_url:
        page.goto(base_url)
        page.click(".tab-btn[data-tab='search']")
        assert page.evaluate("localStorage.getItem('pc_active_tab')") == "search"

        page.fill("#search-query", "fuzzing")
        page.select_option("#search-mode", "keyword")
        page.select_option("#search-category", "SE")
        page.select_option("#search-ccf", "A")
        page.click("#search-select-visible")
        with page.expect_response(lambda response: "/api/search?" in response.url) as search_response:
            page.click("#search-form button[type='submit']")
        assert "conference=icse" in search_response.value.url
        expect(page.locator("#search-results")).to_contain_text("Fuzzing Runtime APIs")
        expect(page.locator("#search-results")).not_to_contain_text("Fuzzing Compiler Pipelines")

        page.click("#index-button")
        expect(page.locator("#index-status")).to_contain_text("Index ready", timeout=15000)
        expect(page.locator("#index-logs")).to_contain_text("mock index completed")

        page.reload()
        expect(page.locator(".tab-btn[data-tab='search']")).to_have_class(re.compile(".*active.*"))


def test_sync_tab_status_and_upload_job(page, tmp_path, monkeypatch):
    config_path, data_dir = write_config(tmp_path, webdav=True)
    write_paper(data_dir, "icse_2025.json", "Local ICSE Paper", venue="ICSE", year=2025)
    patch_fast_sync(monkeypatch)

    with live_server(config_path) as base_url:
        page.goto(base_url)
        page.click(".tab-btn[data-tab='sync']")
        expect(page.locator("#sync-status")).to_contain_text("Remote: 2 files")
        expect(page.locator("#sync-status")).to_contain_text("1 local-only")
        expect(page.locator("#sync-status")).to_contain_text("1 remote-only")

        page.click("#sync-upload-button")
        expect(page.locator("#sync-logs")).to_contain_text("mock upload completed", timeout=15000)
        expect(page.locator("#sync-upload-button")).to_be_enabled()
