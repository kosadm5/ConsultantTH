"""
backend/core/retrieval/hybrid_retriever.py
Consultant+ Core Engine 2.0 — Master Hybrid Retrieval Engine.
Orchestrates Parallel Dense Search, Lexical FTS, Citation Graph Expansion,
RRF Fusion, and EvidenceEngine Reranking & Filtering.
"""

from typing import List, Dict, Any, Tuple
from core.models import QueryPlan, EvidenceCandidate
from core.adapters.base import BaseKnowledgeAdapter
from core.retrieval.rrf_fusion import compute_rrf_fusion
from core.retrieval.evidence_engine import EvidenceEngine


class MasterHybridRetriever:
    def __init__(self, adapter: BaseKnowledgeAdapter, evidence_engine: EvidenceEngine):
        self.adapter = adapter
        self.evidence_engine = evidence_engine

    def retrieve(
        self,
        query_plan: QueryPlan,
        top_evidence: int = 10,
        event_year: int = 2026
    ) -> Tuple[List[EvidenceCandidate], Dict[str, str], Dict[str, int]]:
        """
        Executes complete multi-channel hybrid search:
        1. Dense retrieval across dense_queries
        2. Lexical retrieval across lexical_queries
        3. Legal Reference Graph expansion
        4. Reciprocal Rank Fusion (RRF)
        5. Evidence Engine (Cross-Encoder Rerank + Authority + Temporal Validity)
        
        Returns:
            (selected_evidence, discarded_reasons_map, counts_map)
        """
        # 1. Parallel Channel Searches
        dense_hits = self.adapter.dense_search(query_plan.dense_queries, top_k=25)
        lexical_hits = self.adapter.lexical_search(query_plan.lexical_queries, top_k=25)

        # 2. Extract unique doc IDs for Graph Expansion
        initial_doc_ids = list(set(
            [c.doc_id for c in dense_hits[:10] if c.doc_id] +
            [c.doc_id for c in lexical_hits[:10] if c.doc_id]
        ))
        graph_hits = self.adapter.graph_expand(initial_doc_ids, [], top_k=15)

        # 3. RRF Fusion into Candidate Pool
        fused_pool = compute_rrf_fusion(
            dense_candidates=dense_hits,
            lexical_candidates=lexical_hits,
            graph_candidates=graph_hits,
            top_n=60
        )

        # 4. Evidence Engine Evaluation & Reranking
        selected_evidence, discarded_reasons = self.evidence_engine.evaluate_and_rank(
            query=query_plan.canonical_summary or query_plan.original_query,
            candidates=fused_pool,
            top_k=top_evidence,
            event_year=event_year
        )

        counts = {
            "dense_count": len(dense_hits),
            "lexical_count": len(lexical_hits),
            "graph_count": len(graph_hits),
            "rrf_pool_count": len(fused_pool),
            "selected_evidence_count": len(selected_evidence)
        }

        return selected_evidence, discarded_reasons, counts
