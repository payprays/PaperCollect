import concurrent.futures
import time
from typing import List
import random
from src.core.models import Paper
from src.core.interfaces import MetadataSource
from src.clients.semantic_scholar_client import SemanticScholarClient
from src.clients.openalex_client import OpenAlexClient
from src.clients.crossref_client import CrossrefClient
from src.clients.arxiv_client import ArxivClient
from src.clients.europe_pmc_client import EuropePMCClient
from src.core.exceptions import RateLimitException

class MetadataManager:
    """
    Manages multiple metadata sources and handles concurrent enrichment.
    """
    def __init__(self, threads: int = 4):
        self.threads = threads
        # Initialize available clients
        # Order matters: Try high quality/fastest sources first
        self.sources: List[MetadataSource] = [
            OpenAlexClient(),
            ArxivClient(),
            CrossrefClient(),
            EuropePMCClient(),
            SemanticScholarClient()
        ]

    def _enrich_single_paper(self, paper: Paper) -> Paper:
        """
        Tries to enrich a single paper using available sources.
        """
        # If paper already has all critical metadata (e.g. from previous run), skip
        if paper.abstract and paper.citation_count is not None:
             return paper

        sources_tried = 0
        sources_rate_limited = 0

        for source in self.sources:
            # If we already have an abstract and citation count, we might be good.
            if paper.abstract and paper.citation_count is not None:
                break

            sources_tried += 1
            try:
                paper = source.enrich_paper(paper)
            except RateLimitException:
                sources_rate_limited += 1
                continue
            except Exception as e:
                print(f"Error in source {source.__class__.__name__}: {e}")

        # All sources rate limited — skip this paper instead of sleeping
        if sources_tried > 0 and sources_rate_limited == sources_tried:
             print(f"All sources rate limited for paper {paper.title[:30]}, skipping.")

        return paper

    def enrich_papers(self, papers: List[Paper]) -> List[Paper]:
        """
        Enriches a list of papers concurrently.
        """
        enriched_papers = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.threads) as executor:
            # Submit all tasks
            future_to_paper = {executor.submit(self._enrich_single_paper, paper): paper for paper in papers}

            for i, future in enumerate(concurrent.futures.as_completed(future_to_paper)):
                paper = future_to_paper[future]
                try:
                    result_paper = future.result()
                    enriched_papers.append(result_paper)
                except Exception as exc:
                    print(f"Paper {paper.title[:30]} generated an exception: {exc}")
                    enriched_papers.append(paper) # Return original if failed

        return enriched_papers
