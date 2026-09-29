"""
backend/core/retrieval/rrf_fusion.py
Consultant+ Core Engine 2.0 — Reciprocal Rank Fusion (RRF).
Merges candidates across Dense, Lexical, and Graph retrieval channels into a unified candidate pool.
"""

from typing import List, Dict, Any
from core.models import EvidenceCandidate


def compute_rrf_fusion(
    dense_candidates: List[EvidenceCandidate],
    lexical_candidates: List[EvidenceCandidate],
    graph_candidates: List[EvidenceCandidate],
    k_constant: int = 60,
    dense_weight: float = 1.0,
    lexical_weight: float = 0.8,
    graph_weight: float = 0.9,
    top_n: int = 60
) -> List[EvidenceCandidate]:
    """Combines multi-channel retrieval lists using weighted Reciprocal Rank Fusion."""
    score_map: Dict[str, float] = {}
    candidate_map: Dict[str, EvidenceCandidate] = {}

    # 1. Process Dense Channel
    sorted_dense = sorted(dense_candidates, key=lambda c: c.dense_score, reverse=True)
    for rank, cand in enumerate(sorted_dense):
        cid = cand.chunk_id
        candidate_map[cid] = cand
        score_map[cid] = score_map.get(cid, 0.0) + (dense_weight / (k_constant + (rank + 1)))

    # 2. Process Lexical Channel
    sorted_lex = sorted(lexical_candidates, key=lambda c: c.lexical_score, reverse=True)
    for rank, cand in enumerate(sorted_lex):
        cid = cand.chunk_id
        if cid not in candidate_map:
            candidate_map[cid] = cand
        else:
            # Merge lexical score into candidate
            candidate_map[cid].lexical_score = cand.lexical_score
        score_map[cid] = score_map.get(cid, 0.0) + (lexical_weight / (k_constant + (rank + 1)))

    # 3. Process Graph Expansion Channel
    for rank, cand in enumerate(graph_candidates):
        cid = cand.chunk_id
        if cid not in candidate_map:
            candidate_map[cid] = cand
        score_map[cid] = score_map.get(cid, 0.0) + (graph_weight / (k_constant + (rank + 1)))

    # 4. Assign final RRF score and sort
    fused_list: List[EvidenceCandidate] = []
    for cid, cand in candidate_map.items():
        cand.rrf_score = round(score_map[cid], 5)
        fused_list.append(cand)

    fused_list.sort(key=lambda c: c.rrf_score, reverse=True)
    return fused_list[:top_n]
