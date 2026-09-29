"""
backend/core/adapters/base.py
Consultant+ Core Engine 2.0 — Abstract Knowledge Adapter Interface.
Decouples core reasoning and state machine from jurisdiction-specific storage backends.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from core.models import EvidenceCandidate, TemporalValidity


class BaseKnowledgeAdapter(ABC):
    """Abstract interface for multi-jurisdiction legal knowledge storage (TH, RU, etc.)"""

    @abstractmethod
    def dense_search(self, queries: List[str], top_k: int = 25) -> List[EvidenceCandidate]:
        """Perform semantic vector retrieval across chunk embeddings."""
        pass

    @abstractmethod
    def lexical_search(self, terms: List[str], top_k: int = 25) -> List[EvidenceCandidate]:
        """Perform keyword / full-text / trigram retrieval."""
        pass

    @abstractmethod
    def graph_expand(self, candidate_doc_ids: List[str], candidate_sections: List[str], top_k: int = 15) -> List[EvidenceCandidate]:
        """Traverse statutory cross-references, parent sections, and amendment links."""
        pass

    @abstractmethod
    def resolve_temporal_version(self, doc_id: str, event_date: Optional[str] = None) -> TemporalValidity:
        """Evaluate whether statute was active, amended, or repealed at date of event."""
        pass
