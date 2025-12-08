import requests
import xml.etree.ElementTree as ET
from src.core.models import Paper
from src.core.interfaces import MetadataSource
from src.core.exceptions import RateLimitException

class ArxivClient(MetadataSource):
    """
    Implementation of MetadataSource using the ArXiv API.
    """
    BASE_URL = "http://export.arxiv.org/api/query"

    def enrich_paper(self, paper: Paper) -> Paper:
        # ArXiv search by title
        # We need to be careful with special characters in title
        # Simple cleaning
        clean_title = paper.title.replace(':', ' ').replace('-', ' ')
        query = f'ti:"{clean_title}"'
        params = {
            "search_query": query,
            "start": 0,
            "max_results": 1
        }

        try:
            response = requests.get(self.BASE_URL, params=params, timeout=30)
            if response.status_code == 200:
                root = ET.fromstring(response.content)
                # Namespace map
                ns = {'atom': 'http://www.w3.org/2005/Atom'}
                entry = root.find('atom:entry', ns)
                
                if entry:
                    if not paper.abstract:
                        summary = entry.find('atom:summary', ns)
                        if summary is not None and summary.text:
                            # ArXiv abstracts often have newlines that we might want to clean
                            paper.abstract = summary.text.strip().replace('\n', ' ')
                    
                    if not paper.url:
                        id_elem = entry.find('atom:id', ns)
                        if id_elem is not None and id_elem.text:
                            paper.url = id_elem.text
                            
                    if not paper.paper_id:
                         # ArXiv ID is usually in the id field http://arxiv.org/abs/2101.12345
                         id_elem = entry.find('atom:id', ns)
                         if id_elem is not None and id_elem.text:
                            paper.paper_id = id_elem.text.split('/')[-1]

            elif response.status_code == 503:
                 print(f"Rate limit hit (ArXiv) for paper: {paper.title[:30]}")
                 raise RateLimitException("ArXiv 503")

        except requests.RequestException as e:
            print(f"Error fetching from ArXiv for {paper.title}: {e}")
        except Exception as e:
            print(f"Unexpected error in ArXiv client for {paper.title}: {e}")
        
        return paper
