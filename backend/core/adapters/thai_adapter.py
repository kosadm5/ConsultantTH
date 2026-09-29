"""
backend/core/adapters/thai_adapter.py
Consultant+ Core Engine 2.0 — Thailand Knowledge Adapter.
Interacts with Qdrant (153,831 chunks), PostgreSQL thailaw (57k cards, 30k references),
and provides temporal resolution for Thai Kingdom statutes.
"""

import os
import re
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import List, Dict, Any, Optional
from fastembed import TextEmbedding

from core.adapters.base import BaseKnowledgeAdapter
from core.models import EvidenceCandidate, TemporalValidity

PG_CONFIG = {
    "dbname": "thailaw",
    "user": "admin",
    "password": "Privet2020!",
    "host": "localhost",
    "port": 5433
}

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6433")
QDRANT_COLLECTION = "thai_legal_chunks_hybrid"


class THKnowledgeAdapter(BaseKnowledgeAdapter):
    def __init__(self, pg_config: Optional[Dict[str, Any]] = None, qdrant_url: Optional[str] = None):
        self.pg_config = pg_config or PG_CONFIG
        self.qdrant_url = qdrant_url or QDRANT_URL
        self._embedder = None

    def _get_embedder(self) -> TextEmbedding:
        if self._embedder is None:
            self._embedder = TextEmbedding(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
        return self._embedder

    def _get_pg_conn(self):
        return psycopg2.connect(**self.pg_config)

    def dense_search(self, queries: List[str], top_k: int = 25) -> List[EvidenceCandidate]:
        """Runs vector search in Qdrant across all generated sub-queries."""
        if not queries:
            return []

        embedder = self._get_embedder()
        results: Dict[str, EvidenceCandidate] = {}

        try:
            # Batch embed all queries in a single call for high performance
            vecs = list(embedder.embed(queries))
            for q, vec in zip(queries, vecs):
                q_vec = vec.tolist()
                resp = requests.post(
                    f"{self.qdrant_url}/collections/{QDRANT_COLLECTION}/points/search",
                    json={
                        "vector": q_vec,
                        "limit": top_k,
                        "with_payload": True,
                        "with_vector": False
                    },
                    timeout=5.0
                )
                if resp.status_code != 200:
                    continue

                hits = resp.json().get("result", [])
                for h in hits:
                    payload = h.get("payload", {})
                    cid = payload.get("chunk_id", str(h.get("id")))
                    doc_id = payload.get("doc_id", "")
                    title = payload.get("title", "")
                    sec = payload.get("section_num", "")
                    text = payload.get("chunk_text", "")
                    domain = payload.get("domain", "GENERAL")
                    status_raw = payload.get("status", "ACTIVE")
                    score = float(h.get("score", 0.0))

                    if cid not in results or score > results[cid].dense_score:
                        cand = EvidenceCandidate(
                            chunk_id=cid,
                            doc_id=doc_id,
                            title=title,
                            section_num=sec,
                            chunk_text=text,
                            domain=domain,
                            dense_score=score,
                            temporal_validity=TemporalValidity(
                                is_active=(status_raw.upper() != "REPEALED")
                            )
                        )
                        results[cid] = cand
        except Exception as e:
            print(f"Batch dense search error: {e}")

        return list(results.values())

    def lexical_search(self, terms: List[str], top_k: int = 25) -> List[EvidenceCandidate]:
        """
        Searches PostgreSQL thai_legal_chunks using prioritized multi-channel matching:
        1. Exact statutory doc_id lookup (CIVIL_CODE_*, TH_*, OCS_*) with score 3.0
        2. Section numbers / digits with score 2.5
        3. Thai keywords / phrases with score 1.5
        4. English keywords with score 1.0
        """
        if not terms:
            return []

        def is_thai(text: str) -> bool:
            return bool(re.search(r'[\u0e00-\u0e7f]', text))

        def term_priority(t: str) -> int:
            st = t.strip()
            if st.startswith("CIVIL_CODE_") or st.startswith("TH_") or st.startswith("OCS_"):
                return 0
            if st.isdigit() or ("/" in st and any(c.isdigit() for c in st)):
                return 1
            if is_thai(st):
                return 2
            return 3

        # Deduplicate while sorting by priority
        unique_terms = list(dict.fromkeys(terms))
        sorted_terms = sorted(unique_terms, key=term_priority)[:8]

        results: Dict[str, EvidenceCandidate] = {}
        try:
            with self._get_pg_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    for clean_term in sorted_terms:
                        clean_term = clean_term.strip()
                        if len(clean_term) < 2:
                            continue

                        # 1. Exact doc_id
                        if clean_term.startswith("CIVIL_CODE_") or clean_term.startswith("TH_") or clean_term.startswith("OCS_"):
                            cur.execute("""
                                SELECT c.chunk_id, c.doc_id, c.section_num, c.chunk_text,
                                       d.title, d.domain, d.status, d.last_amendment_act
                                FROM thai_legal_chunks c
                                LEFT JOIN thai_legal_cards d ON c.doc_id = d.doc_id
                                WHERE c.doc_id = %s
                                LIMIT %s
                            """, (clean_term, top_k))
                            base_score = 3.0
                        # 2. Section number
                        elif clean_term.isdigit() or ("/" in clean_term and any(c.isdigit() for c in clean_term)):
                            cur.execute("""
                                SELECT c.chunk_id, c.doc_id, c.section_num, c.chunk_text,
                                       d.title, d.domain, d.status, d.last_amendment_act
                                FROM thai_legal_chunks c
                                LEFT JOIN thai_legal_cards d ON c.doc_id = d.doc_id
                                WHERE c.section_num ILIKE %s OR c.chunk_text ILIKE %s
                                LIMIT %s
                            """, (f"%{clean_term}%", f"%มาตรา {clean_term}%", top_k))
                            base_score = 2.5
                        # 3. General text in chunk_text or card title
                        else:
                            cur.execute("""
                                SELECT c.chunk_id, c.doc_id, c.section_num, c.chunk_text,
                                       d.title, d.domain, d.status, d.last_amendment_act
                                FROM thai_legal_chunks c
                                LEFT JOIN thai_legal_cards d ON c.doc_id = d.doc_id
                                WHERE c.chunk_text ILIKE %s OR d.title ILIKE %s
                                LIMIT %s
                            """, (f"%{clean_term}%", f"%{clean_term}%", top_k))
                            base_score = 1.5 if is_thai(clean_term) else 1.0

                        rows = cur.fetchall()
                        for r in rows:
                            cid = r["chunk_id"]
                            status = (r["status"] or "ACTIVE").upper()
                            if cid not in results:
                                cand = EvidenceCandidate(
                                    chunk_id=cid,
                                    doc_id=r["doc_id"] or "",
                                    title=r["title"] or "",
                                    section_num=r["section_num"] or "",
                                    chunk_text=r["chunk_text"] or "",
                                    domain=r["domain"] or "GENERAL",
                                    lexical_score=base_score,
                                    temporal_validity=TemporalValidity(
                                        is_active=(status != "REPEALED"),
                                        last_amended_act=r.get("last_amendment_act")
                                    )
                                )
                                results[cid] = cand
                            else:
                                results[cid].lexical_score += base_score

        except Exception as e:
            print(f"Lexical search error: {e}")

        # Return sorted by lexical_score descending
        ranked = sorted(results.values(), key=lambda c: c.lexical_score, reverse=True)
        return ranked

    def graph_expand(self, candidate_doc_ids: List[str], candidate_sections: List[str], top_k: int = 15) -> List[EvidenceCandidate]:
        """Finds statutes linked via thai_legal_references."""
        if not candidate_doc_ids:
            return []

        unique_docs = list(set([d for d in candidate_doc_ids if d]))[:10]
        results: List[EvidenceCandidate] = []

        try:
            with self._get_pg_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT r.target_doc_id, r.ref_type, r.article_ref,
                               c.chunk_id, c.section_num, c.chunk_text, d.title, d.domain, d.status
                        FROM thai_legal_references r
                        JOIN thai_legal_chunks c ON r.target_doc_id = c.doc_id
                        LEFT JOIN thai_legal_cards d ON r.target_doc_id = d.doc_id
                        WHERE r.source_doc_id = ANY(%s)
                        LIMIT %s
                    """, (unique_docs, top_k))
                    
                    rows = cur.fetchall()
                    for r in rows:
                        cid = r["chunk_id"]
                        status = (r["status"] or "ACTIVE").upper()
                        cand = EvidenceCandidate(
                            chunk_id=cid,
                            doc_id=r["target_doc_id"] or "",
                            title=r["title"] or "",
                            section_num=r["section_num"] or "",
                            chunk_text=r["chunk_text"] or "",
                            domain=r["domain"] or "GENERAL",
                            authority_score=1.1,  # Boosted because cited by primary statute
                            temporal_validity=TemporalValidity(
                                is_active=(status != "REPEALED")
                            )
                        )
                        results.append(cand)
        except Exception as e:
            print(f"Graph expand error: {e}")

        return results

    def resolve_temporal_version(self, doc_id: str, event_date: Optional[str] = None) -> TemporalValidity:
        """Retrieves amendment and currency status from thai_legal_cards."""
        try:
            with self._get_pg_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT status, last_amendment_act, last_amended_year_be, repealed_by
                        FROM thai_legal_cards
                        WHERE doc_id = %s
                        LIMIT 1
                    """, (doc_id,))
                    row = cur.fetchone()
                    if row:
                        status = (row["status"] or "ACTIVE").upper()
                        return TemporalValidity(
                            is_active=(status != "REPEALED"),
                            effective_date_be=row.get("last_amended_year_be"),
                            last_amended_act=row.get("last_amendment_act"),
                            repealed_by=row.get("repealed_by")
                        )
        except Exception as e:
            print(f"Temporal resolution error for {doc_id}: {e}")

        return TemporalValidity(is_active=True)
