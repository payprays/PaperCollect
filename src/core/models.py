from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class Paper:
    title: str
    authors: List[str]
    year: int
    venue: str
    dblp_key: Optional[str] = None
    url: Optional[str] = None

    # Metadata fields that might be filled later
    abstract: Optional[str] = None
    citation_count: Optional[int] = None
    reference_count: Optional[int] = None
    paper_id: Optional[str] = None # ID from the metadata provider
    source: Optional[str] = None
    source_url: Optional[str] = None
