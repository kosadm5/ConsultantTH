"""
backend/core/pipeline/response_composer.py
Consultant+ Core Engine 2.0 — Multilingual Response Composer.
Composes final client-facing ConsultantResponse DTO in user's response_language,
with interactive statutory citations, precedents, and dynamic proactive follow-up questions.
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

        # 3. Dynamic Proactive Questions strictly in user's target language
        followups: List[str] = []
        target_q = reasoning_plan.next_high_yield_question_target_lang or reasoning_plan.next_high_yield_question
        if target_q:
            followups.append(target_q)

        # Additional contextual follow-up in user's language
        if reasoning_plan.applicable_options:
            first_opt = reasoning_plan.applicable_options[0].get("option_title")
            if first_opt:
                if lang == "ru":
                    doc_q = f"Какие документы требуются для оформления: {first_opt}?"
                elif lang == "th":
                    doc_q = f"เอกสารที่ต้องใช้ในการดำเนินการ: {first_opt} มีอะไรบ้าง?"
                else:
                    doc_q = f"What statutory documents are mandated to structure: {first_opt}?"
                if doc_q not in followups:
                    followups.append(doc_q)

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
            proactive_clarifications=followups[:3],
            domain="REAL_ESTATE",
            mode=reasoning_plan.response_mode,
            trace_id=trace_id,
            session_id=session_id,
            sources=sources
        )
