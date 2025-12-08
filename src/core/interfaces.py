from abc import ABC, abstractmethod
from typing import List
from .models import Paper

class PaperSource(ABC):
    """Interface for fetching a list of papers from a source (e.g., DBLP)."""

    @abstractmethod
    def fetch_papers(self, conference: str, year: int) -> List[Paper]:
        """Fetches papers for a specific conference and year."""
        pass

class MetadataSource(ABC):
    """Interface for fetching detailed metadata for a paper."""

    @abstractmethod
    def enrich_paper(self, paper: Paper) -> Paper:
        """Fetches metadata (abstract, citations) for a paper and returns the updated paper object."""
        pass
