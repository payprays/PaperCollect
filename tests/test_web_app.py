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

    monkeypatch.setattr("src.web.workers.collection.process_conference_year", fake_process_conference_year)

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
    collect_payload = collect_response.get_json()
    assert collect_payload["status_url"].startswith("/papercollect/api/jobs/")
    assert collect_payload["job_id"] in collect_payload["status_url"]
    for _ in range(20):
        status = client.get(collect_payload["status_url"]).get_json()
        if status["status"] == "completed":
            break
        time.sleep(0.05)
    assert status["status"] == "completed"


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


def test_collect_rejects_empty_conference_batch(tmp_path):
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
    response = client.post("/api/collect", json={"conferences": [], "year": 2025, "limit": 1})

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

    monkeypatch.setattr("src.web.workers.collection.process_conference_year", fake_process_conference_year)

    client = create_app(str(config_path)).test_client()
    response = client.post("/api/collect", json={"conference": "icse", "year": 2026, "limit": 1})

    assert response.status_code == 202
    status_url = response.get_json()["status_url"]
    for _ in range(20):
        status = client.get(status_url).get_json()
        if status["status"] == "completed":
            break
        time.sleep(0.05)
    assert status["status"] == "completed"


def test_collect_endpoint_runs_batch_and_records_partial_failures(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
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
                        "dblp_stream": "conf/sigsoft",
                    },
                ],
                "years": [2025],
                "output_dir": str(data_dir),
                "concurrency": {"threads": 1},
            }
        ),
        encoding="utf-8",
    )
    calls = []

    def fake_process_conference_year(conf, year, dblp_client, metadata_manager, output_dir, limit):
        calls.append(conf.id)
        print(f"Mock collector reached {conf.display_name}.")
        if conf.id == "fse":
            raise RuntimeError("FSE timed out")
        output_path = get_output_path(output_dir, conf, year)
        data_dir.mkdir(exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump([{"title": "Collected ICSE Paper", "authors": [], "venue": "ICSE", "year": year}], f)

    monkeypatch.setattr("src.web.workers.collection.process_conference_year", fake_process_conference_year)

    client = create_app(str(config_path)).test_client()
    response = client.post(
        "/api/collect",
        json={"conferences": ["icse", "icse", "fse"], "year": 2025, "limit": 1},
    )

    assert response.status_code == 202
    status_url = response.get_json()["status_url"]

    status = None
    for _ in range(20):
        status = client.get(status_url).get_json()
        if status["status"] == "completed":
            break
        time.sleep(0.05)

    assert calls == ["icse", "fse"]
    assert status["status"] == "completed"
    assert status["conference_count"] == 2
    assert status["completed_count"] == 1
    assert status["failed_count"] == 1
    assert status["paper_count"] == 1
    assert status["feed_urls"] == ["/feed/icse/2025.xml"]
    assert status["errors"] == [{"conference": "fse", "display_name": "FSE", "year": 2025, "error": "FSE timed out"}]
    assert "Collection failed for FSE: FSE timed out" in status["logs"]


def test_collect_stop_endpoint_cancels_batch_before_next_conference(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "include_ccfddl_catalog": False,
                "conferences": [
                    {"id": "icse", "display_name": "ICSE", "dblp_stream": "conf/icse"},
                    {"id": "fse", "display_name": "FSE", "dblp_stream": "conf/sigsoft"},
                ],
                "years": [2025],
                "output_dir": str(data_dir),
                "concurrency": {"threads": 1},
            }
        ),
        encoding="utf-8",
    )
    calls = []
    started = threading.Event()
    release = threading.Event()

    def fake_process_conference_year(conf, year, dblp_client, metadata_manager, output_dir, limit):
        calls.append(conf.id)
        print(f"Mock collector reached {conf.display_name}.")
        if conf.id == "icse":
            started.set()
            assert release.wait(timeout=2)
        output_path = get_output_path(output_dir, conf, year)
        data_dir.mkdir(exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(
                [
                    {
                        "title": f"{conf.display_name} Paper",
                        "authors": [],
                        "venue": conf.display_name,
                        "year": year,
                    }
                ],
                f,
            )

    monkeypatch.setattr("src.web.workers.collection.process_conference_year", fake_process_conference_year)

    client = create_app(str(config_path)).test_client()
    response = client.post(
        "/api/collect",
        json={"conferences": ["icse", "fse"], "year": 2025, "limit": 1},
    )

    assert response.status_code == 202
    assert started.wait(timeout=2)
    status_url = response.get_json()["status_url"]

    stop_response = client.post(f"{status_url}/stop")
    assert stop_response.status_code == 202
    assert stop_response.get_json()["cancel_requested"] is True
    release.set()

    status = None
    for _ in range(40):
        status = client.get(status_url).get_json()
        if status["status"] == "stopped":
            break
        time.sleep(0.05)

    assert calls == ["icse"]
    assert status["status"] == "stopped"
    assert status["completed_count"] == 1
    assert status["failed_count"] == 0
    assert status["stopped_count"] >= 1
    assert status["paper_count"] == 1
    assert status["feed_urls"] == ["/feed/icse/2025.xml"]
    assert "Stop requested; collection will stop after the current conference." in status["logs"]
    assert any("Collection stopped by user" in line for line in status["logs"])


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


def test_search_endpoint_supports_agentic_mode_with_index_status(tmp_path):
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
                "vector_index": {
                    "path": str(tmp_path / "qdrant"),
                    "collection": "missing_collection",
                    "embedding_provider": "hash",
                },
                "conferences": [
                    {
                        "id": "ndss",
                        "display_name": "NDSS",
                        "category": "SC",
                        "focus_tags": ["security", "cloud_native"],
                    }
                ],
                "years": [2026],
                "output_dir": str(data_dir),
            }
        ),
        encoding="utf-8",
    )

    client = create_app(str(config_path)).test_client()
    response = client.get("/api/search?q=云原生供应链攻击检测&mode=agentic")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["mode"] == "agentic"
    assert payload["index_status"]["indexed"] is False
    assert payload["results"][0]["search_mode"] == "agentic_fallback"


def test_search_endpoint_accepts_multiple_conferences_and_ccf_filter(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    for filename, title, venue in [
        ("icse_2025.json", "Fuzzing Runtime APIs", "ICSE"),
        ("fse_2025.json", "Fuzzing Compiler Pipelines", "FSE"),
        ("ndss_2025.json", "Fuzzing Malware Sandboxes", "NDSS"),
    ]:
        (data_dir / filename).write_text(
            json.dumps(
                [
                    {
                        "title": title,
                        "authors": ["A. Researcher"],
                        "venue": venue,
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
                    {"id": "icse", "display_name": "ICSE", "category": "SE", "tier": {"ccf": "A"}},
                    {"id": "fse", "display_name": "FSE", "category": "SE", "tier": {"ccf": "B"}},
                    {"id": "ndss", "display_name": "NDSS", "category": "SC", "tier": {"ccf": "A"}},
                ],
                "years": [2025],
                "output_dir": str(data_dir),
            }
        ),
        encoding="utf-8",
    )

    client = create_app(str(config_path)).test_client()
    response = client.get("/api/search?q=fuzzing&conference=icse&conference=fse&ccf=A")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["conferences"] == ["icse", "fse"]
    assert payload["ccf"] == "A"
    assert [result["conference"] for result in payload["results"]] == ["icse"]


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
    response = client.get("/api/search?q=test&mode=unknown")

    assert response.status_code == 400
    assert "mode" in response.get_json()["error"]


def test_index_endpoint_runs_background_job_and_rejects_duplicate(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "include_ccfddl_catalog": False,
                "conferences": [{"id": "ndss", "display_name": "NDSS"}],
                "years": [2026],
                "output_dir": str(data_dir),
                "vector_index": {"collection": "test_collection"},
            }
        ),
        encoding="utf-8",
    )
    release = threading.Event()

    def fake_run_index_subprocess(command, cwd, append_log):
        assert command[-2:] == ["--config", str(config_path)]
        assert cwd
        append_log("mock pc-index completed")
        assert release.wait(timeout=2)
        return 0

    def fake_vector_index_status(config):
        assert config["vector_index"]["collection"] == "test_collection"
        return {
            "backend": "qdrant",
            "collection": "test_collection",
            "indexed": True,
            "paper_count": 3,
            "url": None,
            "index_path": None,
        }

    monkeypatch.setattr("src.web.workers.index_worker.run_index_subprocess", fake_run_index_subprocess)
    monkeypatch.setattr("src.web.workers.index_worker.vector_index_status", fake_vector_index_status)

    client = create_app(str(config_path)).test_client()
    response = client.post("/api/index", json={"force": True})

    assert response.status_code == 202
    status_url = response.get_json()["status_url"]

    duplicate = client.post("/api/index", json={"force": True})
    assert duplicate.status_code == 409

    running_status = client.get(status_url).get_json()
    assert running_status["type"] == "index"
    assert running_status["status"] in {"queued", "running"}

    release.set()
    for _ in range(20):
        completed_status = client.get(status_url).get_json()
        if completed_status["status"] == "completed":
            break
        time.sleep(0.05)

    assert completed_status["status"] == "completed"
    assert completed_status["paper_count"] == 3
    assert completed_status["result"]["indexed"] is True
    assert "mock pc-index completed" in completed_status["logs"]


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

    monkeypatch.setattr("src.web.workers.collection.process_conference_year", fake_process_conference_year)

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

    monkeypatch.setattr("src.web.workers.collection.process_conference_year", fake_process_conference_year)

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

    monkeypatch.setattr("src.web.workers.collection.process_conference_year", fake_process_conference_year)

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


def _make_queue_config(tmp_path, conferences_config, *, include_ccfddl=False):
    """Helper to create a config with the given conferences."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "include_ccfddl_catalog": include_ccfddl,
                "conferences": conferences_config,
                "years": [2025],
                "output_dir": str(tmp_path / "data"),
                "concurrency": {"threads": 1},
            }
        ),
        encoding="utf-8",
    )
    return config_path


def test_collect_creates_queue_items(tmp_path, monkeypatch):
    """POST /api/collect with batch conferences produces queue[] with correct task_id, conference_id, status."""
    config_path = _make_queue_config(tmp_path, [
        {"id": "icse", "display_name": "ICSE", "dblp_stream": "conf/icse"},
        {"id": "fse", "display_name": "FSE", "dblp_stream": "conf/sigsoft"},
        {"id": "issta", "display_name": "ISSTA", "dblp_stream": "conf/issta"},
    ])

    started = threading.Event()
    release = threading.Event()

    def fake_process_conference_year(conf, year, dblp_client, metadata_manager, output_dir, limit):
        if not started.is_set():
            started.set()
            assert release.wait(timeout=2)

    monkeypatch.setattr("src.web.workers.collection.process_conference_year", fake_process_conference_year)

    client = create_app(str(config_path)).test_client()
    response = client.post(
        "/api/collect",
        json={"conferences": ["icse", "fse", "issta"], "year": 2025, "limit": 1},
    )

    assert response.status_code == 202
    status_url = response.get_json()["status_url"]
    assert started.wait(timeout=2)

    job = client.get(status_url).get_json()
    queue = job.get("queue")
    assert queue is not None
    assert len(queue) == 3

    seen_ids = set()
    for i, task in enumerate(queue):
        assert len(task["task_id"]) == 8
        assert task["conference_id"] == ["icse", "fse", "issta"][i]
        assert task["display_name"] == ["ICSE", "FSE", "ISSTA"][i]
        assert task["status"] in {"pending", "running"}
        assert task["task_id"] not in seen_ids
        seen_ids.add(task["task_id"])

    assert job.get("task_summary") is not None
    assert "pending" in job["task_summary"]
    assert "running" in job["task_summary"]

    release.set()
    for _ in range(40):
        time.sleep(0.05)
        if client.get(status_url).get_json()["status"] in {"completed", "failed"}:
            break


def test_queue_progression(tmp_path, monkeypatch):
    """Mocked collection processes tasks sequentially; each task transitions pending -> running -> completed."""
    config_path = _make_queue_config(tmp_path, [
        {"id": "icse", "display_name": "ICSE", "dblp_stream": "conf/icse"},
        {"id": "fse", "display_name": "FSE", "dblp_stream": "conf/sigsoft"},
    ])

    def fake_process_conference_year(conf, year, dblp_client, metadata_manager, output_dir, limit):
        (tmp_path / "data").mkdir(exist_ok=True)
        output_path = get_output_path(str(tmp_path / "data"), conf, year)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump([{"title": f"{conf.display_name} Paper", "authors": [], "venue": conf.display_name, "year": year}], f)

    monkeypatch.setattr("src.web.workers.collection.process_conference_year", fake_process_conference_year)

    client = create_app(str(config_path)).test_client()
    response = client.post(
        "/api/collect",
        json={"conferences": ["icse", "fse"], "year": 2025, "limit": 1},
    )

    assert response.status_code == 202
    status_url = response.get_json()["status_url"]

    for _ in range(40):
        status = client.get(status_url).get_json()
        if status["status"] == "completed":
            break
        time.sleep(0.05)

    assert status["status"] == "completed"
    queue = status["queue"]
    assert len(queue) == 2
    assert queue[0]["status"] == "completed"
    assert queue[0]["paper_count"] == 1
    assert queue[0]["output_path"] is not None
    assert queue[0]["feed_url"] is not None
    assert queue[0]["started_at"] is not None
    assert queue[0]["finished_at"] is not None
    assert queue[1]["status"] == "completed"
    assert queue[1]["paper_count"] == 1

    summary = status["task_summary"]
    assert summary["completed"] == 2
    assert summary["pending"] == 0
    assert summary["failed"] == 0
    assert summary["skipped"] == 0


def test_stop_mid_batch_stops_job(tmp_path, monkeypatch):
    """Stop after first task completes; remaining pending tasks are skipped, job status is stopped."""
    config_path = _make_queue_config(tmp_path, [
        {"id": "icse", "display_name": "ICSE", "dblp_stream": "conf/icse"},
        {"id": "fse", "display_name": "FSE", "dblp_stream": "conf/sigsoft"},
        {"id": "issta", "display_name": "ISSTA", "dblp_stream": "conf/issta"},
    ])

    started = threading.Event()
    release = threading.Event()
    calls = []

    def fake_process_conference_year(conf, year, dblp_client, metadata_manager, output_dir, limit):
        calls.append(conf.id)
        if conf.id == "icse":
            (tmp_path / "data").mkdir(exist_ok=True)
            output_path = get_output_path(str(tmp_path / "data"), conf, year)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump([{"title": "ICSE Paper", "authors": [], "venue": "ICSE", "year": year}], f)
            started.set()
            assert release.wait(timeout=2)
        elif conf.id == "fse":
            (tmp_path / "data").mkdir(exist_ok=True)
            output_path = get_output_path(str(tmp_path / "data"), conf, year)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump([{"title": "FSE Paper", "authors": [], "venue": "FSE", "year": year}], f)

    monkeypatch.setattr("src.web.workers.collection.process_conference_year", fake_process_conference_year)

    client = create_app(str(config_path)).test_client()
    response = client.post(
        "/api/collect",
        json={"conferences": ["icse", "fse", "issta"], "year": 2025, "limit": 1},
    )

    assert response.status_code == 202
    status_url = response.get_json()["status_url"]
    assert started.wait(timeout=2)

    stop_response = client.post(f"{status_url}/stop")
    assert stop_response.status_code == 202
    assert stop_response.get_json()["cancel_requested"] is True
    release.set()

    for _ in range(40):
        status = client.get(status_url).get_json()
        if status["status"] == "stopped":
            break
        time.sleep(0.05)

    assert status["status"] == "stopped"
    assert calls == ["icse"]
    assert status["completed_count"] == 1
    assert status["paper_count"] == 1
    assert status["stopped_count"] >= 1

    queue = status["queue"]
    assert queue[0]["status"] == "completed"
    assert any(item["status"] == "skipped" for item in queue[1:])
    assert any("Collection stopped by user" in line for line in status["logs"])


def test_resume_from_stopped_state(tmp_path, monkeypatch):
    """From stopped state, resume re-queues skipped tasks; completed tasks are not re-run."""
    config_path = _make_queue_config(tmp_path, [
        {"id": "icse", "display_name": "ICSE", "dblp_stream": "conf/icse"},
        {"id": "fse", "display_name": "FSE", "dblp_stream": "conf/sigsoft"},
        {"id": "issta", "display_name": "ISSTA", "dblp_stream": "conf/issta"},
    ])

    calls = []
    started = threading.Event()
    release = threading.Event()

    def fake_process_conference_year(conf, year, dblp_client, metadata_manager, output_dir, limit):
        calls.append(conf.id)
        if conf.id == "icse":
            (tmp_path / "data").mkdir(exist_ok=True)
            output_path = get_output_path(str(tmp_path / "data"), conf, year)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump([{"title": "ICSE Paper", "authors": [], "venue": "ICSE", "year": year}], f)
            started.set()
            assert release.wait(timeout=2)
        else:
            (tmp_path / "data").mkdir(exist_ok=True)
            output_path = get_output_path(str(tmp_path / "data"), conf, year)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump([{"title": f"{conf.display_name} Paper", "authors": [], "venue": conf.display_name, "year": year}], f)

    monkeypatch.setattr("src.web.workers.collection.process_conference_year", fake_process_conference_year)

    client = create_app(str(config_path)).test_client()
    response = client.post(
        "/api/collect",
        json={"conferences": ["icse", "fse", "issta"], "year": 2025, "limit": 1},
    )

    assert response.status_code == 202
    status_url = response.get_json()["status_url"]
    assert started.wait(timeout=2)

    stop_response = client.post(f"{status_url}/stop")
    assert stop_response.status_code == 202
    release.set()

    for _ in range(40):
        status = client.get(status_url).get_json()
        if status["status"] == "stopped":
            break
        time.sleep(0.05)

    assert status["status"] == "stopped"
    assert calls == ["icse"]

    resume_response = client.post(f"{status_url}/resume")
    assert resume_response.status_code == 202

    for _ in range(40):
        status = client.get(status_url).get_json()
        if status["status"] == "completed":
            break
        time.sleep(0.05)

    assert status["status"] == "completed"
    assert "icse" in calls
    assert "fse" in calls
    assert "issta" in calls

    queue = status["queue"]
    assert queue[0]["status"] == "completed"
    assert queue[1]["status"] == "completed"
    assert queue[2]["status"] == "completed"


def test_retry_failed_tasks(tmp_path, monkeypatch):
    """From completed state with 1 failed task, retry re-queues only that task."""
    config_path = _make_queue_config(tmp_path, [
        {"id": "icse", "display_name": "ICSE", "dblp_stream": "conf/icse"},
        {"id": "fse", "display_name": "FSE", "dblp_stream": "conf/sigsoft"},
    ])

    call_count = {"fse": 0}

    def fake_process_conference_year(conf, year, dblp_client, metadata_manager, output_dir, limit):
        if conf.id == "fse":
            call_count["fse"] += 1
            if call_count["fse"] == 1:
                raise RuntimeError("FSE timed out")
        (tmp_path / "data").mkdir(exist_ok=True)
        output_path = get_output_path(str(tmp_path / "data"), conf, year)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump([{"title": f"{conf.display_name} Paper", "authors": [], "venue": conf.display_name, "year": year}], f)

    monkeypatch.setattr("src.web.workers.collection.process_conference_year", fake_process_conference_year)

    client = create_app(str(config_path)).test_client()
    response = client.post(
        "/api/collect",
        json={"conferences": ["icse", "fse"], "year": 2025, "limit": 1},
    )

    assert response.status_code == 202
    status_url = response.get_json()["status_url"]

    for _ in range(40):
        status = client.get(status_url).get_json()
        if status["status"] == "completed":
            break
        time.sleep(0.05)

    assert status["status"] == "completed"
    assert status["completed_count"] == 1
    assert status["failed_count"] == 1

    queue = status["queue"]
    assert queue[0]["status"] == "completed"
    assert queue[1]["status"] == "failed"

    retry_response = client.post(f"{status_url}/retry")
    assert retry_response.status_code == 202

    for _ in range(40):
        status = client.get(status_url).get_json()
        if status["status"] == "completed":
            break
        time.sleep(0.05)

    assert status["status"] == "completed"
    assert call_count["fse"] == 2
    assert status["completed_count"] == 2
    assert status["failed_count"] == 0

    queue = status["queue"]
    assert queue[0]["status"] == "completed"
    assert queue[1]["status"] == "completed"


def test_single_task_retry(tmp_path, monkeypatch):
    """POST /api/jobs/<id>/queue/<task_id>/retry resets only the target task."""
    config_path = _make_queue_config(tmp_path, [
        {"id": "icse", "display_name": "ICSE", "dblp_stream": "conf/icse"},
        {"id": "fse", "display_name": "FSE", "dblp_stream": "conf/sigsoft"},
    ])

    fse_attempts = {"count": 0}

    def fake_process_conference_year(conf, year, dblp_client, metadata_manager, output_dir, limit):
        if conf.id == "fse":
            fse_attempts["count"] += 1
            if fse_attempts["count"] <= 1:
                raise RuntimeError("FSE failed")
        (tmp_path / "data").mkdir(exist_ok=True)
        output_path = get_output_path(str(tmp_path / "data"), conf, year)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump([{"title": f"{conf.display_name} Paper", "authors": [], "venue": conf.display_name, "year": year}], f)

    monkeypatch.setattr("src.web.workers.collection.process_conference_year", fake_process_conference_year)

    client = create_app(str(config_path)).test_client()
    response = client.post(
        "/api/collect",
        json={"conferences": ["icse", "fse"], "year": 2025, "limit": 1},
    )

    assert response.status_code == 202
    status_url = response.get_json()["status_url"]

    for _ in range(40):
        status = client.get(status_url).get_json()
        if status["status"] == "completed":
            break
        time.sleep(0.05)

    queue = status["queue"]
    failed_task = next(t for t in queue if t["status"] == "failed")
    assert failed_task["conference_id"] == "fse"

    retry_response = client.post(f"{status_url}/queue/{failed_task['task_id']}/retry")
    assert retry_response.status_code == 202

    for _ in range(40):
        status = client.get(status_url).get_json()
        if status["status"] == "completed":
            break
        time.sleep(0.05)

    queue = status["queue"]
    fse_task = next(t for t in queue if t["conference_id"] == "fse")
    assert fse_task["status"] == "completed"
    assert status["completed_count"] == 2


def test_single_task_retry_unknown_task_id(tmp_path, monkeypatch):
    """POST /api/jobs/<id>/queue/<task_id>/retry with unknown task_id returns 404."""
    config_path = _make_queue_config(tmp_path, [
        {"id": "icse", "display_name": "ICSE", "dblp_stream": "conf/icse"},
    ])

    def fake_process_conference_year(conf, year, dblp_client, metadata_manager, output_dir, limit):
        (tmp_path / "data").mkdir(exist_ok=True)
        output_path = get_output_path(str(tmp_path / "data"), conf, year)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump([{"title": "ICSE Paper", "authors": [], "venue": "ICSE", "year": year}], f)

    monkeypatch.setattr("src.web.workers.collection.process_conference_year", fake_process_conference_year)

    client = create_app(str(config_path)).test_client()
    response = client.post(
        "/api/collect",
        json={"conference": "icse", "year": 2025, "limit": 1},
    )

    assert response.status_code == 202
    status_url = response.get_json()["status_url"]

    for _ in range(40):
        status = client.get(status_url).get_json()
        if status["status"] == "completed":
            break
        time.sleep(0.05)

    retry_response = client.post(f"{status_url}/queue/nonexistent/retry")
    assert retry_response.status_code == 404
    assert "not found" in retry_response.get_json()["error"].lower()


def test_single_task_retry_on_completed_task_returns_400(tmp_path, monkeypatch):
    """POST /api/jobs/<id>/queue/<task_id>/retry on a completed task returns 400."""
    config_path = _make_queue_config(tmp_path, [
        {"id": "icse", "display_name": "ICSE", "dblp_stream": "conf/icse"},
    ])

    def fake_process_conference_year(conf, year, dblp_client, metadata_manager, output_dir, limit):
        (tmp_path / "data").mkdir(exist_ok=True)
        output_path = get_output_path(str(tmp_path / "data"), conf, year)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump([{"title": "ICSE Paper", "authors": [], "venue": "ICSE", "year": year}], f)

    monkeypatch.setattr("src.web.workers.collection.process_conference_year", fake_process_conference_year)

    client = create_app(str(config_path)).test_client()
    response = client.post(
        "/api/collect",
        json={"conference": "icse", "year": 2025, "limit": 1},
    )

    assert response.status_code == 202
    status_url = response.get_json()["status_url"]

    for _ in range(40):
        status = client.get(status_url).get_json()
        if status["status"] == "completed":
            break
        time.sleep(0.05)

    completed_task = status["queue"][0]
    assert completed_task["status"] == "completed"

    retry_response = client.post(f"{status_url}/queue/{completed_task['task_id']}/retry")
    assert retry_response.status_code == 400
    assert "cannot be retried" in retry_response.get_json()["error"].lower()


def test_resume_returns_409_when_another_job_holds_lock(tmp_path, monkeypatch):
    """Resume/retry while another collection job holds the lock returns 409."""
    config_path = _make_queue_config(tmp_path, [
        {"id": "icse", "display_name": "ICSE", "dblp_stream": "conf/icse"},
        {"id": "fse", "display_name": "FSE", "dblp_stream": "conf/sigsoft"},
    ])

    started = threading.Event()
    release = threading.Event()

    def fake_process_conference_year(conf, year, dblp_client, metadata_manager, output_dir, limit):
        if conf.id == "icse":
            started.set()
            assert release.wait(timeout=3)
        (tmp_path / "data").mkdir(exist_ok=True)
        output_path = get_output_path(str(tmp_path / "data"), conf, year)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump([{"title": f"{conf.display_name} Paper", "authors": [], "venue": conf.display_name, "year": year}], f)

    monkeypatch.setattr("src.web.workers.collection.process_conference_year", fake_process_conference_year)

    client = create_app(str(config_path)).test_client()

    # Start first job (will block on icse)
    response1 = client.post(
        "/api/collect",
        json={"conferences": ["icse", "fse"], "year": 2025, "limit": 1},
    )
    assert response1.status_code == 202
    assert started.wait(timeout=2)

    # Create a second stopped job manually to try resume
    # First, stop the running job
    status_url1 = response1.get_json()["status_url"]
    stop_response = client.post(f"{status_url1}/stop")
    assert stop_response.status_code == 202
    release.set()

    for _ in range(40):
        status = client.get(status_url1).get_json()
        if status["status"] == "stopped":
            break
        time.sleep(0.05)

    assert status["status"] == "stopped"

    # Now start a new blocking job
    started.clear()
    release.clear()
    response2 = client.post(
        "/api/collect",
        json={"conference": "icse", "year": 2025, "limit": 1},
    )
    assert response2.status_code == 202
    assert started.wait(timeout=2)

    # Try to resume the stopped job while new job is running
    resume_response = client.post(f"{status_url1}/resume")
    assert resume_response.status_code == 409
    assert "already running" in resume_response.get_json()["error"].lower()

    release.set()
    for _ in range(40):
        time.sleep(0.05)
        if client.get(response2.get_json()["status_url"]).get_json()["status"] in {"completed", "failed"}:
            break


def test_resume_returns_409_on_running_job(tmp_path, monkeypatch):
    """Resume on a running job returns 409."""
    config_path = _make_queue_config(tmp_path, [
        {"id": "icse", "display_name": "ICSE", "dblp_stream": "conf/icse"},
    ])

    started = threading.Event()
    release = threading.Event()

    def fake_process_conference_year(conf, year, dblp_client, metadata_manager, output_dir, limit):
        started.set()
        assert release.wait(timeout=2)

    monkeypatch.setattr("src.web.workers.collection.process_conference_year", fake_process_conference_year)

    client = create_app(str(config_path)).test_client()
    response = client.post(
        "/api/collect",
        json={"conference": "icse", "year": 2025, "limit": 1},
    )

    assert response.status_code == 202
    status_url = response.get_json()["status_url"]
    assert started.wait(timeout=2)

    resume_response = client.post(f"{status_url}/resume")
    assert resume_response.status_code == 409
    assert "already running" in resume_response.get_json()["error"].lower()

    release.set()
    for _ in range(40):
        time.sleep(0.05)
        if client.get(status_url).get_json()["status"] in {"completed", "failed"}:
            break


def test_retry_returns_400_when_no_failed_tasks(tmp_path, monkeypatch):
    """Retry when all tasks are completed returns 400."""
    config_path = _make_queue_config(tmp_path, [
        {"id": "icse", "display_name": "ICSE", "dblp_stream": "conf/icse"},
    ])

    def fake_process_conference_year(conf, year, dblp_client, metadata_manager, output_dir, limit):
        (tmp_path / "data").mkdir(exist_ok=True)
        output_path = get_output_path(str(tmp_path / "data"), conf, year)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump([{"title": "ICSE Paper", "authors": [], "venue": "ICSE", "year": year}], f)

    monkeypatch.setattr("src.web.workers.collection.process_conference_year", fake_process_conference_year)

    client = create_app(str(config_path)).test_client()
    response = client.post(
        "/api/collect",
        json={"conference": "icse", "year": 2025, "limit": 1},
    )

    assert response.status_code == 202
    status_url = response.get_json()["status_url"]

    for _ in range(40):
        status = client.get(status_url).get_json()
        if status["status"] == "completed":
            break
        time.sleep(0.05)

    retry_response = client.post(f"{status_url}/retry")
    assert retry_response.status_code == 400
    assert "no failed tasks" in retry_response.get_json()["error"].lower()


def test_task_summary_reflects_queue_state(tmp_path, monkeypatch):
    """GET /api/jobs/<id> returns correct task_summary counts."""
    config_path = _make_queue_config(tmp_path, [
        {"id": "icse", "display_name": "ICSE", "dblp_stream": "conf/icse"},
        {"id": "fse", "display_name": "FSE", "dblp_stream": "conf/sigsoft"},
        {"id": "issta", "display_name": "ISSTA", "dblp_stream": "conf/issta"},
    ])

    def fake_process_conference_year(conf, year, dblp_client, metadata_manager, output_dir, limit):
        if conf.id == "fse":
            raise RuntimeError("FSE failed")
        (tmp_path / "data").mkdir(exist_ok=True)
        output_path = get_output_path(str(tmp_path / "data"), conf, year)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump([{"title": f"{conf.display_name} Paper", "authors": [], "venue": conf.display_name, "year": year}], f)

    monkeypatch.setattr("src.web.workers.collection.process_conference_year", fake_process_conference_year)

    client = create_app(str(config_path)).test_client()
    response = client.post(
        "/api/collect",
        json={"conferences": ["icse", "fse", "issta"], "year": 2025, "limit": 1},
    )

    assert response.status_code == 202
    status_url = response.get_json()["status_url"]

    for _ in range(40):
        status = client.get(status_url).get_json()
        if status["status"] == "completed":
            break
        time.sleep(0.05)

    assert status["status"] == "completed"
    summary = status["task_summary"]
    assert summary["completed"] == 2
    assert summary["failed"] == 1
    assert summary["pending"] == 0
    assert summary["running"] == 0
    assert summary["skipped"] == 0


def test_queue_logs_appear_in_job_logs(tmp_path, monkeypatch):
    """Per-task logs appear in job.logs during execution."""
    config_path = _make_queue_config(tmp_path, [
        {"id": "icse", "display_name": "ICSE", "dblp_stream": "conf/icse"},
    ])

    def fake_process_conference_year(conf, year, dblp_client, metadata_manager, output_dir, limit):
        print("Fetching from DBLP stage.")
        (tmp_path / "data").mkdir(exist_ok=True)
        output_path = get_output_path(str(tmp_path / "data"), conf, year)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump([{"title": "ICSE Paper", "authors": [], "venue": "ICSE", "year": year}], f)

    monkeypatch.setattr("src.web.workers.collection.process_conference_year", fake_process_conference_year)

    client = create_app(str(config_path)).test_client()
    response = client.post(
        "/api/collect",
        json={"conference": "icse", "year": 2025, "limit": 1},
    )

    assert response.status_code == 202
    status_url = response.get_json()["status_url"]

    for _ in range(40):
        status = client.get(status_url).get_json()
        if status["status"] == "completed":
            break
        time.sleep(0.05)

    assert status["status"] == "completed"
    logs = status["logs"]
    assert any("Started collection for ICSE 2025" in line for line in logs)
    assert any("Fetching from DBLP stage." in line for line in logs)
    assert any("Completed collection with 1 saved papers." in line for line in logs)


def test_idempotent_stop_on_stopped_job(tmp_path, monkeypatch):
    """Calling stop on an already-stopped job returns 409 with current state."""
    config_path = _make_queue_config(tmp_path, [
        {"id": "icse", "display_name": "ICSE", "dblp_stream": "conf/icse"},
        {"id": "fse", "display_name": "FSE", "dblp_stream": "conf/sigsoft"},
    ])

    started = threading.Event()
    release = threading.Event()

    def fake_process_conference_year(conf, year, dblp_client, metadata_manager, output_dir, limit):
        started.set()
        assert release.wait(timeout=2)

    monkeypatch.setattr("src.web.workers.collection.process_conference_year", fake_process_conference_year)

    client = create_app(str(config_path)).test_client()
    response = client.post(
        "/api/collect",
        json={"conferences": ["icse", "fse"], "year": 2025, "limit": 1},
    )

    assert response.status_code == 202
    status_url = response.get_json()["status_url"]
    assert started.wait(timeout=2)

    stop_response = client.post(f"{status_url}/stop")
    assert stop_response.status_code == 202
    release.set()

    for _ in range(40):
        status = client.get(status_url).get_json()
        if status["status"] == "stopped":
            break
        time.sleep(0.05)

    assert status["status"] == "stopped"

    # Second stop should return 409
    stop_response2 = client.post(f"{status_url}/stop")
    assert stop_response2.status_code == 409
    assert "not running" in stop_response2.get_json()["error"].lower()


def test_resume_with_failed_tasks_in_stopped_job(tmp_path, monkeypatch):
    """Resume a stopped job where some tasks failed and some were skipped."""
    config_path = _make_queue_config(tmp_path, [
        {"id": "icse", "display_name": "ICSE", "dblp_stream": "conf/icse"},
        {"id": "fse", "display_name": "FSE", "dblp_stream": "conf/sigsoft"},
        {"id": "issta", "display_name": "ISSTA", "dblp_stream": "conf/issta"},
    ])

    fse_started = threading.Event()
    fse_release = threading.Event()

    def fake_process_conference_year(conf, year, dblp_client, metadata_manager, output_dir, limit):
        if conf.id == "fse":
            fse_started.set()
            assert fse_release.wait(timeout=3)
            raise RuntimeError("FSE failed")
        (tmp_path / "data").mkdir(exist_ok=True)
        output_path = get_output_path(str(tmp_path / "data"), conf, year)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump([{"title": f"{conf.display_name} Paper", "authors": [], "venue": conf.display_name, "year": year}], f)

    monkeypatch.setattr("src.web.workers.collection.process_conference_year", fake_process_conference_year)

    client = create_app(str(config_path)).test_client()
    response = client.post(
        "/api/collect",
        json={"conferences": ["icse", "fse", "issta"], "year": 2025, "limit": 1},
    )

    assert response.status_code == 202
    status_url = response.get_json()["status_url"]

    # Wait for fse to start (icse already completed)
    assert fse_started.wait(timeout=5)

    stop_response = client.post(f"{status_url}/stop")
    assert stop_response.status_code == 202
    fse_release.set()

    for _ in range(40):
        status = client.get(status_url).get_json()
        if status["status"] == "stopped":
            break
        time.sleep(0.05)

    assert status["status"] == "stopped"
    queue = status["queue"]
    assert queue[0]["status"] == "completed"  # ICSE
    assert queue[1]["status"] == "failed"     # FSE (ran and failed while stop was pending)
    assert queue[2]["status"] == "skipped"    # ISSTA (never started)

    # Resume should re-queue failed and skipped tasks
    resume_response = client.post(f"{status_url}/resume")
    assert resume_response.status_code == 202

    for _ in range(80):
        status = client.get(status_url).get_json()
        if status["status"] == "completed":
            break
        time.sleep(0.05)

    assert status["status"] == "completed"
    queue = status["queue"]
    assert queue[0]["status"] == "completed"
    assert queue[1]["status"] == "failed"     # FSE still fails
    assert queue[2]["status"] == "completed"  # ISSTA now completes


def test_year_progress_endpoint_returns_saved_and_missing_years(tmp_path):
    """GET /api/year-progress returns configured_years, saved_years, missing_years per conference."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "icse_2024.json").write_text(
        json.dumps([{"title": "Paper 2024", "authors": [], "venue": "ICSE", "year": 2024}]),
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
                        "dblp_stream": "conf/icse",
                        "category": "SE",
                        "tier": {"ccf": "A"},
                    }
                ],
                "years": [2023, 2024, 2025],
                "output_dir": str(data_dir),
            }
        ),
        encoding="utf-8",
    )

    client = create_app(str(config_path)).test_client()
    response = client.get("/api/year-progress")

    assert response.status_code == 200
    payload = response.get_json()
    assert len(payload["progress"]) == 1

    entry = payload["progress"][0]
    assert entry["conference_id"] == "icse"
    assert entry["display_name"] == "ICSE"
    assert entry["category"] == "SE"
    assert entry["ccf"] == "A"
    assert entry["configured_years"] == [2023, 2024, 2025]
    assert entry["saved_years"] == [2024]
    assert entry["missing_years"] == [2023, 2025]


def test_year_progress_endpoint_with_per_conference_years(tmp_path):
    """Per-conference years override global years in year-progress."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "include_ccfddl_catalog": False,
                "conferences": [
                    {
                        "id": "mlsys",
                        "display_name": "MLSys",
                        "dblp_stream": "conf/mlsys",
                        "years": [2023, 2024, 2025],
                    }
                ],
                "years": [2024, 2025, 2026],
                "output_dir": str(data_dir),
            }
        ),
        encoding="utf-8",
    )

    client = create_app(str(config_path)).test_client()
    response = client.get("/api/year-progress")

    assert response.status_code == 200
    entry = response.get_json()["progress"][0]
    assert entry["conference_id"] == "mlsys"
    assert entry["configured_years"] == [2023, 2024, 2025]
    assert entry["saved_years"] == []
    assert entry["missing_years"] == [2023, 2024, 2025]


def test_collect_with_years_array_creates_nxm_queue_items(tmp_path, monkeypatch):
    """POST /api/collect with years array creates one queue item per conference x year."""
    data_dir = tmp_path / "data"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "include_ccfddl_catalog": False,
                "conferences": [
                    {"id": "icse", "display_name": "ICSE", "dblp_stream": "conf/icse"},
                    {"id": "fse", "display_name": "FSE", "dblp_stream": "conf/sigsoft"},
                ],
                "years": [2023, 2024],
                "output_dir": str(data_dir),
                "concurrency": {"threads": 1},
            }
        ),
        encoding="utf-8",
    )

    started = threading.Event()
    release = threading.Event()

    def fake_process_conference_year(conf, year, dblp_client, metadata_manager, output_dir, limit):
        if not started.is_set():
            started.set()
            assert release.wait(timeout=2)
        data_dir.mkdir(exist_ok=True)
        output_path = get_output_path(str(data_dir), conf, year)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump([{"title": f"{conf.display_name} {year}", "authors": [], "venue": conf.display_name, "year": year}], f)

    monkeypatch.setattr("src.web.workers.collection.process_conference_year", fake_process_conference_year)

    client = create_app(str(config_path)).test_client()
    response = client.post(
        "/api/collect",
        json={"conferences": ["icse", "fse"], "years": [2024, 2025], "limit": 1},
    )

    assert response.status_code == 202
    status_url = response.get_json()["status_url"]
    assert started.wait(timeout=2)

    job = client.get(status_url).get_json()
    queue = job.get("queue")
    assert queue is not None
    assert len(queue) == 4  # 2 conferences x 2 years

    # Check each item has a year field.
    task_keys = sorted((item["conference_id"], item["year"]) for item in queue)
    assert task_keys == [("fse", 2024), ("fse", 2025), ("icse", 2024), ("icse", 2025)]

    release.set()
    for _ in range(40):
        status = client.get(status_url).get_json()
        if status["status"] in {"completed", "failed"}:
            break
        time.sleep(0.05)

    assert status["status"] == "completed"
    assert status["completed_count"] == 4
    assert status["paper_count"] == 4
    assert len(status["feed_urls"]) == 4


def test_collect_with_explicit_tasks_creates_exact_queue_items(tmp_path, monkeypatch):
    """POST /api/collect with tasks creates only the requested conference/year pairs."""
    data_dir = tmp_path / "data"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "include_ccfddl_catalog": False,
                "conferences": [
                    {"id": "icse", "display_name": "ICSE", "dblp_stream": "conf/icse"},
                    {"id": "fse", "display_name": "FSE", "dblp_stream": "conf/sigsoft"},
                ],
                "years": [2024, 2025],
                "output_dir": str(data_dir),
                "concurrency": {"threads": 1},
            }
        ),
        encoding="utf-8",
    )

    started = threading.Event()
    release = threading.Event()

    def fake_process_conference_year(conf, year, dblp_client, metadata_manager, output_dir, limit):
        if not started.is_set():
            started.set()
            assert release.wait(timeout=2)
        data_dir.mkdir(exist_ok=True)
        output_path = get_output_path(str(data_dir), conf, year)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump([{"title": f"{conf.display_name} {year}", "authors": [], "venue": conf.display_name, "year": year}], f)

    monkeypatch.setattr("src.web.workers.collection.process_conference_year", fake_process_conference_year)

    client = create_app(str(config_path)).test_client()
    response = client.post(
        "/api/collect",
        json={
            "tasks": [
                {"conference": "icse", "year": 2024},
                {"conference": "fse", "year": 2025},
            ],
            "limit": 1,
        },
    )

    assert response.status_code == 202
    status_url = response.get_json()["status_url"]
    assert started.wait(timeout=2)

    job = client.get(status_url).get_json()
    queue = job.get("queue")
    assert queue is not None
    assert len(queue) == 2
    assert [(item["conference_id"], item["year"]) for item in queue] == [
        ("icse", 2024),
        ("fse", 2025),
    ]

    release.set()
    for _ in range(40):
        status = client.get(status_url).get_json()
        if status["status"] in {"completed", "failed"}:
            break
        time.sleep(0.05)

    assert status["status"] == "completed"
    assert status["completed_count"] == 2
    assert status["paper_count"] == 2
    assert len(status["feed_urls"]) == 2


def test_collect_with_single_year_backward_compatible(tmp_path, monkeypatch):
    """POST /api/collect with single year field still works (backward compatibility)."""
    data_dir = tmp_path / "data"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "include_ccfddl_catalog": False,
                "conferences": [
                    {"id": "icse", "display_name": "ICSE", "dblp_stream": "conf/icse"},
                ],
                "years": [2025],
                "output_dir": str(data_dir),
                "concurrency": {"threads": 1},
            }
        ),
        encoding="utf-8",
    )

    def fake_process_conference_year(conf, year, dblp_client, metadata_manager, output_dir, limit):
        data_dir.mkdir(exist_ok=True)
        output_path = get_output_path(str(data_dir), conf, year)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump([{"title": "ICSE Paper", "authors": [], "venue": "ICSE", "year": year}], f)

    monkeypatch.setattr("src.web.workers.collection.process_conference_year", fake_process_conference_year)

    client = create_app(str(config_path)).test_client()
    # Use "year" (single value) instead of "years" (array).
    response = client.post(
        "/api/collect",
        json={"conferences": ["icse"], "year": 2025, "limit": 1},
    )

    assert response.status_code == 202
    status_url = response.get_json()["status_url"]

    for _ in range(40):
        status = client.get(status_url).get_json()
        if status["status"] == "completed":
            break
        time.sleep(0.05)

    assert status["status"] == "completed"
    assert status["completed_count"] == 1
    queue = status["queue"]
    assert len(queue) == 1
    assert queue[0]["year"] == 2025


def test_collect_years_array_rejects_empty_years(tmp_path):
    """POST /api/collect with empty years array returns 400."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "include_ccfddl_catalog": False,
                "conferences": [{"id": "icse", "display_name": "ICSE", "dblp_stream": "conf/icse"}],
                "years": [2025],
            }
        ),
        encoding="utf-8",
    )

    client = create_app(str(config_path)).test_client()
    response = client.post(
        "/api/collect",
        json={"conferences": ["icse"], "years": [], "limit": 1},
    )

    # Empty years array falls through to missing "year" field.
    assert response.status_code == 400


def test_queue_items_have_year_field(tmp_path, monkeypatch):
    """Queue items in the job response include a year field."""
    config_path = _make_queue_config(tmp_path, [
        {"id": "icse", "display_name": "ICSE", "dblp_stream": "conf/icse"},
    ])

    started = threading.Event()
    release = threading.Event()

    def fake_process_conference_year(conf, year, dblp_client, metadata_manager, output_dir, limit):
        if not started.is_set():
            started.set()
            assert release.wait(timeout=2)

    monkeypatch.setattr("src.web.workers.collection.process_conference_year", fake_process_conference_year)

    client = create_app(str(config_path)).test_client()
    response = client.post(
        "/api/collect",
        json={"conferences": ["icse"], "years": [2025], "limit": 1},
    )

    assert response.status_code == 202
    status_url = response.get_json()["status_url"]
    assert started.wait(timeout=2)

    job = client.get(status_url).get_json()
    queue = job.get("queue")
    assert queue is not None
    assert len(queue) == 1
    assert queue[0]["year"] == 2025
    assert queue[0]["conference_id"] == "icse"

    release.set()
    for _ in range(20):
        time.sleep(0.05)
        if client.get(status_url).get_json()["status"] in {"completed", "failed"}:
            break


def test_multi_year_queue_worker_processes_each_pair(tmp_path, monkeypatch):
    """The worker processes each conference x year pair independently."""
    data_dir = tmp_path / "data"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "include_ccfddl_catalog": False,
                "conferences": [
                    {"id": "icse", "display_name": "ICSE", "dblp_stream": "conf/icse"},
                ],
                "years": [2024, 2025],
                "output_dir": str(data_dir),
                "concurrency": {"threads": 1},
            }
        ),
        encoding="utf-8",
    )

    calls = []

    def fake_process_conference_year(conf, year, dblp_client, metadata_manager, output_dir, limit):
        calls.append((conf.id, year))
        data_dir.mkdir(exist_ok=True)
        output_path = get_output_path(str(data_dir), conf, year)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump([{"title": f"{conf.display_name} {year}", "authors": [], "venue": conf.display_name, "year": year}], f)

    monkeypatch.setattr("src.web.workers.collection.process_conference_year", fake_process_conference_year)

    client = create_app(str(config_path)).test_client()
    response = client.post(
        "/api/collect",
        json={"conferences": ["icse"], "years": [2024, 2025], "limit": 1},
    )

    assert response.status_code == 202
    status_url = response.get_json()["status_url"]

    for _ in range(40):
        status = client.get(status_url).get_json()
        if status["status"] == "completed":
            break
        time.sleep(0.05)

    assert status["status"] == "completed"
    assert sorted(calls) == [("icse", 2024), ("icse", 2025)]
    assert status["completed_count"] == 2
    assert status["paper_count"] == 2
    assert sorted(r["year"] for r in status["results"]) == [2024, 2025]


def test_sync_endpoints_return_503_when_webdav_not_configured(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "include_ccfddl_catalog": False,
                "conferences": [{"id": "icse", "display_name": "ICSE"}],
                "years": [2025],
                "output_dir": str(tmp_path / "data"),
            }
        ),
        encoding="utf-8",
    )

    client = create_app(str(config_path)).test_client()

    status_response = client.get("/api/sync/status")
    assert status_response.status_code == 503
    assert "WebDAV" in status_response.get_json()["error"]

    upload_response = client.post("/api/sync/upload")
    assert upload_response.status_code == 503
    assert "WebDAV" in upload_response.get_json()["error"]


def test_sync_status_and_upload_job_with_mocked_webdav(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "icse_2025.json").write_text("[]", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "include_ccfddl_catalog": False,
                "conferences": [{"id": "icse", "display_name": "ICSE"}],
                "years": [2025],
                "output_dir": str(data_dir),
                "webdav": {
                    "url": "https://webdav.example.test/",
                    "username": "tester",
                    "password": "secret",
                    "remote_path": "/papers",
                },
            }
        ),
        encoding="utf-8",
    )

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
            "remote_files": [{"name": "ndss_2025.json", "size": 42, "modified": "today"}],
        }

    def fake_run_sync_upload_job(job_id, webdav_config, output_dir, remote_path, active_lock, app=None):
        store = app.config["PAPERCOLLECT_JOB_STORE"]
        try:
            store.update(job_id, status="running")
            store.append_log(job_id, "mock sync upload completed", max_lines=500)
            store.update(
                job_id,
                status="completed",
                result={"uploaded": ["icse_2025.json"], "skipped": [], "errors": []},
            )
        finally:
            active_lock.release()

    monkeypatch.setattr("src.web.blueprints.sync.WebDAVClient", DummyWebDAVClient)
    monkeypatch.setattr("src.web.blueprints.sync.sync_status", fake_sync_status)
    monkeypatch.setattr("src.web.blueprints.sync.run_sync_upload_job", fake_run_sync_upload_job)

    client = create_app(str(config_path)).test_client()

    status_response = client.get("/api/sync/status")
    assert status_response.status_code == 200
    status_payload = status_response.get_json()
    assert status_payload["remote_path"] == "/papers"
    assert status_payload["local_only"] == ["icse_2025.json"]
    assert status_payload["remote_only"] == ["ndss_2025.json"]
    assert status_payload["both"] == ["fse_2025.json"]

    upload_response = client.post("/api/sync/upload")
    assert upload_response.status_code == 202
    status_url = upload_response.get_json()["status_url"]

    job = None
    for _ in range(20):
        job = client.get(status_url).get_json()
        if job["status"] == "completed":
            break
        time.sleep(0.05)

    assert job["status"] == "completed"
    assert job["result"]["uploaded"] == ["icse_2025.json"]
    assert "mock sync upload completed" in job["logs"]
