import unittest
from unittest.mock import MagicMock, patch
from src.core.models import Paper
from src.clients.arxiv_client import ArxivClient

class TestArxivClient(unittest.TestCase):
    def setUp(self):
        self.client = ArxivClient()

    @patch('src.clients.arxiv_client.requests.Session.get')
    def test_enrich_paper_success(self, mock_get):
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        # Sample Atom response from ArXiv
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2101.12345</id>
    <title>Test Paper Title</title>
    <summary>This is a test abstract.</summary>
  </entry>
</feed>
"""
        mock_response.content = xml_content.encode('utf-8')
        mock_get.return_value = mock_response

        paper = Paper(title="Test Paper Title", authors=["Author One"], year=2021, venue="Test Venue")
        enriched_paper = self.client.enrich_paper(paper)

        self.assertEqual(enriched_paper.abstract, "This is a test abstract.")
        self.assertEqual(enriched_paper.paper_id, "2101.12345")
        self.assertEqual(enriched_paper.url, "http://arxiv.org/abs/2101.12345")

    @patch('src.clients.arxiv_client.requests.Session.get')
    def test_enrich_paper_cleaning(self, mock_get):
        # Test that title is cleaned correctly
        mock_response = MagicMock()
        mock_response.status_code = 200
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
</feed>
"""
        mock_response.content = xml_content.encode('utf-8')
        mock_get.return_value = mock_response

        # Title with special chars and HTML entities
        paper = Paper(title="FixDrive: &apos;Automatically&apos; Repair", authors=[], year=2025, venue="ICSE")
        self.client.enrich_paper(paper)

        # Check call args
        args, kwargs = mock_get.call_args
        params = kwargs['params']
        # Expected: "FixDrive Automatically Repair" (with hyphens kept if logic allows, or spaces)
        # My logic was: clean_title = re.sub(r'[^a-zA-Z0-9\s\-]', ' ', clean_title)
        # &apos; becomes ' which is removed. : is removed.
        # "FixDrive 'Automatically' Repair" -> "FixDrive  Automatically  Repair" -> "FixDrive Automatically Repair"
        self.assertIn('ti:"FixDrive Automatically Repair"', params['search_query'])

    @patch('src.clients.arxiv_client.requests.Session.get')
    def test_enrich_paper_not_found(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
</feed>
"""
        mock_response.content = xml_content.encode('utf-8')
        mock_get.return_value = mock_response

        paper = Paper(title="Nonexistent Paper", authors=[], year=2021, venue="Test")
        enriched_paper = self.client.enrich_paper(paper)

        self.assertIsNone(enriched_paper.abstract)


if __name__ == '__main__':
    unittest.main()
