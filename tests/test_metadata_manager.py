import unittest
from unittest.mock import MagicMock, patch
from src.core.models import Paper
from src.services.metadata_manager import MetadataManager
from src.core.exceptions import RateLimitException

class TestMetadataManager(unittest.TestCase):
    def setUp(self):
        self.manager = MetadataManager(threads=1)
        # Mock the sources list to avoid real calls and control behavior
        self.mock_source1 = MagicMock()
        self.mock_source2 = MagicMock()
        self.manager.sources = [self.mock_source1, self.mock_source2]

    def test_enrich_single_paper_success_first_source(self):
        paper = Paper(title="Test Paper", authors=[], year=2021, venue="Test")
        
        # Source 1 returns enriched paper
        def side_effect(p):
            p.abstract = "Abstract found"
            p.citation_count = 10
            return p
        self.mock_source1.enrich_paper.side_effect = side_effect

        result = self.manager._enrich_single_paper(paper)
        
        self.assertEqual(result.abstract, "Abstract found")
        self.mock_source1.enrich_paper.assert_called_once()
        self.mock_source2.enrich_paper.assert_not_called()

    def test_enrich_single_paper_fallback(self):
        paper = Paper(title="Test Paper", authors=[], year=2021, venue="Test")
        
        # Source 1 returns paper without abstract
        self.mock_source1.enrich_paper.return_value = paper
        
        # Source 2 returns enriched paper
        def side_effect(p):
            p.abstract = "Abstract found in source 2"
            p.citation_count = 5
            return p
        self.mock_source2.enrich_paper.side_effect = side_effect

        result = self.manager._enrich_single_paper(paper)
        
        self.assertEqual(result.abstract, "Abstract found in source 2")
        self.mock_source1.enrich_paper.assert_called_once()
        self.mock_source2.enrich_paper.assert_called_once()

    def test_enrich_single_paper_rate_limit(self):
        paper = Paper(title="Test Paper", authors=[], year=2021, venue="Test")
        
        # Source 1 raises RateLimitException
        self.mock_source1.enrich_paper.side_effect = RateLimitException("Rate limit")
        
        # Source 2 returns enriched paper
        def side_effect(p):
            p.abstract = "Abstract found after rate limit"
            return p
        self.mock_source2.enrich_paper.side_effect = side_effect

        result = self.manager._enrich_single_paper(paper)
        
        self.assertEqual(result.abstract, "Abstract found after rate limit")
        self.mock_source1.enrich_paper.assert_called_once()
        self.mock_source2.enrich_paper.assert_called_once()

if __name__ == '__main__':
    unittest.main()
