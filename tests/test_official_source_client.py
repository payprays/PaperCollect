from unittest.mock import MagicMock, patch

from src.clients.official_source_client import OfficialSourceClient
from src.core.conference_catalog import ConferenceEntry


def _json_response(payload, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def _text_response(text, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    response.raise_for_status.return_value = None
    return response


def test_miniconf_source_fetches_posters_and_abstracts_without_oral_duplicates():
    conference = ConferenceEntry(
        id="mlsys",
        display_name="MLSys",
        official_source={
            "type": "miniconf",
            "papers_url": "https://mlsys.org/static/virtual/data/mlsys-{year}-orals-posters.json",
            "abstracts_url": "https://mlsys.org/static/virtual/data/mlsys-{year}-abstracts.json",
            "page_url": "https://mlsys.org/virtual/{year}/papers.html",
            "event_type": "Poster",
        },
    )
    papers_payload = {
        "results": [
            {
                "id": 100,
                "uid": "poster-uid",
                "name": "Blueprint, Bootstrap, and Bridge: A Security Look at GPU Confidential Computing",
                "authors": [{"fullname": "Ada Lovelace"}, {"fullname": "Alan Turing"}],
                "eventtype": "Poster",
                "visible": True,
                "virtualsite_url": "/virtual/2026/poster/100",
            },
            {
                "id": 200,
                "name": "Oral presentation for the same paper",
                "authors": [{"fullname": "Ada Lovelace"}],
                "eventtype": "Oral",
                "visible": True,
            },
        ]
    }
    abstracts_payload = {"100": "We study confidential GPU computing."}

    with patch("src.clients.official_source_client.requests.Session.get") as mock_get:
        mock_get.side_effect = [
            _json_response(papers_payload),
            _json_response(abstracts_payload),
        ]

        papers = OfficialSourceClient().fetch_papers(conference, 2026)

    assert len(papers) == 1
    assert papers[0].title.startswith("Blueprint")
    assert papers[0].authors == ["Ada Lovelace", "Alan Turing"]
    assert papers[0].abstract == "We study confidential GPU computing."
    assert papers[0].url == "https://mlsys.org/virtual/2026/poster/100"
    assert papers[0].paper_id == "official:mlsys:2026:100"
    assert papers[0].source == "official:miniconf"
    assert papers[0].source_url == "https://mlsys.org/virtual/2026/papers.html"


def test_miniconf_source_missing_papers_json_returns_empty_list():
    conference = ConferenceEntry(
        id="mlsys",
        display_name="MLSys",
        official_source={
            "type": "miniconf",
            "papers_url": "https://mlsys.org/static/virtual/data/mlsys-{year}-orals-posters.json",
        },
    )

    with patch("src.clients.official_source_client.requests.Session.get") as mock_get:
        mock_get.return_value = _json_response({}, status_code=404)

        assert OfficialSourceClient().fetch_papers(conference, 2026) == []


def test_ieee_sp_accepted_source_parses_static_accepted_papers_html():
    conference = ConferenceEntry(
        id="sp",
        display_name="IEEE S&P",
        official_source={
            "type": "ieee_sp_accepted",
            "page_url": "https://sp{year}.ieee-security.org/accepted-papers.html",
        },
    )
    html = """
    <div role="tabpanel" class="tab-pane active" id="cycle1"><div class="list-group-item">
      <b><a data-toggle="collapse" href="#collapse-0">Bridge: High-Order Taint Vulnerabilities Detection <span></span></a></b><br />
      <div class="collapse authorlist" id="collapse-0">
        Jiaqian Peng<sup>1,2</sup>, Puzhuo Liu<sup>3</sup>, Yicheng Zeng<sup>1</sup><br />
        <sup>1</sup>: Institute A, <sup>3</sup>: Institute B
      </div>
    </div>
    <div class="list-group-item">
      <b><a data-toggle="collapse" href="#collapse-1">Camveil: Multi-Protocol Coordinated Fuzzing <span></span></a></b><br />
      <div class="collapse authorlist" id="collapse-1">
        Fuchen Ma<sup>1</sup>, Yuqiao Yang<sup>2</sup><br />
        <sup>1</sup>: Tsinghua University
      </div>
    </div></div>
    """

    with patch("src.clients.official_source_client.requests.Session.get") as mock_get:
        mock_get.return_value = _text_response(html)

        papers = OfficialSourceClient().fetch_papers(conference, 2026)

    assert len(papers) == 2
    assert papers[0].title == "Bridge: High-Order Taint Vulnerabilities Detection"
    assert papers[0].authors == ["Jiaqian Peng", "Puzhuo Liu", "Yicheng Zeng"]
    assert papers[0].url == "https://sp2026.ieee-security.org/accepted-papers.html#collapse-0"
    assert papers[0].paper_id == "official:sp:2026:collapse-0"
    assert papers[0].source == "official:ieee_sp_accepted"
    assert papers[0].source_url == "https://sp2026.ieee-security.org/accepted-papers.html"
    assert papers[1].authors == ["Fuchen Ma", "Yuqiao Yang"]


def test_ieee_sp_accepted_source_missing_page_returns_empty_list():
    conference = ConferenceEntry(
        id="sp",
        display_name="IEEE S&P",
        official_source={
            "type": "ieee_sp_accepted",
            "page_url": "https://sp{year}.ieee-security.org/accepted-papers.html",
        },
    )

    with patch("src.clients.official_source_client.requests.Session.get") as mock_get:
        mock_get.return_value = _text_response("", status_code=404)

        assert OfficialSourceClient().fetch_papers(conference, 2026) == []


def test_researchr_accepted_source_parses_event_overview_table():
    conference = ConferenceEntry(
        id="fse",
        display_name="FSE",
        official_source={
            "type": "researchr_accepted",
            "page_url": "https://conf.researchr.org/track/fse-{year}/fse-{year}-research-papers",
        },
    )
    html = """
    <div id="event-overview" class="tab-pane ">
      <h3>Accepted Papers</h3>
      <table>
        <tr><td></td><td>
          <a href="#" data-event-modal="event-1">Accelerating Policy Synthesis</a>
          <div class="prog-track">Research Papers</div>
          <div class="performers">
            <a href="/profile/fse-2026/alexandros">Alexandros Evangelidis</a>,
            <a href="/profile/fse-2026/gricel">Gricel Vazquez</a>
          </div>
          <a href="https://arxiv.org/abs/2506.17792" class="publication-link navigate">Pre-print</a>
          <a href="https://conf.researchr.org/details/fse-2026/fse-2026-research-papers/185/title" class="publication-link navigate">File Attached</a>
        </td></tr>
        <tr><td></td><td>
          <a href="#" data-event-modal="event-2">AccessDroid</a>
          <div class="performers"><a href="/profile/fse-2026/ada">Ada Lovelace</a></div>
        </td></tr>
      </table>
    </div>
    <div id="Call-for-Papers"><h2>Call for Papers</h2></div>
    """

    with patch("src.clients.official_source_client.requests.Session.get") as mock_get:
        mock_get.return_value = _text_response(html)

        papers = OfficialSourceClient().fetch_papers(conference, 2026)

    assert len(papers) == 2
    assert papers[0].title == "Accelerating Policy Synthesis"
    assert papers[0].authors == ["Alexandros Evangelidis", "Gricel Vazquez"]
    assert papers[0].url == "https://conf.researchr.org/details/fse-2026/fse-2026-research-papers/185/title"
    assert papers[0].paper_id == "official:fse:2026:event-1"
    assert papers[0].source == "official:researchr_accepted"
    assert papers[0].source_url == "https://conf.researchr.org/track/fse-2026/fse-2026-research-papers"
    assert papers[1].url == "https://conf.researchr.org/track/fse-2026/fse-2026-research-papers#event-2"


def test_researchr_accepted_source_without_accepted_tab_returns_empty_list():
    conference = ConferenceEntry(
        id="ase",
        display_name="ASE",
        official_source={
            "type": "researchr_accepted",
            "page_url": "https://conf.researchr.org/track/ase-{year}/ase-{year}-research-track",
        },
    )

    with patch("src.clients.official_source_client.requests.Session.get") as mock_get:
        mock_get.return_value = _text_response("<h2>Call for Papers</h2>")

        assert OfficialSourceClient().fetch_papers(conference, 2026) == []
