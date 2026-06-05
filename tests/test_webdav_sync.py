import json
import os
import threading
import time
from unittest.mock import patch

import yaml

from src.services.webdav_sync import (
    WebDAVClient,
    load_webdav_config,
    sync_download,
    sync_status,
    sync_upload,
)
from src.web import create_app


# --- load_webdav_config tests ---


def test_load_webdav_config_returns_none_when_no_url():
    with patch.dict(os.environ, {}, clear=True):
        # Remove any WEBDAV_* keys that might be in the real env
        env_clean = {k: v for k, v in os.environ.items() if not k.startswith("WEBDAV_")}
        with patch.dict(os.environ, env_clean, clear=True):
            assert load_webdav_config({}) is None
            assert load_webdav_config({"webdav": {"url": ""}}) is None
            assert load_webdav_config({"webdav": None}) is None


def test_load_webdav_config_reads_from_config(monkeypatch):
    monkeypatch.delenv("WEBDAV_URL", raising=False)
    monkeypatch.delenv("WEBDAV_USERNAME", raising=False)
    monkeypatch.delenv("WEBDAV_PASSWORD", raising=False)
    config = {
        "webdav": {
            "url": "https://dav.example.com/remote.php/dav/files/user/",
            "username": "user",
            "password": "pass",
            "remote_path": "/papers/",
        }
    }
    result = load_webdav_config(config)
    assert result is not None
    assert result["url"] == "https://dav.example.com/remote.php/dav/files/user/"
    assert result["username"] == "user"
    assert result["password"] == "pass"
    assert result["remote_path"] == "/papers/"


def test_load_webdav_config_env_overrides_config(monkeypatch):
    config = {
        "webdav": {
            "url": "https://from-config.example.com/",
            "username": "config_user",
            "password": "config_pass",
        }
    }
    monkeypatch.setenv("WEBDAV_URL", "https://from-env.example.com/")
    monkeypatch.setenv("WEBDAV_USERNAME", "env_user")
    monkeypatch.setenv("WEBDAV_PASSWORD", "env_pass")

    result = load_webdav_config(config)
    assert result["url"] == "https://from-env.example.com/"
    assert result["username"] == "env_user"
    assert result["password"] == "env_pass"


def test_load_webdav_config_env_only(monkeypatch):
    monkeypatch.setenv("WEBDAV_URL", "https://env-only.example.com/")
    monkeypatch.delenv("WEBDAV_USERNAME", raising=False)
    monkeypatch.delenv("WEBDAV_PASSWORD", raising=False)
    result = load_webdav_config({})
    assert result is not None
    assert result["url"] == "https://env-only.example.com/"
    assert result["username"] == ""
    assert result["password"] == ""


def test_load_webdav_config_default_remote_path():
    config = {"webdav": {"url": "https://example.com/dav/"}}
    result = load_webdav_config(config)
    assert result["remote_path"] == "/"


# --- WebDAVClient tests with mocked requests ---


class MockResponse:
    def __init__(self, status_code=200, text="", content=b"", headers=None):
        self.status_code = status_code
        self.text = text
        self.content = content
        self.headers = headers or {}
        self.iter_chunks = []

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=8192):
        yield self.content


def test_webdav_client_ensure_directory(monkeypatch):
    client = WebDAVClient("https://example.com/dav/", "user", "pass")
    calls = []

    def mock_request(method, url, **kwargs):
        calls.append({"method": method, "url": url})
        return MockResponse(201)

    monkeypatch.setattr(client.session, "request", mock_request)
    client.ensure_directory("/papers/2025")

    methods = [c["method"] for c in calls]
    assert all(m == "MKCOL" for m in methods)
    assert len(calls) == 2


def test_webdav_client_list_files(monkeypatch):
    propfind_response = """<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:">
  <D:response>
    <D:href>/dav/papers/</D:href>
    <D:propstat><D:prop><D:getcontentlength>0</D:getcontentlength></D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat>
  </D:response>
  <D:response>
    <D:href>/dav/papers/ICSE_2025.json</D:href>
    <D:propstat><D:prop><D:getcontentlength>1234</D:getcontentlength><D:getlastmodified>Mon, 01 Jan 2025 00:00:00 GMT</D:getlastmodified></D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat>
  </D:response>
  <D:response>
    <D:href>/dav/papers/FSE_2025.json</D:href>
    <D:propstat><D:prop><D:getcontentlength>5678</D:getcontentlength><D:getlastmodified>Tue, 02 Jan 2025 00:00:00 GMT</D:getlastmodified></D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat>
  </D:response>
</D:multistatus>"""

    client = WebDAVClient("https://example.com/dav/", "user", "pass")

    def mock_request(method, url, **kwargs):
        return MockResponse(207, text=propfind_response)

    monkeypatch.setattr(client.session, "request", mock_request)
    files = client.list_files("/papers")

    assert len(files) == 2
    names = {f["name"] for f in files}
    assert "ICSE_2025.json" in names
    assert "FSE_2025.json" in names
    icse = next(f for f in files if f["name"] == "ICSE_2025.json")
    assert icse["size"] == 1234


def test_webdav_client_upload_file(monkeypatch, tmp_path):
    local = tmp_path / "test.json"
    local.write_text('{"test": true}')
    client = WebDAVClient("https://example.com/dav/", "user", "pass")
    calls = []

    def mock_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, "data": kwargs.get("data")})
        return MockResponse(201)

    monkeypatch.setattr(client.session, "request", mock_request)
    client.upload_file(str(local), "/papers/test.json")

    assert len(calls) == 1
    assert calls[0]["method"] == "PUT"
    assert b"test" in calls[0]["data"]


def test_webdav_client_download_file(monkeypatch, tmp_path):
    client = WebDAVClient("https://example.com/dav/", "user", "pass")
    local_path = str(tmp_path / "downloaded.json")

    def mock_request(method, url, **kwargs):
        resp = MockResponse(200, content=b'{"downloaded": true}')
        return resp

    monkeypatch.setattr(client.session, "request", mock_request)
    # We need to mock get with stream=True
    def mock_get(url, timeout=60, stream=False):
        resp = MockResponse(200, content=b'{"downloaded": true}')
        resp.iter_content = lambda chunk_size=8192: [b'{"downloaded": true}']
        return resp

    monkeypatch.setattr(client.session, "get", mock_get)
    client.download_file("/papers/test.json", local_path)

    assert os.path.exists(local_path)
    assert open(local_path).read() == '{"downloaded": true}'


def test_webdav_client_file_exists(monkeypatch):
    client = WebDAVClient("https://example.com/dav/", "user", "pass")

    def mock_head(url, timeout=15):
        return MockResponse(200)

    monkeypatch.setattr(client.session, "head", mock_head)
    assert client.file_exists("/papers/test.json") is True


def test_webdav_client_file_not_exists(monkeypatch):
    client = WebDAVClient("https://example.com/dav/", "user", "pass")

    def mock_head(url, timeout=15):
        return MockResponse(404)

    monkeypatch.setattr(client.session, "head", mock_head)
    assert client.file_exists("/papers/test.json") is False


# --- sync_upload / sync_download / sync_status tests ---


def test_sync_upload_skips_unchanged_files(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "ICSE_2025.json").write_text('{"test": 1}')

    client = WebDAVClient("https://example.com/dav/", "user", "pass")

    # Mock list_files to return same size
    monkeypatch.setattr(
        client, "list_files",
        lambda remote_path, timeout=120: [{"name": "ICSE_2025.json", "size": os.path.getsize(str(data_dir / "ICSE_2025.json")), "modified": ""}],
    )
    upload_calls = []
    monkeypatch.setattr(client, "upload_file", lambda lp, rp: upload_calls.append(rp))
    monkeypatch.setattr(client, "ensure_directory", lambda rp: None)

    result = sync_upload(client, str(data_dir), "/papers")
    assert result["skipped"] == ["ICSE_2025.json"]
    assert result["uploaded"] == []
    assert upload_calls == []


def test_sync_upload_uploads_new_and_changed_files(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "ICSE_2025.json").write_text('{"test": 1}')
    (data_dir / "FSE_2025.json").write_text('{"test": 2}')

    client = WebDAVClient("https://example.com/dav/", "user", "pass")

    # Mock: remote has ICSE with different size, no FSE
    monkeypatch.setattr(
        client, "list_files",
        lambda remote_path: [{"name": "ICSE_2025.json", "size": 999, "modified": ""}],
    )
    upload_calls = []
    monkeypatch.setattr(client, "upload_file", lambda lp, rp: upload_calls.append(rp))
    monkeypatch.setattr(client, "ensure_directory", lambda rp: None)

    result = sync_upload(client, str(data_dir), "/papers")
    assert sorted(result["uploaded"]) == ["FSE_2025.json", "ICSE_2025.json"]
    assert result["skipped"] == []
    assert len(upload_calls) == 2


def test_sync_download_skips_unchanged_files(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    local_file = data_dir / "ICSE_2025.json"
    local_file.write_text('{"test": 1}')
    local_size = os.path.getsize(str(local_file))

    client = WebDAVClient("https://example.com/dav/", "user", "pass")
    monkeypatch.setattr(
        client, "list_files",
        lambda remote_path, timeout=120: [{"name": "ICSE_2025.json", "size": local_size, "modified": ""}],
    )
    download_calls = []
    monkeypatch.setattr(client, "download_file", lambda rp, lp: download_calls.append(rp))

    result = sync_download(client, str(data_dir), "/papers")
    assert result["skipped"] == ["ICSE_2025.json"]
    assert result["downloaded"] == []
    assert download_calls == []


def test_sync_download_downloads_new_files(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    client = WebDAVClient("https://example.com/dav/", "user", "pass")
    monkeypatch.setattr(
        client, "list_files",
        lambda remote_path, timeout=120: [{"name": "ICSE_2025.json", "size": 100, "modified": ""}],
    )

    def fake_download(rp, lp):
        with open(lp, "w") as f:
            f.write('{"downloaded": true}')

    monkeypatch.setattr(client, "download_file", fake_download)

    result = sync_download(client, str(data_dir), "/papers")
    assert result["downloaded"] == ["ICSE_2025.json"]
    assert result["skipped"] == []
    assert (data_dir / "ICSE_2025.json").exists()


def test_sync_status_shows_differences(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "ICSE_2025.json").write_text('{"test": 1}')
    (data_dir / "NDSS_2025.json").write_text('{"test": 2}')

    client = WebDAVClient("https://example.com/dav/", "user", "pass")
    monkeypatch.setattr(
        client, "list_files",
        lambda remote_path, timeout=120: [
            {"name": "ICSE_2025.json", "size": 100, "modified": ""},
            {"name": "FSE_2025.json", "size": 200, "modified": ""},
        ],
    )

    result = sync_status(client, str(data_dir), "/papers")
    assert result["local_only"] == ["NDSS_2025.json"]
    assert result["remote_only"] == ["FSE_2025.json"]
    assert result["both"] == ["ICSE_2025.json"]
    assert len(result["remote_files"]) == 2


# --- API endpoint tests ---


def _make_webdav_config(tmp_path, *, url="https://dav.example.com/", remote_path="/papers/"):
    config = {
        "include_ccfddl_catalog": False,
        "conferences": [{"id": "icse", "display_name": "ICSE", "dblp_stream": "conf/icse"}],
        "years": [2025],
        "output_dir": str(tmp_path / "data"),
        "webdav": {
            "url": url,
            "username": "testuser",
            "password": "testpass",
            "remote_path": remote_path,
        },
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return config_path


def test_sync_status_endpoint_returns_503_when_not_configured(tmp_path, monkeypatch):
    monkeypatch.delenv("WEBDAV_URL", raising=False)
    monkeypatch.delenv("WEBDAV_USERNAME", raising=False)
    monkeypatch.delenv("WEBDAV_PASSWORD", raising=False)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump({
            "include_ccfddl_catalog": False,
            "conferences": [{"id": "icse", "display_name": "ICSE"}],
            "years": [2025],
            "output_dir": str(tmp_path / "data"),
        }),
        encoding="utf-8",
    )
    client = create_app(str(config_path)).test_client()
    response = client.get("/api/sync/status")
    assert response.status_code == 503
    assert "not configured" in response.get_json()["error"].lower()


def test_sync_status_endpoint_returns_status(tmp_path, monkeypatch):
    monkeypatch.delenv("WEBDAV_URL", raising=False)
    monkeypatch.delenv("WEBDAV_USERNAME", raising=False)
    monkeypatch.delenv("WEBDAV_PASSWORD", raising=False)
    config_path = _make_webdav_config(tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)

    def mock_list_files(self, remote_path, timeout=120):
        return [{"name": "ICSE_2025.json", "size": 100, "modified": ""}]

    monkeypatch.setattr(WebDAVClient, "list_files", mock_list_files)

    # Mock HEAD request for connectivity check
    class MockResponse:
        status_code = 200
    monkeypatch.setattr("requests.Session.head", lambda self, url, **kw: MockResponse())

    client = create_app(str(config_path)).test_client()
    response = client.get("/api/sync/status")
    assert response.status_code == 200
    data = response.get_json()
    assert data["remote_url"] == "https://dav.example.com/"
    assert data["remote_path"] == "/papers/"


def test_sync_upload_endpoint_starts_background_job(tmp_path, monkeypatch):
    monkeypatch.delenv("WEBDAV_URL", raising=False)
    monkeypatch.delenv("WEBDAV_USERNAME", raising=False)
    monkeypatch.delenv("WEBDAV_PASSWORD", raising=False)
    config_path = _make_webdav_config(tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "ICSE_2025.json").write_text('{"test": 1}')

    monkeypatch.setattr(WebDAVClient, "ensure_directory", lambda self, rp: None)
    monkeypatch.setattr(WebDAVClient, "list_files", lambda self, rp, timeout=120: [])
    upload_calls = []
    monkeypatch.setattr(WebDAVClient, "upload_file", lambda self, lp, rp: upload_calls.append(rp))

    app = create_app(str(config_path))
    client = app.test_client()
    response = client.post("/api/sync/upload")
    assert response.status_code == 202

    status_url = response.get_json()["status_url"]
    for _ in range(20):
        status = client.get(status_url).get_json()
        if status["status"] == "completed":
            break
        time.sleep(0.05)

    assert status["status"] == "completed"
    assert status["result"]["uploaded"] == ["ICSE_2025.json"]


def test_sync_download_endpoint_starts_background_job(tmp_path, monkeypatch):
    monkeypatch.delenv("WEBDAV_URL", raising=False)
    monkeypatch.delenv("WEBDAV_USERNAME", raising=False)
    monkeypatch.delenv("WEBDAV_PASSWORD", raising=False)
    config_path = _make_webdav_config(tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)

    monkeypatch.setattr(WebDAVClient, "list_files", lambda self, rp, timeout=120: [{"name": "FSE_2025.json", "size": 50, "modified": ""}])

    def fake_download(self, rp, lp):
        os.makedirs(os.path.dirname(lp), exist_ok=True)
        with open(lp, "w") as f:
            f.write('{"test": 1}')

    monkeypatch.setattr(WebDAVClient, "download_file", fake_download)

    app = create_app(str(config_path))
    client = app.test_client()
    response = client.post("/api/sync/download")
    assert response.status_code == 202

    status_url = response.get_json()["status_url"]
    for _ in range(20):
        status = client.get(status_url).get_json()
        if status["status"] == "completed":
            break
        time.sleep(0.05)

    assert status["status"] == "completed"
    assert status["result"]["downloaded"] == ["FSE_2025.json"]
    assert (tmp_path / "data" / "FSE_2025.json").exists()


def test_sync_endpoints_reject_duplicate_jobs(tmp_path, monkeypatch):
    monkeypatch.delenv("WEBDAV_URL", raising=False)
    monkeypatch.delenv("WEBDAV_USERNAME", raising=False)
    monkeypatch.delenv("WEBDAV_PASSWORD", raising=False)
    config_path = _make_webdav_config(tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)

    started = threading.Event()
    release = threading.Event()

    def slow_upload(self, lp, rp):
        started.set()
        release.wait(timeout=2)

    monkeypatch.setattr(WebDAVClient, "ensure_directory", lambda self, rp: None)
    monkeypatch.setattr(WebDAVClient, "list_files", lambda self, rp, timeout=120: [{"name": "ICSE_2025.json", "size": 999, "modified": ""}])
    monkeypatch.setattr(WebDAVClient, "upload_file", slow_upload)
    (tmp_path / "data" / "ICSE_2025.json").write_text('{"test": 1}')

    app = create_app(str(config_path))
    client = app.test_client()

    response1 = client.post("/api/sync/upload")
    assert response1.status_code == 202
    assert started.wait(timeout=2)

    response2 = client.post("/api/sync/upload")
    assert response2.status_code == 409
    assert "already running" in response2.get_json()["error"].lower()

    release.set()
    for _ in range(20):
        time.sleep(0.05)
        status = client.get(response1.get_json()["status_url"]).get_json()
        if status["status"] in {"completed", "failed"}:
            break
