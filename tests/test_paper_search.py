import json

from src.services.paper_search import search_saved_papers


def test_search_saved_papers_filters_by_category_and_query(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "ICSE_2025.json").write_text(
        json.dumps(
            [
                {
                    "title": "Neural Program Repair",
                    "authors": ["A. Researcher"],
                    "venue": "ICSE",
                    "year": 2025,
                    "abstract": "A paper about program repair with neural methods.",
                    "url": "https://example.com/repair",
                },
                {
                    "title": "Storage Systems",
                    "authors": ["B. Researcher"],
                    "venue": "ICSE",
                    "year": 2025,
                    "abstract": "A systems paper.",
                },
            ]
        ),
        encoding="utf-8",
    )

    config = {
        "include_ccfddl_catalog": False,
        "conferences": [
            {
                "id": "icse",
                "display_name": "ICSE",
                "category": "SE",
                "dblp_stream": "conf/icse",
            }
        ],
    }

    results = search_saved_papers(
        config,
        str(data_dir),
        "program repair",
        category="SE",
        limit=10,
    )

    assert len(results) == 1
    assert results[0]["title"] == "Neural Program Repair"
    assert results[0]["conference"] == "icse"
    assert results[0]["category"] == "SE"


def test_search_saved_papers_filters_by_focus_tag(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "SoCC_2025.json").write_text(
        json.dumps(
            [
                {
                    "title": "Serverless Scheduling",
                    "authors": ["A. Researcher"],
                    "venue": "SoCC",
                    "year": 2025,
                    "abstract": "A cloud native systems paper.",
                }
            ]
        ),
        encoding="utf-8",
    )

    config = {
        "include_ccfddl_catalog": False,
        "conferences": [
            {
                "id": "socc",
                "display_name": "SoCC",
                "category": "DS",
                "focus_tags": ["cloud_native"],
                "dblp_stream": "conf/cloud",
            }
        ],
    }

    results = search_saved_papers(
        config,
        str(data_dir),
        "serverless",
        focus="cloud_native",
        limit=10,
    )

    assert len(results) == 1
    assert "cloud_native" in results[0]["focus_tags"]


def test_search_saved_papers_keyword_mode_matches_conference_metadata(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "usenix-atc_2025.json").write_text(
        json.dumps(
            [
                {
                    "title": "SpaceExit",
                    "authors": ["A. Researcher"],
                    "venue": "USENIX ATC",
                    "year": 2025,
                    "abstract": "Adaptive computing with early exits.",
                }
            ]
        ),
        encoding="utf-8",
    )

    config = {
        "include_ccfddl_catalog": False,
        "conferences": [
            {
                "id": "usenix-atc",
                "display_name": "USENIX ATC",
                "full_name": "USENIX Annual Technical Conference",
                "aliases": ["ATC", "SIGOPS ATC"],
                "category": "DS",
                "focus_tags": ["distributed_systems", "cloud_native"],
                "dblp_stream": "conf/usenix",
            }
        ],
    }

    results = search_saved_papers(
        config,
        str(data_dir),
        "USENIX ATC",
        limit=10,
        mode="keyword",
    )

    assert len(results) == 1
    assert results[0]["conference"] == "usenix-atc"
    assert results[0]["display_name"] == "USENIX ATC"


def test_search_saved_papers_concept_mode_expands_scientific_concepts(tmp_path):
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
                },
                {
                    "title": "Neural Program Repair",
                    "authors": ["B. Researcher"],
                    "venue": "NDSS",
                    "year": 2026,
                    "abstract": "A paper about fixing programming errors.",
                },
            ]
        ),
        encoding="utf-8",
    )

    config = {
        "include_ccfddl_catalog": False,
        "conferences": [
            {
                "id": "ndss",
                "display_name": "NDSS",
                "category": "SC",
                "focus_tags": ["security", "cloud_native", "cloud_security"],
                "dblp_stream": "conf/ndss",
            }
        ],
    }

    results = search_saved_papers(
        config,
        str(data_dir),
        "云原生供应链攻击检测",
        mode="concept",
        limit=10,
    )

    assert results[0]["title"] == "Image Provenance Policies for Kubernetes Deployments"
    assert "Cloud Native" in results[0]["matched_concepts"]
    assert "Software Supply Chain" in results[0]["matched_concepts"]
    assert "Vulnerability Detection" in results[0]["matched_concepts"]


def test_search_saved_papers_keyword_mode_does_not_expand_concepts(tmp_path):
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

    config = {
        "include_ccfddl_catalog": False,
        "conferences": [{"id": "ndss", "display_name": "NDSS", "dblp_stream": "conf/ndss"}],
    }

    results = search_saved_papers(
        config,
        str(data_dir),
        "云原生供应链攻击检测",
        mode="keyword",
        limit=10,
    )

    assert results == []


def test_search_saved_papers_normalizes_underscore_queries(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "ICSE_2025.json").write_text(
        json.dumps(
            [
                {
                    "title": "Software Testing for Cloud Applications",
                    "authors": ["A. Researcher"],
                    "venue": "ICSE",
                    "year": 2025,
                    "abstract": "A paper about software testing techniques.",
                }
            ]
        ),
        encoding="utf-8",
    )

    config = {
        "include_ccfddl_catalog": False,
        "conferences": [{"id": "icse", "display_name": "ICSE", "dblp_stream": "conf/icse"}],
    }

    results = search_saved_papers(
        config,
        str(data_dir),
        "software_testing",
        mode="keyword",
        limit=10,
    )

    assert len(results) == 1
    assert results[0]["title"] == "Software Testing for Cloud Applications"


def test_search_saved_papers_filters_noise_entries(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "SP_2025.json").write_text(
        json.dumps(
            [
                {
                    "title": "POSTER: Kubernetes RBAC Permission Scanner",
                    "authors": ["A. Researcher"],
                    "venue": "SP",
                    "year": 2025,
                    "abstract": "A poster about Kubernetes security.",
                },
                {
                    "title": "Proceedings of the 2025 Security Symposium",
                    "authors": ["B. Researcher"],
                    "venue": "SP",
                    "year": 2025,
                    "abstract": "Proceedings front matter.",
                },
                {
                    "title": "38th IEEE/ACM International Conference on Automated Software Engineering, ASE 2023, Luxembourg, September 11-15, 2023",
                    "authors": ["D. Researcher"],
                    "venue": "ASE",
                    "year": 2023,
                    "abstract": "Conference volume metadata.",
                },
                {
                    "title": "KubeFence: Security Hardening of the Kubernetes Attack Surface",
                    "authors": ["C. Researcher"],
                    "venue": "SP",
                    "year": 2025,
                    "abstract": "We harden Kubernetes cluster policies and RBAC permissions.",
                },
            ]
        ),
        encoding="utf-8",
    )

    config = {
        "include_ccfddl_catalog": False,
        "conferences": [{"id": "sp", "display_name": "SP", "dblp_stream": "conf/sp"}],
    }

    results = search_saved_papers(
        config,
        str(data_dir),
        "kubernetes policy hardening",
        mode="concept",
        limit=10,
    )

    assert [result["title"] for result in results] == [
        "KubeFence: Security Hardening of the Kubernetes Attack Surface"
    ]


def test_search_saved_papers_concept_mode_uses_expanded_bm25_for_paraphrase(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "ICSE_2025.json").write_text(
        json.dumps(
            [
                {
                    "title": "Query Provenance Analysis for Black-Box Attacks",
                    "authors": ["A. Researcher"],
                    "venue": "ICSE",
                    "year": 2025,
                    "abstract": "We study provenance in query-based attacks.",
                },
                {
                    "title": "What are Weak Links in the npm Supply Chain?",
                    "authors": ["B. Researcher"],
                    "venue": "ICSE",
                    "year": 2025,
                    "abstract": "We analyze third-party package provenance, package registries, build pipelines, and SBOM evidence.",
                },
            ]
        ),
        encoding="utf-8",
    )

    config = {
        "include_ccfddl_catalog": False,
        "conferences": [{"id": "icse", "display_name": "ICSE", "dblp_stream": "conf/icse"}],
    }

    results = search_saved_papers(
        config,
        str(data_dir),
        "third-party package provenance and build pipeline risk",
        mode="concept",
        limit=10,
    )

    assert results[0]["title"] == "What are Weak Links in the npm Supply Chain?"
    assert "Software Supply Chain" in results[0]["matched_concepts"]
    assert results[0]["lexical_score"] > 0


def test_search_saved_papers_concept_mode_filters_incidental_abstract_mentions(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "NDSS_2026.json").write_text(
        json.dumps(
            [
                {
                    "title": "Breaking the Bulkhead: Demystifying Cross-Namespace Reference Vulnerabilities in Kubernetes Operators",
                    "authors": ["A. Researcher"],
                    "venue": "NDSS",
                    "year": 2026,
                    "abstract": "We study Kubernetes operators, cluster isolation, and namespace references.",
                },
                {
                    "title": "Token Time Bomb: Evaluating JWT Implementations for Vulnerability Discovery",
                    "authors": ["B. Researcher"],
                    "venue": "NDSS",
                    "year": 2026,
                    "abstract": "We study JWT libraries and mention authentication bypass in Kubernetes as one impact example.",
                },
            ]
        ),
        encoding="utf-8",
    )

    config = {
        "include_ccfddl_catalog": False,
        "conferences": [{"id": "ndss", "display_name": "NDSS", "dblp_stream": "conf/ndss"}],
    }

    results = search_saved_papers(
        config,
        str(data_dir),
        "kubernetes",
        year=2026,
        mode="concept",
        limit=10,
    )

    assert [result["title"] for result in results] == [
        "Breaking the Bulkhead: Demystifying Cross-Namespace Reference Vulnerabilities in Kubernetes Operators"
    ]


def test_search_saved_papers_treats_query_year_as_filter(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "NDSS_2026.json").write_text(
        json.dumps(
            [
                {
                    "title": "Breaking the Bulkhead: Demystifying Cross-Namespace Reference Vulnerabilities in Kubernetes Operators",
                    "authors": ["A. Researcher"],
                    "venue": "NDSS",
                    "year": 2026,
                    "abstract": "We study Kubernetes operators and namespace references.",
                }
            ]
        ),
        encoding="utf-8",
    )
    (data_dir / "SP_2025.json").write_text(
        json.dumps(
            [
                {
                    "title": "KubeFence: Security Hardening of the Kubernetes Attack Surface",
                    "authors": ["B. Researcher"],
                    "venue": "SP",
                    "year": 2025,
                    "abstract": "We study Kubernetes policies.",
                }
            ]
        ),
        encoding="utf-8",
    )

    config = {
        "include_ccfddl_catalog": False,
        "conferences": [
            {"id": "ndss", "display_name": "NDSS", "dblp_stream": "conf/ndss"},
            {"id": "sp", "display_name": "SP", "dblp_stream": "conf/sp"},
        ],
    }

    results = search_saved_papers(
        config,
        str(data_dir),
        "kubernetes 2026",
        mode="concept",
        limit=10,
    )

    assert [result["title"] for result in results] == [
        "Breaking the Bulkhead: Demystifying Cross-Namespace Reference Vulnerabilities in Kubernetes Operators"
    ]
    assert results[0]["year"] == 2026


def test_search_saved_papers_keeps_legitimate_committee_sampling_paper(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "ndss_2026.json").write_text(
        json.dumps(
            [
                {
                    "title": "Program Committee",
                    "authors": [],
                    "venue": "NDSS",
                    "year": 2026,
                },
                {
                    "title": "Pando: Extremely Scalable BFT Based on Committee Sampling.",
                    "authors": ["A. Researcher"],
                    "venue": "NDSS",
                    "year": 2026,
                    "abstract": "We study scalable BFT committee sampling.",
                },
            ]
        ),
        encoding="utf-8",
    )

    config = {
        "include_ccfddl_catalog": False,
        "conferences": [{"id": "ndss", "display_name": "NDSS", "dblp_stream": "conf/ndss"}],
    }

    results = search_saved_papers(config, str(data_dir), "committee sampling", limit=10)

    assert [result["title"] for result in results] == [
        "Pando: Extremely Scalable BFT Based on Committee Sampling."
    ]
