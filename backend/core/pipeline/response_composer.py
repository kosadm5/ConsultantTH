"""
backend/core/pipeline/response_composer.py
Consultant+ Core Engine 2.0 — Multilingual Response Composer.
Composes final client-facing ConsultantResponse DTO in user's response_language,
with interactive statutory citations, precedents, and strictly <= 1 high-yield follow-up question.
"""

from typing import List, Dict, Any, Optional
from core.models import (
    ConsultantResponse,
    EvidenceCandidate,
    ReasoningPlan,
    ResponseMode
)


class ResponseComposer:
    @staticmethod
    def compose(
        validated_text: str,
        reasoning_plan: ReasoningPlan,
        evidence_chunks: List[EvidenceCandidate],
        lang: str = "ru",
        trace_id: str = "tr_unknown",
        session_id: Optional[str] = None
    ) -> ConsultantResponse:
        """Assembles the final ConsultantResponse compatible with Mini App and Web UI."""
        
        # 1. Format Statutory References for UI modal
        stat_refs: List[Dict[str, Any]] = []
        for c in evidence_chunks[:8]:
            cid = c.doc_id or c.chunk_id
            stat_refs.append({
                "id": cid,
                "key": c.chunk_id,
                "title": c.title or "Законодательный акт Королевства Таиланд",
                "section_num": c.section_num or "Статья закона",
                "snippet": c.chunk_text[:350],
                "full_text": c.chunk_text,
                "official_th": c.title,
                "official_th_section": c.section_num,
                "official_th_text": c.chunk_text[:600],
                "status": "ACTIVE",
                "status_th": "มีผลใช้บังคับ",
                "score": round(c.final_evidence_score or 0.95, 2)
            })

        # 2. Extract Precedents if present in evidence
        precedents: List[Dict[str, Any]] = []
        for c in evidence_chunks:
            if "DEKA" in c.doc_id.upper() or "SAN DEKA" in c.title.upper():
                precedents.append({
                    "doc_id": c.doc_id,
                    "deka_no": c.section_num or "Прецедент Верховного Суда Таиланда (San Deka)",
                    "headline": c.chunk_text[:200],
                    "full_text": c.chunk_text
                })

        # 3. Dynamic Proactive Question: STRICTLY AT MOST 1 HIGH-VALUE QUESTION
        followups: List[str] = []
        if reasoning_plan.response_mode != ResponseMode.DIRECT_ANSWER:
            target_q = reasoning_plan.next_high_yield_question_target_lang or reasoning_plan.next_high_yield_question
            if target_q and len(target_q.strip()) > 5:
                followups.append(target_q.strip())

        # 4. Sources
        sources = [
            {"source": "Королевская газета Королевства Таиланд (Royal Thai Government Gazette)", "status": "Официальный вестник"},
            {"source": "Государственный Совет Таиланда (Council of State / Krisdika)", "status": "Официальное толкование"},
            {"source": "Верховный Суд Таиланда (San Deka Repository)", "status": "Судебная практика"}
        ]

        return ConsultantResponse(
            answer=validated_text,
            lang=lang,
            statutory_references=stat_refs,
            precedents=precedents,
            proactive_clarifications=followups[:1],  # STRICT CONTRACT: ask_question_count <= 1
            domain="REAL_ESTATE",
            mode=reasoning_plan.response_mode,
            trace_id=trace_id,
            session_id=session_id,
            sources=sources
        )
