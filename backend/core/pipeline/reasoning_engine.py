"""
backend/core/pipeline/reasoning_engine.py
Consultant+ Core Engine 2.0 — Multilingual Two-Pass Legal Reasoning Engine.
Pass 1: Generates structured ReasoningPlan (JSON) directly from verified Evidence Chunks.
Pass 2: Synthesizes authoritative, grounded 5-part legal consultation in the user's TARGET LANGUAGE,
preserving official statutory citation titles and generating strategic follow-up questions in target_lang.
"""

from typing import List, Dict, Any, Optional, Tuple
from core.models import (
    LegalCaseState,
    EvidenceCandidate,
    ReasoningPlan,
    ResponseMode
)
from core.gateway import ModelGateway


PASS_1_SYSTEM_PROMPT = """You are the Apex Legal Reasoning & Analysis System of Consultant+ for the Kingdom of Thailand.
Your role is PASS 1: Generate a rigorous, objective Legal Reasoning Plan in strict JSON based ONLY on the verified evidence chunks provided.

RULES:
1. Ground every claim, mechanism, and risk strictly in the provided EVIDENCE CHUNKS.
2. If evidence does NOT support a conclusion or detail, do not speculate or extrapolate.
3. Systematically evaluate substantive dimensions RELEVANT to the client's legal matter and the evidence base:
   - For real estate & land: foreign land limits (Land Code Section 86), leasehold registration (CCC Section 538), superficies (CCC Section 1410).
   - For wills & estate administration: formal statutory forms (CCC Section 1656, Section 1657 holographic wills), probate and foreign heirs.
   - For tourist accommodation & rentals: Hotel Act B.E. 2547 licensing, non-hotel accommodation ministerial exemptions (up to 4 rooms / 20 guests).
   - For corporate & investment: nominee shareholder prohibitions (Foreign Business Act Section 36, Section 37), 51% Thai / 49% foreign capital distinction (under FBA Section 4 a 51/49 company has less than 50% foreign capital and is legally a Thai company, NOT a foreign person).
   - For family & marriage: prenuptial agreements (CCC Section 1465, 1466), marital property Sin Somros vs Sin Suan Tua (CCC Section 1471, 1474).
   - For labor & employment: statutory severance pay scale (Labor Protection Act Section 118, Section 119), work permit rules.
   - For taxes & revenue: applicable transfer fees, Specific Business Tax (Revenue Code Section 91/2), foreign remittance taxation (P.161/2566).
4. Do NOT force unrelated dimensions (e.g. do not invent nominee or land restrictions for a holographic will or labor case unless relevant).
5. Formulate the single highest-yield strategic follow-up question in BOTH English AND the TARGET LANGUAGE specified.

Output strictly JSON:
{
  "legal_qualification": "Objective assessment of client status under Thai law based on evidence",
  "applicable_options": [
    {
      "option_title": "Title of lawful option",
      "legal_basis": "Act and Section cited in evidence",
      "prerequisites": "Mandatory conditions",
      "risk_level": "LOW / MEDIUM / HIGH"
    }
  ],
  "statutory_prohibitions": [
    "Specific restriction with statutory citation from evidence"
  ],
  "financial_and_tax_formalities": [
    "Applicable banking remittance certificates, fees, or taxes directly pertinent to the matter, or 'Requires specific tax review'"
  ],
  "unknowns_identified": ["unresolved factual issues"],
  "next_high_yield_question": "Single best question in English",
  "next_high_yield_question_target_lang": "Single best question in the requested TARGET LANGUAGE",
  "response_mode": "ANSWER_AND_CLARIFY"
}
"""

PASS_2_SYSTEM_PROMPT = """You are the Senior Official Legal AI Advisor of Consultant+ for the Kingdom of Thailand.
Your role is PASS 2: Convert the structured Reasoning Plan and Evidence into an authoritative, polished, empathetic yet legally rigorous advisory for the client.

MANDATORY LANGUAGE RULE:
The ENTIRE response MUST be composed strictly in the TARGET LANGUAGE requested (Russian if ru, English if en, Thai if th, Chinese if zh).
Preserve authentic statutory titles and Section numbers in parentheses (e.g. "พระราชบัญญัติโรงแรม พ.ศ. 2547 (Hotel Act B.E. 2547)").

FORMATTING STRUCTURE (Mandatory 5 Sections in Markdown):
### 💡 1. Правовая квалификация ситуации / Legal Qualification / การประเมินสถานะทางกฎหมาย
[Clear executive qualification of the client's position under Thai jurisdiction based on known facts and retrieved statutes]

---

### 🏛️ 2. Законные механизмы и варианты оформления / Lawful Mechanisms / แนวทางและกลไกที่ถูกต้องตามกฎหมาย
[Detailed breakdown of permitted legal options and formal statutory requirements, strictly citing retrieved Acts and Sections]

---

### ⚠️ 3. Императивные законодательные запреты и риски / Statutory Prohibitions & Risks / ข้อห้ามและบทกำหนดโทษทางกฎหมาย
[Specific statutory prohibitions, penalties, non-compliance consequences strictly based on evidence]

---

### 💰 4. Финансовый комплаенс и налоги / Financial Compliance & Taxes / การปฏิบัติตามกฎหมายการเงินและภาษีอากร
[Mandatory banking formalities, transfer fees, or tax rules pertinent to the specific matter, strictly referencing evidence or stating that specific assessment depends on official declarations]

---

### 🎯 5. Следующий стратегический шаг / Next Strategic Step / ขั้นตอนเชิงกลยุทธ์ถัดไป
[Present the single highest-yield qualifying question strictly in the TARGET LANGUAGE to continue the consultation]

CRITICAL RULES:
- Never fabricate articles or laws. Use ONLY what is established in the Evidence and Reasoning Plan.
- Use dignified, professional, senior legal advisory tone matching the target language.
- Keep assertions strictly bounded to verified evidence.
- Factual and numerical accuracy: Under Section 4 FBA, 49% foreign capital is strictly less than half (<50%), which makes the company a Thai entity rather than a foreign person.
"""


class TwoPassReasoningEngine:
    def __init__(self, gateway: Optional[ModelGateway] = None):
        self.gateway = gateway or ModelGateway()

    def execute_two_pass_reasoning(
        self,
        case_state: LegalCaseState,
        evidence_chunks: List[EvidenceCandidate],
        target_lang: str = "en",
        user_query: str = ""
    ) -> Tuple[ReasoningPlan, str]:
        """
        Executes Two-Pass reasoning workflow:
        Pass 1: Structured JSON Reasoning Plan grounded on verified evidence
        Pass 2: Complete legal consultation text in target_lang
        
        Returns: (reasoning_plan, generated_text)
        """
        active_facts = case_state.get_active_facts()
        evidence_digest = ""
        for idx, c in enumerate(evidence_chunks[:8]):
            evidence_digest += f"[CHUNK {c.chunk_id} | {c.title} | {c.section_num} | Authority: {c.authority_score}]:\n{c.chunk_text[:500]}\n\n"

        # PASS 1: Structured Plan Generation
        pass1_prompt = f"""CURRENT USER INQUIRY:
\"{user_query}\"

CLIENT FACTS & CASE STATE:
Matter: {case_state.matter_type}
Active Facts: {active_facts}
Target Language for advisory: {target_lang}

VERIFIED EVIDENCE BASE (Kingdom of Thailand):
{evidence_digest}
"""
        pass1_messages = [
            {"role": "system", "content": PASS_1_SYSTEM_PROMPT},
            {"role": "user", "content": pass1_prompt}
        ]

        raw_plan = self.gateway.chat_structured_json(pass1_messages, temperature=0.1)

        reasoning_plan = ReasoningPlan(
            legal_qualification=raw_plan.get("legal_qualification", "Status requires assessment under Thai law."),
            applicable_options=raw_plan.get("applicable_options", []),
            statutory_prohibitions=raw_plan.get("statutory_prohibitions", []),
            financial_and_tax_formalities=raw_plan.get("financial_and_tax_formalities", []),
            unknowns_identified=raw_plan.get("unknowns_identified", []),
            next_high_yield_question=raw_plan.get("next_high_yield_question"),
            next_high_yield_question_target_lang=raw_plan.get("next_high_yield_question_target_lang") or raw_plan.get("next_high_yield_question"),
            response_mode=ResponseMode(raw_plan.get("response_mode", "ANSWER_AND_CLARIFY"))
        )

        # PASS 2: Comprehensive Advisory Text Generation
        pass2_prompt = f"""MANDATORY TARGET LANGUAGE: {target_lang.upper()}
CURRENT USER INQUIRY:
\"{user_query}\"

CLIENT FACTS: {active_facts}

STRUCTURED REASONING PLAN:
{reasoning_plan.model_dump_json(indent=2)}

VERIFIED EVIDENCE BASE:
{evidence_digest}

Compose the complete 5-section legal consultation in {target_lang.upper()} strictly addressing the CURRENT USER INQUIRY based on the verified evidence.
"""
        pass2_messages = [
            {"role": "system", "content": PASS_2_SYSTEM_PROMPT},
            {"role": "user", "content": pass2_prompt}
        ]

        generated_text = self.gateway.chat_completion(pass2_messages, temperature=0.2)
        return reasoning_plan, generated_text
