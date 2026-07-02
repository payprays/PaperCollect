import json

from backfill_metadata import enrich_metadata_file


class FakeMetadataManager:
    def enrich_papers(self, papers):
        for paper in papers:
            paper.abstract = f"Abstract for {paper.title}"
            paper.citation_count = 7
            paper.reference_count = 3
            paper.paper_id = f"fake:{paper.title}"
        return papers


def test_enrich_metadata_file_only_attempts_missing_items_and_saves_progress(tmp_path):
    path = tmp_path / "icml_2025.json"
    path.write_text(
        json.dumps(
            [
                {
                    "title": "Missing One",
                    "authors": ["A"],
                    "venue": "ICML",
                    "year": 2025,
                    "abstract": None,
                    "citation_count": None,
                },
                {
                    "title": "Already Complete",
                    "authors": ["B"],
                    "venue": "ICML",
                    "year": 2025,
                    "abstract": "Existing abstract",
                    "citation_count": 5,
                },
                {
                    "title": "Missing Two",
                    "authors": ["C"],
                    "venue": "ICML",
                    "year": 2025,
                    "abstract": "",
                    "citation_count": None,
                },
            ]
        ),
        encoding="utf-8",
    )

    result = enrich_metadata_file(path, FakeMetadataManager(), max_papers=1, chunk_size=1)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert result.total_count == 3
    assert result.missing_before == 2
    assert result.attempted_count == 1
    assert result.completed_count == 1
    assert result.remaining_missing == 1
    assert data[0]["abstract"] == "Abstract for Missing One"
    assert data[0]["citation_count"] == 7
    assert data[0]["source_id"] == "fake:Missing One"
    assert data[1]["abstract"] == "Existing abstract"
    assert data[1]["citation_count"] == 5
    assert data[2]["abstract"] == ""
