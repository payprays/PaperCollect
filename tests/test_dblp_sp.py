import unittest
from unittest.mock import MagicMock, patch

import requests

from src.clients.dblp_client import DBLPClient, DBLPFetchError


def _mock_json_response(payload, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    return response


def _mock_text_response(payload: str, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.content = payload.encode("utf-8")
    return response


def _search_hit(index: int, venue: str = "ICSE"):
    return {
        "info": {
            "title": f"Paper {index}.",
            "authors": {"author": [{"text": f"Author {index}"}]},
            "year": "2025",
            "venue": venue,
            "key": f"conf/icse/paper{index}",
            "url": f"https://dblp.org/rec/conf/icse/paper{index}",
        }
    }


class TestDBLPClientSP(unittest.TestCase):
    def setUp(self):
        self.client = DBLPClient()

    @patch('src.clients.dblp_client.requests.Session.get')
    def test_search_uses_stream_query_when_requested(self, mock_get):
        """
        测试当 conference='SP' 时，是否生成了正确的 DBLP 查询语句
        """
        mock_get.return_value = _mock_json_response({"result": {"hits": {"hit": []}}})

        self.client._fetch_from_search("IEEE S&P", 2022, dblp_stream="conf/sp", venue_aliases=["SP"])

        # 验证调用参数
        args, kwargs = mock_get.call_args
        params = kwargs['params']
        
        # 关键断言：SP must use the DBLP stream to avoid venue-name ambiguity.
        expected_query = "stream:conf/sp: year:2022"
        self.assertEqual(params['q'], expected_query, 
                         f"SP 的查询语句应该是全称，实际为: {params['q']}")

    @patch('src.clients.dblp_client.requests.Session.get')
    def test_fetch_papers_other_conf_query_construction(self, mock_get):
        """
        测试普通会议（如 ICSE）是否仍然使用简写
        """
        mock_get.return_value = _mock_json_response({"result": {"hits": {"hit": []}}})

        self.client._fetch_from_search("ICSE", 2022, dblp_stream="conf/icse", venue_aliases=["ICSE"])

        args, kwargs = mock_get.call_args
        params = kwargs['params']
        
        expected_query = "stream:conf/icse: year:2022"
        self.assertEqual(params['q'], expected_query)

    @patch('src.clients.dblp_client.requests.Session.get')
    def test_fetch_papers_uses_toc_when_available(self, mock_get):
        mock_get.return_value = _mock_text_response(
            """
            <bht>
              <dblpcites>
                <r style="ee">
                  <inproceedings key="conf/ndss/example26">
                    <author>Alice Example</author>
                    <title>Cloud Native Security Testing.</title>
                    <year>2026</year>
                    <booktitle>NDSS</booktitle>
                    <ee>https://example.com/paper</ee>
                  </inproceedings>
                </r>
              </dblpcites>
            </bht>
            """
        )

        papers = self.client.fetch_papers("NDSS", 2026, dblp_stream="conf/ndss", venue_aliases=["NDSS"])

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].title, "Cloud Native Security Testing.")
        self.assertEqual(papers[0].dblp_key, "conf/ndss/example26")
        mock_get.assert_called_once()
        self.assertEqual(mock_get.call_args.args[0], "https://dblp.org/db/conf/ndss/ndss2026.xml")

    @patch('src.clients.dblp_client.requests.Session.get')
    def test_fetch_papers_falls_back_to_venue_search_when_stream_toc_missing(self, mock_get):
        mock_get.side_effect = [
            _mock_text_response("", status_code=404),
            _mock_json_response(
                {
                    "result": {
                        "hits": {
                            "hit": [
                                {
                                    "info": {
                                        "title": "NeurIPS Fallback Paper.",
                                        "authors": {"author": [{"text": "A. Researcher"}]},
                                        "year": "2025",
                                        "venue": "NeurIPS",
                                        "key": "conf/nips/example25",
                                        "url": "https://dblp.org/rec/conf/nips/example25",
                                    }
                                }
                            ]
                        }
                    }
                }
            ),
        ]

        papers = self.client.fetch_papers("NeurIPS", 2025, dblp_stream="conf/nips", venue_aliases=["NIPS"])

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].title, "NeurIPS Fallback Paper.")
        self.assertEqual(mock_get.call_args_list[0].args[0], "https://dblp.org/db/conf/nips/neurips2025.xml")
        self.assertEqual(mock_get.call_args_list[1].args[0], "https://dblp.org/search/publ/api")
        self.assertEqual(mock_get.call_args_list[1].kwargs["params"]["q"], "stream:conf/nips: year:2025")

    @patch('src.clients.dblp_client.requests.Session.get')
    def test_fetch_papers_fallback_passes_dblp_stream_to_search(self, mock_get):
        """When TOC returns 404, the search fallback should use stream query, not venue query."""
        mock_get.side_effect = [
            _mock_text_response("", status_code=404),
            _mock_json_response(
                {
                    "result": {
                        "hits": {
                            "hit": [
                                {
                                    "info": {
                                        "title": "OOPSLA Paper.",
                                        "authors": {"author": [{"text": "A. Researcher"}]},
                                        "year": "2023",
                                        "venue": "Proc. ACM Program. Lang.",
                                        "key": "conf/oopsla/example23",
                                        "url": "https://dblp.org/rec/conf/oopsla/example23",
                                    }
                                }
                            ]
                        }
                    }
                }
            ),
        ]

        papers = self.client.fetch_papers(
            "OOPSLA", 2023,
            dblp_stream="conf/oopsla",
            venue_aliases=["OOPSLA", "Proc. ACM Program. Lang."],
        )

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].venue, "Proc. ACM Program. Lang.")
        # Fallback must use stream query, not venue query
        self.assertEqual(mock_get.call_args_list[1].kwargs["params"]["q"], "stream:conf/oopsla: year:2023")

    @patch('src.clients.dblp_client.requests.Session.get')
    def test_stream_search_trusts_stream_scope_over_venue_label(self, mock_get):
        """Stream queries should not drop valid stream records with non-exact venue labels."""
        mock_get.return_value = _mock_json_response(
            {
                "result": {
                    "hits": {
                        "hit": [
                            _search_hit(1, venue="Findings of ACL"),
                            _search_hit(2, venue="ACL (1)"),
                        ]
                    }
                }
            }
        )

        papers = self.client._fetch_from_search("ACL", 2022, dblp_query="stream:conf/acl: year:{year}")

        self.assertEqual(len(papers), 2)

    @patch('src.clients.dblp_client.requests.Session.get')
    def test_search_paginates_beyond_dblp_page_size(self, mock_get):
        requested_page_size = 100
        sent_page_size = 100
        total = 101
        first_page = {
            "result": {
                "hits": {
                    "@total": str(total),
                    "@sent": str(sent_page_size),
                    "@first": "0",
                    "hit": [_search_hit(index) for index in range(sent_page_size)],
                }
            }
        }
        second_page = {
            "result": {
                "hits": {
                    "@total": str(total),
                    "@sent": "1",
                    "@first": str(sent_page_size),
                    "hit": [_search_hit(sent_page_size)],
                }
            }
        }
        mock_get.side_effect = [
            _mock_json_response(first_page),
            _mock_json_response(second_page),
        ]

        papers = self.client._fetch_from_search("ICSE", 2025, dblp_stream="conf/icse", venue_aliases=["ICSE"])

        self.assertEqual(len(papers), 101)
        self.assertEqual([call.kwargs["params"]["f"] for call in mock_get.call_args_list], [0, 100])
        self.assertTrue(all(call.kwargs["params"]["h"] == requested_page_size for call in mock_get.call_args_list))

    @patch('src.clients.dblp_client.requests.Session.get')
    def test_search_raises_when_later_page_fails_instead_of_returning_partial_results(self, mock_get):
        first_page = {
            "result": {
                "hits": {
                    "@total": "101",
                    "@sent": "100",
                    "@first": "0",
                    "hit": [_search_hit(index) for index in range(100)],
                }
            }
        }
        mock_get.side_effect = [
            _mock_json_response(first_page),
            requests.Timeout("read timed out"),
        ]

        with self.assertRaisesRegex(DBLPFetchError, "Could not fetch DBLP search data"):
            self.client._fetch_from_search("ICSE", 2025, dblp_stream="conf/icse", venue_aliases=["ICSE"])

        self.assertEqual([call.kwargs["params"]["f"] for call in mock_get.call_args_list], [0, 100])

    @patch('src.clients.dblp_client.requests.Session.get')
    def test_fetch_papers_raises_when_search_request_fails(self, mock_get):
        mock_get.side_effect = requests.Timeout("read timed out")

        with self.assertRaisesRegex(DBLPFetchError, "Could not fetch DBLP search data"):
            self.client.fetch_papers("NDSS", 2026)

if __name__ == '__main__':
    unittest.main()
