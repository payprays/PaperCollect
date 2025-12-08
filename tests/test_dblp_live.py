import unittest
import os
from src.clients.dblp_client import DBLPClient

@unittest.skipIf(os.environ.get('SKIP_REAL_NET_TESTS'), "Skipping real network tests")
class TestDBLPLive(unittest.TestCase):
    def setUp(self):
        self.client = DBLPClient()

    def test_fetch_real_sp_papers(self):
        """
        测试真实连接 DBLP API 获取 SP 论文，验证是否过滤了杂质。
        尝试获取 2024 或 2025 年的论文。
        """
        print("\n[Live Test] Fetching SP papers from DBLP...")
        
        # 尝试获取 2024 年的数据（比较稳定），或者用户提到的 2025
        # 为了验证修复效果，我们需要确保结果中没有 ESORICS
        year = 2024 
        papers = self.client.fetch_papers("SP", year)
        
        print(f"Found {len(papers)} papers for SP {year}")
        
        self.assertTrue(len(papers) > 0, f"Should find some papers for SP {year}")

        # 检查是否混入了 ESORICS
        esorics_count = 0
        sp_count = 0
        other_count = 0
        
        for p in papers:
            # DBLP key for SP usually starts with 'conf/sp/'
            # DBLP key for ESORICS usually starts with 'conf/esorics/'
            if p.dblp_key and 'conf/sp/' in p.dblp_key:
                sp_count += 1
            elif p.dblp_key and 'conf/esorics/' in p.dblp_key:
                esorics_count += 1
                print(f"Found Pollution: {p.title} ({p.dblp_key})")
            else:
                other_count += 1
                # print(f"Other: {p.title} ({p.dblp_key})")

        print(f"SP papers (conf/sp/): {sp_count}")
        print(f"ESORICS papers (Pollution): {esorics_count}")
        print(f"Other papers: {other_count}")

        self.assertEqual(esorics_count, 0, "Should not have ESORICS papers in SP results")
        self.assertTrue(sp_count > 0, "Should have actual SP papers")

if __name__ == '__main__':
    unittest.main()
