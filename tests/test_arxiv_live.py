import unittest
import os
from src.core.models import Paper
from src.clients.arxiv_client import ArxivClient

# 这是一个集成测试，会发送真实网络请求
# 可以通过设置环境变量 SKIP_REAL_NET_TESTS=1 来跳过
@unittest.skipIf(os.environ.get('SKIP_REAL_NET_TESTS'), "Skipping real network tests")
class TestArxivLive(unittest.TestCase):
    def setUp(self):
        self.client = ArxivClient()

    def test_fetch_real_paper_fixdrive(self):
        """
        测试真实连接 ArXiv API 获取 'FIXDRIVE' 论文
        """
        print("\n[Live Test] Connecting to ArXiv API...")
        title = "FIXDRIVE: Automatically Repair"
        paper = Paper(title=title, authors=[], year=2025, venue="Test")
        
        enriched_paper = self.client.enrich_paper(paper)
        
        # 验证确实拿到了数据
        self.assertIsNotNone(enriched_paper.abstract, "Abstract should not be None")
        self.assertIsNotNone(enriched_paper.paper_id, "Paper ID should not be None")
        self.assertIsNotNone(enriched_paper.url, "URL should not be None")
        self.assertTrue(enriched_paper.url and enriched_paper.url.startswith("http"), "URL should start with http")
        
        print(f"Successfully fetched: {enriched_paper.title}")
        print(f"Successfully fetched: {enriched_paper.title}")
        print(f"ID: {enriched_paper.paper_id}")
        print(f"URL: {enriched_paper.url}")
        abstract_preview = (enriched_paper.abstract or "")[:1000]
        print(f"Abstract: {abstract_preview}...")  # Print first 1000 chars of abstract for brevity

if __name__ == '__main__':
    unittest.main()