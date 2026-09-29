#!/usr/bin/env python3
"""
processor/thai_enricher.py
Thai Legal Knowledge Enricher, Citation Graph Builder & Self-Learning Synthesis.
"""

import re
import hashlib
from typing import Dict, List, Any, Optional

# Thai Legal Citation Patterns
RE_SECTION = re.compile(r"มาตรา\s+(\d+(?:\s*(?:ทวิ|ตรี|จัตวา|เบญจ|ฉ|สัปต|อัฐ|นว|สิบ|\/\d+))?)")
RE_ACT = re.compile(r"พระราชบัญญัติ[^\r\n,0-9]{3,60}(?:พ\.ศ\.\s*\d{4})?")
RE_DECREE = re.compile(r"พระราชกำหนด[^\r\n,0-9]{3,60}(?:พ\.ศ\.\s*\d{4})?")
RE_MINISTERIAL = re.compile(r"กฎกระทรวง[^\r\n,0-9]{3,60}(?:พ\.ศ\.\s*\d{4})?")
RE_DEKA = re.compile(r"คำพิพากษาศาลฎีกาที่\s*(\d+\/\d{4})")

# Legal Domain Keywords
DOMAIN_KEYWORDS = {
    "CRIMINAL": ["ความผิด", "อาญา", "โทษ", "จำคุก", "ปรับ", "ริบทรัพย์สิน", "ประหารชีวิต", "ผู้กระทำความผิด"],
    "CIVIL_COMMERCIAL": ["สัญญา", "ละเมิด", "ทรัพย์สิน", "มรดก", "นิติกรรม", "หนี้", "ซื้อขาย", "เช่าทรัพย์", "ค้ำประกัน", "จำนอง"],
    "ADMINISTRATIVE": ["หน่วยงานทางปกครอง", "เจ้าหน้าที่ของรัฐ", "คำสั่งทางปกครอง", "การปฏิบัติหน้าที่", "ศาลปกครอง"],
    "CONSTITUTIONAL": ["รัฐธรรมนูญ", "สิทธิเสรีภาพ", "ศาลรัฐธรรมนูญ", "อำนาจอธิปไตย"],
    "LABOR": ["การจ้างงาน", "นายจ้าง", "ลูกจ้าง", "ค่าจ้าง", "เลิกจ้าง", "ประกันสังคม"],
    "LAND_PROPERTY": ["ที่ดิน", "โฉนด", "กรรมสิทธิ์", "ครอบครอง", "ภาระจำยอม"]
}


class ThaiLegalEnricher:
    """Extracts citations, classifies domain, builds graph edges and generates QA pairs."""

    def __init__(self):
        pass

    def extract_citations(self, text: str) -> Dict[str, List[str]]:
        """Extracts Thai legal sections, acts, decrees, and Supreme Court rulings."""
        sections = list(set(RE_SECTION.findall(text)))
        acts = list(set(RE_ACT.findall(text)))
        decrees = list(set(RE_DECREE.findall(text)))
        ministerials = list(set(RE_MINISTERIAL.findall(text)))
        dekas = list(set(RE_DEKA.findall(text)))

        return {
            "sections": [f"มาตรา {s}" for s in sections],
            "acts": [a.strip() for a in acts],
            "decrees": [d.strip() for d in decrees],
            "ministerial_regulations": [m.strip() for m in ministerials],
            "deka_precedents": [f"ฎีกาที่ {d}" for d in dekas]
        }

    def classify_domain(self, text: str, title: str = "") -> str:
        """Classifies document into Thai legal domain."""
        combined = f"{title} {text}".lower()
        scores = {}
        for domain, kws in DOMAIN_KEYWORDS.items():
            score = sum(combined.count(kw) for kw in kws)
            scores[domain] = score

        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else "GENERAL_LAW"

    def generate_qa_self_learning(self, title: str, text: str, domain: str, citations: Dict[str, List[str]]) -> List[Dict[str, str]]:
        """Synthesizes high-value legal QA pairs for online self-learning in EN, TH, RU, ZH."""
        qa_pairs = []
        clean_title = title.strip() or "ข้อกฎหมายนี้"
        
        if citations.get("sections"):
            sec_str = ", ".join(citations["sections"][:3])
            qa_pairs.append({
                "lang": "th",
                "question": f"ตาม {clean_title} ({sec_str}) มีหลักเกณฑ์และข้อกำหนดทางกฎหมายอย่างไร?",
                "answer_summary": f"เอกสารนี้กำหนดหลักเกณฑ์ตาม {sec_str} ในหมวดหมู่ {domain}",
                "clarification_needed": "ประเด็นนี้เกี่ยวข้องกับการกระทำในฐานะบุคคลธรรมดาหรือนิติบุคคล?"
            })
            
            qa_pairs.append({
                "lang": "en",
                "question": f"What are the legal requirements and provisions under {clean_title} regarding {sec_str}?",
                "answer_summary": f"This provision sets mandatory statutory obligations for {domain} under {sec_str}.",
                "clarification_needed": "Does this matter involve a natural person or a registered Thai juristic entity?"
            })

            qa_pairs.append({
                "lang": "ru",
                "question": f"Каковы правовые нормы и требования согласно {clean_title} в части {sec_str}?",
                "answer_summary": f"Норма регулирует правоотношения в сфере {domain} на основании {sec_str}.",
                "clarification_needed": "Касается ли вопрос физического лица или зарегистрированной тайской компании?"
            })

            qa_pairs.append({
                "lang": "zh",
                "question": f"根据 {clean_title} 中关于 {sec_str} 的规定，具体的法律要求是什么？",
                "answer_summary": f"该条款规定了 {domain} 领域中关于 {sec_str} 的法定合规要求。",
                "clarification_needed": "该事项涉及自然人还是在泰国注册的法人企业？"
            })

        return qa_pairs

    def enrich_document(self, doc_id: str, title: str, text: str, meta: Optional[Dict] = None) -> Dict[str, Any]:
        """Full enrichment pass producing parent metadata, graph edges, and self-learning payload."""
        citations = self.extract_citations(text)
        domain = self.classify_domain(text, title)
        qa_pairs = self.generate_qa_self_learning(title, text, domain, citations)

        edges = []
        for sec in citations["sections"]:
            edges.append({"source": doc_id, "target": sec, "type": "GOVERNED_BY_SECTION"})
        for deka in citations["deka_precedents"]:
            edges.append({"source": doc_id, "target": deka, "type": "CITES_SUPREME_COURT_PRECEDENT"})

        return {
            "doc_id": doc_id,
            "title": title,
            "domain": domain,
            "citations": citations,
            "citation_count": sum(len(v) for v in citations.values()),
            "graph_edges": edges,
            "qa_self_learning": qa_pairs,
            "multilingual_tags": {
                "en": [domain, "Thai Law", "Statutory Provision"],
                "th": [domain, "กฎหมายไทย", "บทบัญญัติ"],
                "ru": [domain, "Законодательство Таиланда", "Нормативный акт"],
                "zh": [domain, "泰国法律", "法律条文"]
            }
        }
