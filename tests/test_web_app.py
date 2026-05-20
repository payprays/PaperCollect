import json
import threading
import time

import yaml

from main import get_output_path
from src.web import create_app


def test_options_endpoint_reads_config(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "conferences": [
                    {
                        "id": "icse",
                        "display_name": "ICSE",
                        "dblp_stream": "conf/icse",
                    }
                ],
                "years": [2025],
                "output_dir": str(tmp_path / "data"),
                "limit_per_conference": 3,
            }
        ),
        encoding="utf-8",
    )

    client = create_app(str(config_path)).test_client()
    response = client.get("/api/options")

    assert response.status_code == 200
    assert response.get_json()["conferences"][0]["id"] == "icse"
    assert response.get_json()["conferences"][0]["display_name"] == "ICSE"
    assert any(category["id"] == "SE" for category in response.get_json()["categories"])
    assert any(tag["id"] == "cloud_native" for tag in response.get_json()["focus_tags"])
    assert response.get_json()["years"] == [2025]


def test_feed_endpoint_serves_saved_json_as_rss(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "ICSE_2025.json").write_text(
        json.dumps(
            [
                {
                    "title": "Test Paper",
                    "authors": ["A. Researcher"],
                    "venue": "ICSE",
                    "year": 2025,
                    "abstract": "A useful abstract.",
                    "url": "https://example.com/test",
                    "dblp_key": "conf/icse/test",
                }
            ]
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "conferences": [
                    {
                        "id": "icse",
                        "display_name": "ICSE",
                        "dblp_stream": "conf/icse",
                    }
                ],
                "years": [2025],
                "output_dir": str(data_dir),
            }
        ),
        encoding="utf-8",
    )

    client = create_app(str(config_path)).test_client()
    response = client.get("/feed/icse/2025.xml")

    assert response.status_code == 200
    assert response.mimetype == "application/rss+xml"
    assert b"Test Paper" in response.data


def test_feeds_endpoint_skips_saved_empty_json_files(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "ICSE_2025.json").write_text(
        json.dumps(
            [
                {
                    "title": "Test Paper",
                    "authors": ["A. Researcher"],
                    "venue": "ICSE",
                    "year": 2025,
                }
            ]
        ),
        encoding="utf-8",
    )
    (data_dir / "FSE_2025.json").write_text("[]", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "include_ccfddl_catalog": False,
                "conferences": [
                    {
                        "id": "icse",
                        "display_name": "ICSE",
                        "dblp_stream": "conf/icse",
                    },
                    {
                        "id": "fse",
                        "display_name": "FSE",
                        "dblp_stream": "conf/fse",
                    },
                ],
                "years": [2025],
                "output_dir": str(data_dir),
            }
        ),
        encoding="utf-8",
    )

    client = create_app(str(config_path)).test_client()
    response = client.get("/api/feeds")

    assert response.status_code == 200
    feeds = response.get_json()["feeds"]
    assert [feed["conference"] for feed in feeds] == ["icse"]
    assert feeds[0]["paper_count"] == 1


def test_feeds_endpoint_includes_saved_years_not_listed_in_config(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "conext_2024.json").write_text(
        json.dumps(
            [
                {
                    "title": "Saved CoNEXT Paper",
                    "authors": ["A. Researcher"],
                    "venue": "CoNEXT",
                    "year": 2024,
                }
            ]
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "include_ccfddl_catalog": False,
                "conferences": [
                    {
                        "id": "conext",
                        "display_name": "CoNEXT",
                        "dblp_stream": "conf/conext",
                        "years": [2025],
                    }
                ],
                "years": [2025],
                "output_dir": str(data_dir),
            }
        ),
        encoding="utf-8",
    )

    client = create_app(str(config_path)).test_client()
    response = client.get("/api/feeds")

    assert response.status_code == 200
    feeds = response.get_json()["feeds"]
    assert feeds == [
        {
            "conference": "conext",
            "display_name": "CoNEXT",
            "year": 2024,
            "paper_count": 1,
            "feed_url": "/feed/conext/2024.xml",
        }
    ]


def test_url_base_prefixes_routes_assets_and_generated_urls(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "ICSE_2025.json").write_text(
        json.dumps(
            [
                {
                    "title": "Prefixed Paper",
                    "authors": ["A. Researcher"],
                    "venue": "ICSE",
                    "year": 2025,
                }
            ]
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "include_ccfddl_catalog": False,
                "url_base": "/papercollect",
                "conferences": [
                    {
                        "id": "icse",
                        "display_name": "ICSE",
                        "dblp_stream": "conf/icse",
                    }
                ],
                "years": [2025],
                "output_dir": str(data_dir),
                "concurrency": {"threads": 1},
            }
        ),
        encoding="utf-8",
    )

    def fake_process_conference_year(conf, year, dblp_client, metadata_manager, output_dir, limit):
        output_path = get_output_path(output_dir, conf, year)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump([{"title": "Collected Paper", "authors": [], "venue": "ICSE", "year": year}], f)

    monkeypatch.setattr("src.web.app.process_conference_year", fake_process_conference_year)

    client = create_app(str(config_path)).test_client()
    index_response = client.get("/papercollect/")

    assert index_response.status_code == 200
    assert b'/papercollect/static/styles.css' in index_response.data
    assert b'window.PAPERCOLLECT_URL_BASE = "/papercollect";' in index_response.data
    assert client.get("/papercollect/static/app.js").status_code == 200
    assert client.get("/papercollect/api/options").status_code == 200

    feeds_response = client.get("/papercollect/api/feeds")
    assert feeds_response.status_code == 200
    assert feeds_response.get_json()["feeds"][0]["feed_url"] == "/papercollect/feed/icse/2025.xml"
    assert client.get("/papercollect/feed/icse/2025.xml").status_code == 200

    collect_response = client.post(
        "/papercollect/api/collect",
        json={"conference": "icse", "year": 2025, "limit": 1},
    )
    assert collect_response.status_code == 202
    assert collect_response.get_json()["status_url"] == "/papercollect/api/jobs/1"


def test_collect_rejects_conference_not_in_config(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "conferences": [
                    {
                        "id": "icse",
                        "display_name": "ICSE",
                        "dblp_stream": "conf/icse",
                    }
                ],
                "years": [2025],
            }
        ),
        encoding="utf-8",
    )

    client = create_app(str(config_path)).test_client()
    response = client.post(
        "/api/collect",
        json={"conference": "Unknown", "year": 2025, "limit": 1},
    )

    assert response.status_code == 400
    assert "conference" in response.get_json()["error"]


def test_collect_accepts_year_not_listed_in_config(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "conferences": [
                    {
                        "id": "icse",
                        "display_name": "ICSE",
                        "dblp_stream": "conf/icse",
                    }
                ],
                "years": [2024],
                "output_dir": str(data_dir),
                "concurrency": {"threads": 1},
            }
        ),
        encoding="utf-8",
    )

    def fake_process_conference_year(conf, year, dblp_client, metadata_manager, output_dir, limit):
        output_path = get_output_path(output_dir, conf, year)
        data_dir.mkdir(exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump([{"title": "Future Paper", "authors": [], "venue": "ICSE", "year": year}], f)

    monkeypatch.setattr("src.web.app.process_conference_year", fake_process_conference_year)

    client = create_app(str(config_path)).test_client()
    response = client.post("/api/collect", json={"conference": "icse", "year": 2026, "limit": 1})

    assert response.status_code == 202


def test_search_endpoint_returns_saved_papers(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "ICSE_2025.json").write_text(
        json.dumps(
            [
                {
                    "title": "Fuzzing WebAssembly Runtimes",
                    "authors": ["A. Researcher"],
                    "venue": "ICSE",
                    "year": 2025,
                    "abstract": "A fuzzing paper.",
                }
            ]
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "include_ccfddl_catalog": False,
                "conferences": [
                    {
                        "id": "icse",
                        "display_name": "ICSE",
                        "category": "SE",
                        "dblp_stream": "conf/icse",
                    }
                ],
                "years": [2025],
                "output_dir": str(data_dir),
            }
        ),
        encoding="utf-8",
    )

    client = create_app(str(config_path)).test_client()
    response = client.get("/api/search?q=fuzzing&category=SE")

    assert response.status_code == 200
    assert response.get_json()["results"][0]["title"] == "Fuzzing WebAssembly Runtimes"


def test_search_endpoint_supports_concept_mode(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "NDSS_2026.json").write_text(
        json.dumps(
            [
                {
                    "title": "Image Provenance Policies for Kubernetes Deployments",
                    "authors": ["A. Researcher"],
                    "venue": "NDSS",
                    "year": 2026,
                    "abstract": "We detect malicious container image supply chain attacks with SBOM evidence.",
                }
            ]
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "include_ccfddl_catalog": False,
                "conferences": [
                    {
                        "id": "ndss",
                        "display_name": "NDSS",
                        "category": "SC",
                        "focus_tags": ["security", "cloud_native"],
                        "dblp_stream": "conf/ndss",
                    }
                ],
                "years": [2026],
                "output_dir": str(data_dir),
            }
        ),
        encoding="utf-8",
    )

    client = create_app(str(config_path)).test_client()
    response = client.get("/api/search?q=云原生供应链攻击检测&mode=concept")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["mode"] == "concept"
    assert payload["results"][0]["title"] == "Image Provenance Policies for Kubernetes Deployments"
    assert "Software Supply Chain" in payload["results"][0]["matched_concepts"]


def test_search_endpoint_rejects_unknown_mode(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "include_ccfddl_catalog": False,
                "conferences": [{"id": "ndss", "display_name": "NDSS"}],
                "years": [2026],
                "output_dir": str(tmp_path / "data"),
            }
        ),
        encoding="utf-8",
    )

    client = create_app(str(config_path)).test_client()
    response = client.get("/api/search?q=test&mode=vector")

    assert response.status_code == 400
    assert "mode" in response.get_json()["error"]


def test_collect_endpoint_runs_job_and_exposes_feed(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "conferences": [
                    {
                        "id": "icse",
                        "display_name": "ICSE",
                        "dblp_stream": "conf/icse",
                    }
                ],
                "years": [2025],
                "output_dir": str(data_dir),
                "concurrency": {"threads": 1},
                "limit_per_conference": 1,
            }
        ),
        encoding="utf-8",
    )

    def fake_process_conference_year(conf, year, dblp_client, metadata_manager, output_dir, limit):
        print("Mock collector wrote one paper.")
        output_path = get_output_path(output_dir, conf, year)
        data_dir.mkdir(exist_ok=True)
        venue = getattr(conf, "display_name", conf)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(
                [
                    {
                        "title": "Collected Paper",
                        "authors": ["A. Researcher"],
                        "venue": venue,
                        "year": year,
                        "url": "https://example.com/collected",
                    }
                ],
                f,
            )

    monkeypatch.setattr("src.web.app.process_conference_year", fake_process_conference_year)

    client = create_app(str(config_path)).test_client()
    response = client.post("/api/collect", json={"conference": "icse", "year": 2025, "limit": 1})

    assert response.status_code == 202
    status_url = response.get_json()["status_url"]

    status = None
    for _ in range(20):
        status_response = client.get(status_url)
        status = status_response.get_json()
        if status["status"] == "completed":
            break
        time.sleep(0.05)

    assert status is not None
    assert status["status"] == "completed"
    assert status["paper_count"] == 1
    assert status["feed_url"] == "/feed/icse/2025.xml"
    assert "Started collection for ICSE 2025." in status["logs"]
    assert "Mock collector wrote one paper." in status["logs"]
    assert "Completed collection with 1 saved papers." in status["logs"]

    feed_response = client.get(status["feed_url"])
    assert feed_response.status_code == 200
    assert b"Collected Paper" in feed_response.data


def test_collect_endpoint_streams_logs_while_job_runs(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "conferences": [
                    {
                        "id": "icse",
                        "display_name": "ICSE",
                        "dblp_stream": "conf/icse",
                    }
                ],
                "years": [2025],
                "output_dir": str(data_dir),
                "concurrency": {"threads": 1},
            }
        ),
        encoding="utf-8",
    )
    started = threading.Event()
    release = threading.Event()

    def fake_process_conference_year(conf, year, dblp_client, metadata_manager, output_dir, limit):
        print("Fake collector reached DBLP stage.")
        started.set()
        assert release.wait(timeout=2)
        output_path = get_output_path(output_dir, conf, year)
        data_dir.mkdir(exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump([{"title": "Collected Paper", "authors": [], "venue": "ICSE", "year": year}], f)

    monkeypatch.setattr("src.web.app.process_conference_year", fake_process_conference_year)

    client = create_app(str(config_path)).test_client()
    response = client.post("/api/collect", json={"conference": "icse", "year": 2025, "limit": 1})

    assert response.status_code == 202
    assert started.wait(timeout=2)

    status_url = response.get_json()["status_url"]
    running_status = client.get(status_url).get_json()
    assert running_status["status"] == "running"
    assert "Fake collector reached DBLP stage." in running_status["logs"]

    release.set()
    for _ in range(20):
        completed_status = client.get(status_url).get_json()
        if completed_status["status"] == "completed":
            break
        time.sleep(0.05)

    assert completed_status["status"] == "completed"


def test_collect_endpoint_marks_job_failed_when_collection_raises(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "conferences": [
                    {
                        "id": "ndss",
                        "display_name": "NDSS",
                        "dblp_stream": "conf/ndss",
                    }
                ],
                "years": [2026],
                "output_dir": str(tmp_path / "data"),
            }
        ),
        encoding="utf-8",
    )

    def fake_process_conference_year(conf, year, dblp_client, metadata_manager, output_dir, limit):
        print("Fetching from DBLP...")
        raise RuntimeError("DBLP timed out")

    monkeypatch.setattr("src.web.app.process_conference_year", fake_process_conference_year)

    client = create_app(str(config_path)).test_client()
    response = client.post("/api/collect", json={"conference": "ndss", "year": 2026, "limit": 1})

    assert response.status_code == 202
    status_url = response.get_json()["status_url"]

    status = None
    for _ in range(20):
        status = client.get(status_url).get_json()
        if status["status"] == "failed":
            break
        time.sleep(0.05)

    assert status["status"] == "failed"
    assert status["error"] == "DBLP timed out"
    assert "Fetching from DBLP..." in status["logs"]
    assert "Collection failed: DBLP timed out" in status["logs"]
