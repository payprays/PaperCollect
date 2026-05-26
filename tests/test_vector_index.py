import json
import sys
import types

from src.services.paper_search import search_saved_papers
from src.services.vector_index import build_vector_index, search_vector_index, vector_index_status


def test_build_and_search_qdrant_hybrid_index_with_filters(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "ndss_2026.json").write_text(
        json.dumps(
            [
                {
                    "title": "Kubernetes Runtime Security for Cloud Workloads",
                    "authors": ["A. Researcher"],
                    "venue": "NDSS",
                    "year": 2026,
                    "abstract": "We detect attacks against Kubernetes workloads with runtime telemetry.",
                    "url": "https://example.com/k8s",
                    "dblp_key": "conf/ndss/K8s26",
                },
                {
                    "title": "Token Time Bomb",
                    "authors": ["B. Researcher"],
                    "venue": "NDSS",
                    "year": 2026,
                    "abstract": "We evaluate JWT libraries.",
                },
            ]
        ),
        encoding="utf-8",
    )

    config = {
        "include_ccfddl_catalog": False,
        "vector_index": {
            "path": str(tmp_path / "qdrant"),
            "collection": "test_papers",
            "embedding_provider": "hash",
            "dense_size": 64,
        },
        "conferences": [
            {
                "id": "ndss",
                "display_name": "NDSS",
                "category": "SC",
                "focus_tags": ["security", "cloud_native"],
                "tier": {"ccf": "A"},
            }
        ],
    }

    stats = build_vector_index(config, str(data_dir))
    assert stats["paper_count"] == 2

    status = vector_index_status(config)
    assert status["indexed"] is True
    assert status["paper_count"] == 2

    results = search_vector_index(
        config,
        str(data_dir),
        "kubernetes cloud workload security",
        ccf="A",
        focus="cloud_native",
        conferences=["ndss"],
        year=2026,
        limit=5,
    )

    assert results[0]["title"] == "Kubernetes Runtime Security for Cloud Workloads"
    assert results[0]["search_mode"] == "agentic"
    assert results[0]["retrieval_backend"] == "qdrant_hybrid_rrf"
    assert results[0]["provenance"]["dblp_key"] == "conf/ndss/K8s26"
    assert results[0]["score_details"]["fusion"] == "rrf"


def test_agentic_search_falls_back_to_concept_when_index_missing(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "ndss_2026.json").write_text(
        json.dumps(
            [
                {
                    "title": "Image Provenance Policies for Kubernetes Deployments",
                    "authors": ["A. Researcher"],
                    "venue": "NDSS",
                    "year": 2026,
                    "abstract": "We detect malicious container image supply chain attacks with SBOM evidence.",
                    "dblp_key": "conf/ndss/Image26",
                }
            ]
        ),
        encoding="utf-8",
    )
    config = {
        "include_ccfddl_catalog": False,
        "vector_index": {
            "path": str(tmp_path / "missing-qdrant"),
            "collection": "missing_collection",
            "embedding_provider": "hash",
            "dense_size": 64,
        },
        "conferences": [
            {
                "id": "ndss",
                "display_name": "NDSS",
                "category": "SC",
                "focus_tags": ["security", "cloud_native"],
            }
        ],
    }

    results = search_saved_papers(
        config,
        str(data_dir),
        "云原生供应链攻击检测",
        mode="agentic",
        limit=5,
    )

    assert results[0]["title"] == "Image Provenance Policies for Kubernetes Deployments"
    assert results[0]["search_mode"] == "agentic_fallback"
    assert results[0]["retrieval_backend"] == "concept_semantic"
    assert "Run pc-index first" in results[0]["fallback_reason"]


def test_agentic_search_falls_back_when_qdrant_local_path_is_locked(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "ndss_2026.json").write_text(
        json.dumps(
            [
                {
                    "title": "Kubernetes Policy Verification",
                    "authors": ["A. Researcher"],
                    "venue": "NDSS",
                    "year": 2026,
                    "abstract": "A paper about Kubernetes admission control and cluster security.",
                }
            ]
        ),
        encoding="utf-8",
    )
    config = {
        "include_ccfddl_catalog": False,
        "conferences": [{"id": "ndss", "display_name": "NDSS", "category": "SC"}],
    }

    import src.services.vector_index as vector_index

    def raise_locked(*_args, **_kwargs):
        raise RuntimeError("Storage folder data/qdrant is already accessed")

    monkeypatch.setattr(vector_index, "search_vector_index", raise_locked)

    results = search_saved_papers(
        config,
        str(data_dir),
        "kubernetes security",
        mode="agentic",
        limit=5,
    )

    assert results[0]["title"] == "Kubernetes Policy Verification"
    assert results[0]["search_mode"] == "agentic_fallback"
    assert "already accessed" in results[0]["fallback_reason"]


def test_fastembed_provider_is_cached_for_repeated_searches(monkeypatch):
    import src.services.vector_index as vector_index

    vector_index._PROVIDER_CACHE.clear()
    init_calls = []

    class FakeVector:
        def __init__(self, values):
            self._values = values

        def tolist(self):
            return self._values

    class FakeTextEmbedding:
        def __init__(self, model_name, cache_dir=None, threads=None):
            init_calls.append((model_name, cache_dir, threads))

        @staticmethod
        def list_supported_models():
            return [{"model": "dense-test", "dim": 4}]

        def embed(self, texts):
            for _text in texts:
                yield FakeVector([1.0, 0.0, 0.0, 0.0])

        def query_embed(self, _text):
            yield FakeVector([1.0, 0.0, 0.0, 0.0])

    fake_fastembed = types.ModuleType("fastembed")
    fake_fastembed.TextEmbedding = FakeTextEmbedding
    monkeypatch.setitem(sys.modules, "fastembed", fake_fastembed)

    config = {
        "embedding_provider": "fastembed",
        "dense_model": "dense-test",
        "sparse_model": "hash",
    }
    provider = vector_index._embedding_provider(config)
    cached_provider = vector_index._embedding_provider(config)

    assert provider is cached_provider
    assert init_calls == [("dense-test", None, None)]
    vector_index._PROVIDER_CACHE.clear()
