import json
import sys

import yaml

from search_papers import main


def test_pc_search_uses_local_concept_search_without_openai_or_embeddings(tmp_path, monkeypatch, capsys):
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
                    "url": "https://example.com/kubernetes",
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
                    }
                ],
                "output_dir": str(data_dir),
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pc-search",
            "kubernetes security",
            "--config",
            str(config_path),
            "--top_k",
            "1",
        ],
    )

    main()

    output = capsys.readouterr().out
    assert "Top 1 agentic results" in output
    assert "Image Provenance Policies for Kubernetes Deployments" in output
    assert "concepts:" in output
    assert not (data_dir / "embeddings.pkl").exists()


def test_pc_search_accepts_legacy_ask_mode_as_concept_alias(tmp_path, monkeypatch, capsys):
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
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "include_ccfddl_catalog": False,
                "conferences": [{"id": "ndss", "display_name": "NDSS", "category": "SC"}],
                "output_dir": str(data_dir),
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["pc-search", "kubernetes", "--config", str(config_path), "--mode", "ask"],
    )

    main()

    output = capsys.readouterr().out
    assert "Top 1 concept results" in output
    assert "Kubernetes Policy Verification" in output
