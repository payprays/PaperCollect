import json
from xml.etree import ElementTree as ET

from src.services.rss_service import build_rss_xml, load_papers


def test_build_rss_xml_escapes_and_includes_paper_fields():
    xml = build_rss_xml(
        [
            {
                "title": "A & B",
                "authors": ["Ada Lovelace", "Alan Turing"],
                "venue": "ICSE",
                "year": 2025,
                "abstract": "Testing <RSS> generation.",
                "url": "https://example.com/paper",
                "dblp_key": "conf/icse/example",
            }
        ],
        "ICSE",
        2025,
        "http://localhost/feed/ICSE/2025.xml",
    )

    root = ET.fromstring(xml)
    channel = root.find("channel")
    assert channel is not None
    assert channel.findtext("title") == "PaperCollect: ICSE 2025"

    item = channel.find("item")
    assert item is not None
    assert item.findtext("title") == "A & B"
    assert item.findtext("link") == "https://example.com/paper"
    assert "Ada Lovelace" in (item.findtext("description") or "")
    assert "Testing <RSS> generation." in (item.findtext("description") or "")


def test_load_papers_filters_non_paper_metadata_entries(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "esorics_2026.json").write_text(
        json.dumps(
            [
                {
                    "title": "Computer Security - ESORICS 2025 - 30th European Symposium on Research in Computer Security, Proceedings, Part I",
                    "authors": ["Editor"],
                    "venue": ["ESORICS", "Lecture Notes in Computer Science"],
                    "year": 2026,
                },
                {
                    "title": "Cloud-Native Access Control for Microservices",
                    "authors": ["A. Researcher"],
                    "venue": "ESORICS",
                    "year": 2026,
                },
            ]
        ),
        encoding="utf-8",
    )

    papers = load_papers(str(data_dir), "esorics", 2026)

    assert [paper["title"] for paper in papers] == [
        "Cloud-Native Access Control for Microservices"
    ]
