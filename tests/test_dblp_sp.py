import unittest
from unittest.mock import MagicMock, patch
from src.clients.dblp_client import DBLPClient

class TestDBLPClientSP(unittest.TestCase):
    def setUp(self):
        self.client = DBLPClient()

    @patch('src.clients.dblp_client.requests.Session.get')
    def test_fetch_papers_sp_query_construction(self, mock_get):
        """
        测试当 conference='SP' 时，是否生成了正确的 DBLP 查询语句
        """
        # Mock 一个空的响应，因为我们只关心请求参数
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": {"hits": {"hit": []}}}
        mock_get.return_value = mock_response

        self.client.fetch_papers("SP", 2022)

        # 验证调用参数
        args, kwargs = mock_get.call_args
        params = kwargs['params']
        
        # 关键断言：查询语句必须包含全称，而不是简单的 venue:sp
        expected_query = "venue:IEEE_Symposium_on_Security_and_Privacy year:2022"
        self.assertEqual(params['q'], expected_query, 
                         f"SP 的查询语句应该是全称，实际为: {params['q']}")

    @patch('src.clients.dblp_client.requests.Session.get')
    def test_fetch_papers_other_conf_query_construction(self, mock_get):
        """
        测试普通会议（如 ICSE）是否仍然使用简写
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": {"hits": {"hit": []}}}
        mock_get.return_value = mock_response

        self.client.fetch_papers("ICSE", 2022)

        args, kwargs = mock_get.call_args
        params = kwargs['params']
        
        expected_query = "venue:ICSE year:2022"
        self.assertEqual(params['q'], expected_query)

if __name__ == '__main__':
    unittest.main()
