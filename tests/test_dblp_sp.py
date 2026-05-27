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
        self.assertEqual(mock_get.call_args_list[1].kwargs["params"]["q"], "venue:NeurIPS year:2025")

    @patch('src.clients.dblp_client.requests.Session.get')
    def test_search_paginates_beyond_dblp_page_size(self, mock_get):
        first_page = {
            "result": {
                "hits": {
                    "@total": "1001",
                    "@sent": "1000",
                    "@first": "0",
                    "hit": [_search_hit(index) for index in range(1000)],
                }
            }
        }
        second_page = {
            "result": {
                "hits": {
                    "@total": "1001",
                    "@sent": "1",
                    "@first": "1000",
                    "hit": [_search_hit(1000)],
                }
            }
        }
        mock_get.side_effect = [
            _mock_json_response(first_page),
            _mock_json_response(second_page),
        ]

        papers = self.client._fetch_from_search("ICSE", 2025, dblp_stream="conf/icse", venue_aliases=["ICSE"])

        self.assertEqual(len(papers), 1001)
        self.assertEqual([call.kwargs["params"]["f"] for call in mock_get.call_args_list], [0, 1000])
        self.assertTrue(all(call.kwargs["params"]["h"] == 1000 for call in mock_get.call_args_list))

    @patch('src.clients.dblp_client.requests.Session.get')
    def test_fetch_papers_raises_when_search_request_fails(self, mock_get):
        mock_get.side_effect = requests.Timeout("read timed out")

        with self.assertRaisesRegex(DBLPFetchError, "Could not fetch DBLP search data"):
            self.client.fetch_papers("NDSS", 2026)

if __name__ == '__main__':
    unittest.main()
