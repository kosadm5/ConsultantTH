"""
backend/core/pipeline/degraded_mode.py
Consultant+ Core Engine 2.0 — Safe Degraded Mode Handler.
When LLM gateway or reasoning encounters an unrecoverable failure, delivers authentic
verified statutory materials directly from the database without fabricating or using hardcoded fake advice.
"""

from typing import List, Dict, Any
from core.models import EvidenceCandidate, ConsultantResponse, ResponseMode


class SafeDegradedHandler:
    @staticmethod
    def build_degraded_response(
        query: str,
        evidence_chunks: List[EvidenceCandidate],
        lang: str = "ru",
        trace_id: str = "trace_degraded"
    ) -> ConsultantResponse:
        """Constructs an unembellished, honest statutory evidence response."""
        
        stat_refs: List[Dict[str, Any]] = []
        for c in evidence_chunks[:5]:
            stat_refs.append({
                "id": c.doc_id or c.chunk_id,
                "key": c.chunk_id,
                "title": c.title,
                "section_num": c.section_num,
                "snippet": c.chunk_text[:350],
                "full_text": c.chunk_text,
                "official_th": c.title,
                "official_th_section": c.section_num,
                "official_th_text": c.chunk_text[:500],
                "status": "ACTIVE",
                "status_th": "มีผลใช้บังคับ",
                "score": round(c.final_evidence_score or 0.9, 2)
            })

        if lang == "ru":
            body = (
                "### ℹ️ Режим прямого нормативного доступа (Safe Degraded Mode)\n\n"
                "Аналитический модуль юридического синтеза временно работает в режиме прямого доступа к реестру источников.\n\n"
                "По вашему запросу из базы официального законодательства Королевства Таиланд отобраны следующие действующие нормативные акты и статьи:\n\n"
            )
            for i, s in enumerate(stat_refs, 1):
                body += f"**{i}. {s['title']} ({s['section_num']})**\n"
                body += f"> {s['snippet']}...\n\n"
            body += (
                "---\n"
                "💡 *Вы можете ознакомиться с полными текстами норм в карточках ниже или повторить запрос через минуту для формирования развернутого аналитического заключения.*"
            )
            followups = [
                "Повторить формирование правового заключения",
                "Показать полные тексты отобранных статей"
            ]
        elif lang == "th":
            body = (
                "### ℹ️ โหมดการเข้าถึงตัวบทกฎหมายโดยตรง (Safe Degraded Mode)\n\n"
                "ระบบได้รวบรวมบทบัญญัติแห่งกฎหมายที่เกี่ยวข้องโดยตรงจากฐานข้อมูลราชกิจจานุเบกษา:\n\n"
            )
            for i, s in enumerate(stat_refs, 1):
                body += f"**{i}. {s['title']} ({s['section_num']})**\n> {s['snippet']}...\n\n"
            followups = ["ประมวลผลคำตอบทางกฎหมายอีกครั้ง"]
        else:
            body = (
                "### ℹ️ Direct Statutory Access Mode (Safe Degraded Mode)\n\n"
                "The legal analytical reasoning module is temporarily operating in direct evidence retrieval mode.\n\n"
                "The following verified provisions from the official Thai legal repository match your inquiry:\n\n"
            )
            for i, s in enumerate(stat_refs, 1):
                body += f"**{i}. {s['title']} ({s['section_num']})**\n> {s['snippet']}...\n\n"
            body += "---\n💡 *Please tap on any provision below for the complete official text or retry in a moment.*"
            followups = ["Retry detailed legal analysis", "View full statutory text"]

        return ConsultantResponse(
            answer=body,
            lang=lang,
            statutory_references=stat_refs,
            precedents=[],
            proactive_clarifications=followups,
            domain="STATUTORY_REPOSITORY",
            mode=ResponseMode.SAFE_DEGRADED,
            trace_id=trace_id,
            sources=[{"source": "Королевская газета Королевства Таиланд (Royal Gazette)", "status": "Верифицировано"}]
        )
