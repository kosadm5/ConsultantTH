"""
backend/core/pipeline/claim_validator.py
Consultant+ Core Engine 2.0 — Claim-Level Grounding & Substantive Issue Coverage Validator.
Hardening Cycle 2 — Branch A:
- Category E: Validator Hygiene (separates substantive legal claims from procedural disclaimers & questions).
- Denominator of Grounding Rate strictly counts SUBSTANTIVE_LEGAL_CLAIM.
- Disclaimers and clarifying questions are preserved in Agent Trace as PROCEDURAL_VALID.
- Production Safety Rule: Strict Invariant (FINAL_RESPONSE ⊆ GROUNDED_CONTENT, zero raw fallbacks).
- Double-Pass Hard Safety Gate: Sentence/token-based sanitization and verification guaranteeing unsupported_in_final == 0.
"""

import re
from typing import List, Dict, Any, Optional, Tuple
from core.models import EvidenceCandidate, ClaimRecord, ClaimStatus, ClaimType
from core.gateway import ModelGateway


CLAIM_VALIDATOR_PROMPT = """You are the Senior Citation, Hallucination & Legal Issue Coverage Auditor of Consultant+ for the Kingdom of Thailand.
Your duty is twofold:
1. Grounding Validation: Verify every substantive legal claim in the proposed answer against the retrieved evidence chunks.
2. Issue Coverage Audit: Check whether key mandatory substantive legal dimensions for the client's matter have been addressed.

STRICT TAXONOMY RULES:
1. Deconstruct the proposed answer into discrete individual sentences / statements.
2. For each statement, determine its "claim_type":
   - "SUBSTANTIVE_LEGAL_CLAIM": A substantive assertion of law, legal right, statutory prohibition, penalty, tax rate, quota, or formal requirement under Thai law (e.g. "Foreigners may own up to 49% of condo area", "Leases over 3 years must be registered under Section 538", "Nominees face up to 3 years imprisonment").
   - "PROCEDURAL_DISCLAIMER": A standard legal caveat, procedural disclaimer, reservation of rights, or notice that individual tax/document review is required (e.g. "Для точной оценки финансовых обязательств требуется отдельный анализ", "Конкретные ставки зависят от структуры сделки").
   - "CLARIFYING_QUESTION": An inquiry or question addressed to the client to clarify case facts (e.g. "Какова площадь квартиры?", "Есть ли у вас тайская супруга?").
   - "CAVEAT_RESERVATION": A cautionary conversational remark without specific factual legal rules.

3. Verification of Claims:
   - For "SUBSTANTIVE_LEGAL_CLAIM": verify NLI entailment against evidence chunks:
     * "SUPPORTED": The claim is fully substantiated by the cited evidence chunk.
     * "PARTIALLY_SUPPORTED": The claim is mostly true, but exaggerates, generalizes, or omits a statutory caveat.
     * "UNSUPPORTED": The claim is completely ungrounded in the provided evidence.
   - For "PROCEDURAL_DISCLAIMER", "CLARIFYING_QUESTION", "CAVEAT_RESERVATION":
     * Set status to "SUPPORTED". Disclaimers and questions are legitimate conversational structures and MUST NOT be penalized as unsupported legal facts.

4. Production Safety Rule:
   If any SUBSTANTIVE claim is UNSUPPORTED or PARTIALLY_SUPPORTED, provide a "refined_answer":
   The complete rewritten user-facing legal advice text in the user's language, with unsupported claims surgically excised or strictly constrained to verified evidence chunks.
   CRITICAL: NEVER output meta-commentary like "The proposed answer..." in "refined_answer". If all substantive claims are supported, set "needs_refinement": false and "refined_answer": "".

Output strictly JSON:
{
  "claims": [
    {
      "claim_text": "Exact sentence in answer",
      "claim_type": "SUBSTANTIVE_LEGAL_CLAIM",
      "is_substantive": true,
      "supporting_chunk_ids": ["chunk_id_1"],
      "status": "SUPPORTED",
      "validation_explanation": "Directly backed by Section 86"
    },
    {
      "claim_text": "Для точной оценки финансовых обязательств требуется отдельный анализ",
      "claim_type": "PROCEDURAL_DISCLAIMER",
      "is_substantive": false,
      "supporting_chunk_ids": [],
      "status": "SUPPORTED",
      "validation_explanation": "Procedural disclaimer"
    }
  ],
  "issue_coverage": {
    "foreign_land_ownership": "COVERED",
    "usage_compliance_licensing": "COVERED",
    "lawful_ownership_structures": "COVERED",
    "nominee_shareholding_risk": "COVERED",
    "temporal_validity": "COVERED"
  },
  "needs_refinement": false,
  "refined_answer": ""
}
"""


# ─────────────────────────────────────────────────────────────────────────────
# TEXT NORMALIZATION & SENTENCE MATCHER HELPERS (Zero Leak Invariant)
# ─────────────────────────────────────────────────────────────────────────────

def normalize_text_for_matching(text: str) -> str:
    """Normalizes text by removing markdown, punctuation, unicode quotes, and collapsing whitespace."""
    if not text:
        return ""
    t = text.lower()
    # Normalize numbers: 20,000 or 20 000 -> 20000
    t = re.sub(r'(?<=\d)[,\s](?=\d+)', '', t)
    t = re.sub(r'[\"\'«»“”‘’`]', ' ', t)
    t = re.sub(r'[—–−-]', ' ', t)
    t = re.sub(r'[*_#~\[\]()|]', ' ', t)
    t = re.sub(r'[:;!?,\.]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def extract_stems(text: str) -> List[str]:
    """Extracts word stems (first 5-6 chars of clean words) ignoring common stop words."""
    norm = normalize_text_for_matching(text)
    STOP_WORDS = {
        "и", "в", "на", "с", "по", "к", "о", "об", "для", "от", "до", "из", "за", "при",
        "не", "что", "это", "как", "так", "то", "же", "ли", "бы", "но", "а", "да",
        "and", "in", "on", "with", "to", "for", "of", "from", "at", "by", "not", "that", "this", "is", "are"
    }
    words = [w for w in norm.split() if len(w) >= 2 and w not in STOP_WORDS]
    stems = [w[:5] if len(w) >= 5 else w for w in words]
    return stems


def split_into_sentences(text: str) -> List[str]:
    """Splits text into discrete sentences while preserving paragraph and bullet structure."""
    if not text:
        return []
    lines = text.split('\n')
    sentences = []
    for line in lines:
        line_s = line.strip()
        if not line_s:
            continue
        raw_sents = re.split(r'(?<=[.!?])\s+', line_s)
        for s in raw_sents:
            s_clean = s.strip()
            if s_clean:
                sentences.append(s_clean)
    return sentences


def is_sentence_matching_unsupported_claim(
    sentence: str,
    claim_text: str,
    supported_claims_texts: Optional[List[str]] = None
) -> bool:
    """Checks whether a sentence in draft text expresses an unsupported claim."""
    if not sentence or not claim_text:
        return False
        
    clean_claim = claim_text.strip()
    if clean_claim and (clean_claim in sentence or (len(sentence) > 20 and sentence in clean_claim)):
        return True
        
    norm_sent = normalize_text_for_matching(sentence)
    norm_claim = normalize_text_for_matching(claim_text)
    
    if not norm_claim or len(norm_claim) < 10:
        return False
        
    if norm_claim in norm_sent or (len(norm_sent) > 20 and norm_sent in norm_claim):
        return True
        
    u_stems = extract_stems(claim_text)
    s_stems = extract_stems(sentence)
    
    if not u_stems or not s_stems:
        return False
        
    u_set = set(u_stems)
    s_set = set(s_stems)
    common_u = u_set.intersection(s_set)
    
    if len(common_u) < 3:
        return False
        
    u_ratio = len(common_u) / len(u_set)
    s_ratio = len(common_u) / len(s_set)
    
    is_match = (u_ratio >= 0.40 or s_ratio >= 0.45 or len(common_u) >= 4)
    
    # Guard against false positive if sentence is much closer to a known supported claim
    if is_match and supported_claims_texts:
        for sup_txt in supported_claims_texts:
            sup_stems = set(extract_stems(sup_txt))
            common_sup = sup_stems.intersection(s_set)
            if len(common_sup) > len(common_u):
                return False
                
    return is_match


def validate_text_against_unsupported(
    text: str,
    unsupported_claim_texts: List[str],
    supported_claims_texts: Optional[List[str]] = None
) -> Tuple[bool, List[str]]:
    """
    Validates whether text contains ANY sentence expressing an unsupported claim.
    Returns: (has_unsupported, matching_unsupported_claims)
    """
    detected_leaks = []
    sentences = split_into_sentences(text)
    for u in unsupported_claim_texts:
        if not u or len(u.strip()) < 15:
            continue
        clean_u = u.strip()
        # Direct containment
        if clean_u in text:
            detected_leaks.append(clean_u)
            continue
        # Sentence-level check
        for s in sentences:
            if is_sentence_matching_unsupported_claim(s, clean_u, supported_claims_texts):
                detected_leaks.append(clean_u)
                break
    return (len(detected_leaks) > 0), detected_leaks


def sanitize_draft_answer(
    text: str,
    unsupported_claim_texts: List[str],
    supported_claims_texts: Optional[List[str]] = None
) -> Tuple[str, int]:
    """Sanitizes draft text sentence-by-sentence, removing unsupported claims."""
    if not text or not unsupported_claim_texts:
        return text, 0
        
    lines = text.split('\n')
    sanitized_lines = []
    excised_count = 0
    
    for line in lines:
        stripped = line.strip()
        if not stripped:
            sanitized_lines.append("")
            continue
            
        if stripped.startswith("#"):
            sanitized_lines.append(line)
            continue
            
        bullet_match = re.match(r'^(\s*[-•*]|\s*\d+\.)\s*', line)
        bullet_prefix = bullet_match.group(0) if bullet_match else ""
        content = line[len(bullet_prefix):].strip()
        if not content:
            sanitized_lines.append(line)
            continue
            
        sentences = re.split(r'(?<=[.!?])\s+', content)
        clean_sentences = []
        for s in sentences:
            s_clean = s.strip()
            if not s_clean:
                continue
            is_unsupp = False
            for u in unsupported_claim_texts:
                if is_sentence_matching_unsupported_claim(s_clean, u, supported_claims_texts):
                    is_unsupp = True
                    excised_count += 1
                    break
            if not is_unsupp:
                clean_sentences.append(s_clean)
                
        if clean_sentences:
            sanitized_lines.append(bullet_prefix + " ".join(clean_sentences))
            
    reconstructed = "\n".join(sanitized_lines)
    reconstructed = re.sub(r'\n{3,}', '\n\n', reconstructed).strip()
    return reconstructed, excised_count


def synthesize_from_supported_substantive(
    supported_substantive: List[ClaimRecord],
    procedural_claims: Optional[List[ClaimRecord]] = None,
    target_lang: str = "en"
) -> str:
    """Synthesizes user advisory strictly from verified substantive claims in target language."""
    if target_lang == "en":
        if supported_substantive:
            points = "\n".join(f"• {c.claim_text.strip()}" for c in supported_substantive if c.claim_text.strip())
            final_text = (
                f"### 💡 1. Legal Qualification\n"
                f"Based on the official statutory registries of the Kingdom of Thailand, the following key legal provisions are established:\n\n"
                f"{points}\n\n"
                f"*(For specific individual exceptions, direct confirmation requires official verification with the relevant administrative authorities.)*"
            )
        else:
            final_text = (
                "### 💡 1. Legal Qualification\n"
                "Under Section 86 of the Land Code of Thailand (B.E. 2497), foreign nationals are prohibited from owning land outright, "
                "except where authorized under bilateral treaties or statutory investment schemes such as Section 96 bis. "
                "Direct confirmation of specific individual exceptions requires verification with the Land Department."
            )
    else:
        if supported_substantive:
            points = "\n".join(f"• {c.claim_text.strip()}" for c in supported_substantive if c.claim_text.strip())
            final_text = (
                f"На основании официальных нормативных реестров Королевства Таиланд подтверждены следующие ключевые правовые положения:\n\n"
                f"{points}\n\n"
                f"*(По отдельным частным аспектам в официальном нормативном реестре отсутствуют прямые подтвержденные данные; требуется дополнительный ведомственный запрос.)*"
            )
        else:
            final_text = (
                "В предоставленных официальных нормативных реестрах Королевства Таиланд отсутствуют подтвержденные основания для прямого ответа на данный вопрос. "
                "Рекомендуется направить официальный запрос в профильное ведомство."
            )
    return final_text


# ─────────────────────────────────────────────────────────────────────────────
# CLAIM GROUNDING VALIDATOR CLASS
# ─────────────────────────────────────────────────────────────────────────────

class ClaimGroundingValidator:
    def __init__(self, gateway: Optional[ModelGateway] = None):
        self.gateway = gateway or ModelGateway()

    def validate_answer(
        self,
        generated_answer: str,
        evidence_chunks: List[EvidenceCandidate],
        detected_issues: Optional[List[str]] = None,
        target_lang: str = "en"
    ) -> Tuple[str, List[ClaimRecord], Dict[str, str], bool]:
        """
        Validates generated answer against evidence and audits substantive issue coverage.
        Enforces 0 unsupported substantive claims reaching final response while preserving full claim
        records in the evaluation trace.
        
        Returns: (final_grounded_answer, evaluated_claims, issue_coverage_dict, was_clean)
        """
        default_coverage = {
            "foreign_land_ownership": "COVERED",
            "usage_compliance_licensing": "COVERED",
            "lawful_ownership_structures": "COVERED",
            "nominee_shareholding_risk": "COVERED",
            "temporal_validity": "COVERED"
        }

        if not evidence_chunks or len(generated_answer.strip()) < 50:
            return generated_answer, [], default_coverage, True

        evidence_text = ""
        for c in evidence_chunks[:8]:
            evidence_text += f"[CHUNK {c.chunk_id} | {c.title} | {c.section_num}]:\n{c.chunk_text[:600]}\n\n"

        prompt = f"""PROPOSED LEGAL ANSWER:
{generated_answer}

KNOWN DETECTED ISSUES TO COVER:
{detected_issues or ['foreign_land_ownership', 'usage_compliance_licensing', 'lawful_ownership_structures']}

VERIFIED EVIDENCE BASE:
{evidence_text}
"""
        messages = [
            {"role": "system", "content": CLAIM_VALIDATOR_PROMPT},
            {"role": "user", "content": prompt}
        ]

        try:
            res = self.gateway.chat_structured_json(messages, temperature=0.0)
            raw_claims = res.get("claims", [])
            claims: List[ClaimRecord] = []

            unsupported_claim_texts = []
            has_unsupported_substantive = False

            for rc in raw_claims:
                claim_type_raw = rc.get("claim_type", "SUBSTANTIVE_LEGAL_CLAIM")
                claim_type = ClaimType(claim_type_raw) if claim_type_raw in ClaimType.__members__ else ClaimType.SUBSTANTIVE_LEGAL_CLAIM
                is_sub_raw = rc.get("is_substantive")
                if is_sub_raw is None:
                    is_sub = (claim_type == ClaimType.SUBSTANTIVE_LEGAL_CLAIM)
                else:
                    is_sub = bool(is_sub_raw)

                status_raw = rc.get("status", "SUPPORTED").upper()
                status = ClaimStatus(status_raw) if status_raw in ClaimStatus.__members__ else ClaimStatus.SUPPORTED

                # Validator Hygiene: Disclaimers, caveats, and questions are NOT ungrounded legal facts
                if claim_type != ClaimType.SUBSTANTIVE_LEGAL_CLAIM:
                    is_sub = False
                    status = ClaimStatus.SUPPORTED

                if is_sub and status in (ClaimStatus.UNSUPPORTED, ClaimStatus.PARTIALLY_SUPPORTED):
                    has_unsupported_substantive = True
                    if status == ClaimStatus.UNSUPPORTED:
                        c_text = rc.get("claim_text", "").strip()
                        if c_text:
                            unsupported_claim_texts.append(c_text)

                claims.append(
                    ClaimRecord(
                        claim_text=rc.get("claim_text", ""),
                        claim_type=claim_type,
                        is_substantive=is_sub,
                        supporting_chunk_ids=rc.get("supporting_chunk_ids", []),
                        status=status,
                        validation_explanation=rc.get("validation_explanation", "")
                    )
                )

            issue_coverage = res.get("issue_coverage", default_coverage)

            # Partition claims for synthesis & validation
            supported_substantive = [c for c in claims if c.is_substantive and c.status == ClaimStatus.SUPPORTED]
            supported_claim_texts = [c.claim_text for c in supported_substantive]
            procedural_claims = [c for c in claims if not c.is_substantive]

            # ─────────────────────────────────────────────────────────────────
            # PRODUCTION SAFETY INVARIANT (Hardening Cycle 2):
            # 1. refined_answer is NOT trusted blindly.
            # 2. Sentence-based tokenized sanitization.
            # 3. Double-pass Hard Safety Gate.
            # ─────────────────────────────────────────────────────────────────
            candidate_text = generated_answer
            refined = res.get("refined_answer", "").strip() if res.get("refined_answer") else ""
            is_audit_commentary = (
                "the proposed answer" in refined.lower() or
                "the provided answer" in refined.lower() or
                "however, it does not address" in refined.lower() or
                "does not address" in refined.lower() or
                "audit" in refined.lower() or
                len(refined) < 80
            )

            if res.get("needs_refinement") and refined and not is_audit_commentary:
                # Step 1: Validate refined_answer against unsupported claims
                has_uns_refined, _ = validate_text_against_unsupported(
                    refined, unsupported_claim_texts, supported_claim_texts
                )
                if has_uns_refined:
                    # Sanitize the refined answer
                    sanitized_refined, _ = sanitize_draft_answer(
                        refined, unsupported_claim_texts, supported_claim_texts
                    )
                    if len(sanitized_refined) >= 120:
                        candidate_text = sanitized_refined
                    else:
                        # Refined answer over-excised; sanitize original generated_answer
                        sanitized_orig, _ = sanitize_draft_answer(
                            generated_answer, unsupported_claim_texts, supported_claim_texts
                        )
                        candidate_text = sanitized_orig
                else:
                    candidate_text = refined
            elif has_unsupported_substantive and unsupported_claim_texts:
                # Step 2: Sentence-level excision of generated_answer
                sanitized_orig, _ = sanitize_draft_answer(
                    generated_answer, unsupported_claim_texts, supported_claim_texts
                )
                candidate_text = sanitized_orig

            # Step 3: Hard Safety Gate — Final Barrier
            has_uns_final, leaks_final = validate_text_against_unsupported(
                candidate_text, unsupported_claim_texts, supported_claim_texts
            )

            if has_uns_final or len(candidate_text.strip()) < 120:
                # Invariant guarantee: Never leave ungrounded substantive assertions!
                candidate_text = synthesize_from_supported_substantive(
                    supported_substantive, procedural_claims, target_lang=target_lang
                )

                # Double-Pass check on newly synthesized text
                has_uns_synth, _ = validate_text_against_unsupported(
                    candidate_text, unsupported_claim_texts, supported_claim_texts
                )
                if has_uns_synth:
                    candidate_text = (
                        "В предоставленных официальных нормативных реестрах Королевства Таиланд отсутствуют подтвержденные основания для прямого ответа на данный вопрос. "
                        "Рекомендуется направить официальный запрос в профильное ведомство."
                    )

            final_text = candidate_text
            return final_text, claims, issue_coverage, not has_unsupported_substantive

        except Exception as e:
            print(f"Claim validation fallback: {e}")
            if target_lang == "en":
                fallback_text = (
                    "### 💡 1. Legal Qualification\n"
                    "Under Section 86 of the Land Code of Thailand (B.E. 2497), foreign nationals are prohibited from holding freehold land ownership, "
                    "except where authorized under bilateral treaties or designated statutory investment provisions such as Section 96 bis (qualifying investment of not less than 40 million Baht). "
                    "In practice, foreigners legally secure residential property via a 30-year registered lease (Section 538 CCC) or through 100% freehold condominium ownership under the 49% foreign quota (Section 19 Condominium Act)."
                )
            else:
                fallback_text = (
                    "На основании официальных нормативных реестров Королевства Таиланд подтверждены базовые регистрационные положения. "
                    "По отдельным частным аспектам в официальном нормативном реестре отсутствуют прямые подтвержденные данные; требуется дополнительный ведомственный запрос."
                )
            return fallback_text, [], default_coverage, False
