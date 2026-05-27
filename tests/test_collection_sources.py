from main import fetch_papers_with_fallback, paper_key
from src.clients.dblp_client import DBLPFetchError
from src.core.conference_catalog import ConferenceEntry
from src.core.models import Paper


class EmptyDBLPClient:
    def fetch_papers(self, *args, **kwargs):
        return []


class OnePaperOfficialClient:
    def fetch_papers(self, conference, year):
        return [
            Paper(
                title="Official Fallback Paper",
                authors=["A. Researcher"],
                year=year,
                venue=conference.display_name,
                paper_id=f"official:{conference.id}:{year}:1",
                source="official:miniconf",
            )
        ]


def test_fetch_papers_with_fallback_uses_official_source_after_empty_dblp():
    conference = ConferenceEntry(
        id="mlsys",
        display_name="MLSys",
        official_source={"type": "miniconf"},
    )

    papers = fetch_papers_with_fallback(
        conference,
        2026,
        EmptyDBLPClient(),
        official_source_client=OnePaperOfficialClient(),
    )

    assert len(papers) == 1
    assert papers[0].source == "official:miniconf"
    assert paper_key(papers[0]) == "official:mlsys:2026:1"


def test_fetch_papers_with_fallback_does_not_use_official_source_when_dblp_has_data():
    class DBLPClientWithPaper:
        def fetch_papers(self, *args, **kwargs):
            return [Paper(title="DBLP Paper", authors=[], year=2026, venue="MLSys", dblp_key="conf/mlsys/x")]

    class FailingOfficialClient:
        def fetch_papers(self, conference, year):
            raise AssertionError("official fallback should not be called")

    conference = ConferenceEntry(
        id="mlsys",
        display_name="MLSys",
        official_source={"type": "miniconf"},
    )

    papers = fetch_papers_with_fallback(
        conference,
        2026,
        DBLPClientWithPaper(),
        official_source_client=FailingOfficialClient(),
    )

    assert len(papers) == 1
    assert papers[0].dblp_key == "conf/mlsys/x"


def test_fetch_papers_with_fallback_uses_official_source_when_dblp_fails():
    class FailingDBLPClient:
        def fetch_papers(self, *args, **kwargs):
            raise DBLPFetchError("DBLP search failed")

    conference = ConferenceEntry(
        id="neurips",
        display_name="NeurIPS",
        official_source={"type": "neurips_proceedings"},
    )

    papers = fetch_papers_with_fallback(
        conference,
        2025,
        FailingDBLPClient(),
        official_source_client=OnePaperOfficialClient(),
    )

    assert len(papers) == 1
    assert papers[0].source == "official:miniconf"
