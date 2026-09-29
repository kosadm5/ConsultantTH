"""
backend/core/models.py
Consultant+ Core Engine 2.0 — Unified Pydantic v2 Contracts.
Strictly decoupled, jurisdiction-agnostic, and supporting temporal/historical state,
full multilingual language detection & cross-lingual session continuity.
"""

from __future__ import annotations
import uuid
import time
from enum import Enum
from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────────────────────────────────────────
# 1. INPUT CONTRACT (Voice-ready & Multilingual)
# ─────────────────────────────────────────────────────────────────────────────

class VoiceMetadata(BaseModel):
    duration_sec: float = 0.0
    stt_confidence: float = 1.0  # 0.0 - 1.0
    sample_rate: Optional[int] = None
    transcription_engine: str = "whisper_or_external"


class UserTurnInput(BaseModel):
    user_id: str
    case_id: Optional[str] = None
    input_type: Literal["text", "voice"] = "text"
    raw_text: str
    voice_metadata: Optional[VoiceMetadata] = None
    language_hint: Optional[str] = None
    session_id: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# 2. USER PROFILE vs CASE STATE (Decoupled)
# ─────────────────────────────────────────────────────────────────────────────

class UserProfile(BaseModel):
    user_id: str
    preferred_language: str = "en"
    jurisdiction_focus: str = "Thailand"
    communication_style: str = "concise_authoritative"
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    active_case_ids: List[str] = Field(default_factory=list)


class FactType(str, Enum):
    USER_FACT = "USER_FACT"                    # Explicitly stated by user
    USER_CORRECTION = "USER_CORRECTION"        # Overriding a prior statement
    SYSTEM_ASSUMPTION = "SYSTEM_ASSUMPTION"    # Hypothesized by system (unconfirmed)
    CONFLICTING_FACT = "CONFLICTING_FACT"      # Contradicts existing facts
    LEGAL_EVIDENCE = "LEGAL_EVIDENCE"          # Rule/section extracted from verified law
    CONCLUSION = "CONCLUSION"                  # Synthesized finding


class FactRecord(BaseModel):
    fact_id: str = Field(default_factory=lambda: f"f_{uuid.uuid4().hex[:8]}")
    fact_type: FactType = FactType.USER_FACT
    entity: str                                # Canonical concept: e.g. "role", "property_type", "purpose_of_acquisition"
    value: Any                                 # Canonical value: e.g. "investor", "villa", "short_term_rental_to_tourists"
    confidence: float = 1.0
    turn_id: int = 1
    source: str = "user_input"
    timestamp: float = Field(default_factory=time.time)
    superseded_by: Optional[str] = None        # Pointer to newer fact_id if corrected
    is_active: bool = True


class ResponseMode(str, Enum):
    DIRECT_ANSWER = "DIRECT_ANSWER"            # Complete answer, all critical facts known
    ANSWER_AND_CLARIFY = "ANSWER_AND_CLARIFY"  # Substantial overview + 1 targeted question
    CLARIFY_FIRST = "CLARIFY_FIRST"            # Action legally perilous without more data
    SAFE_DEGRADED = "SAFE_DEGRADED"            # Raw verified materials on LLM/network failure


class LegalCaseState(BaseModel):
    case_id: str = Field(default_factory=lambda: f"case_{uuid.uuid4().hex[:8]}")
    user_id: str
    matter_type: str = "general_inquiry"       # e.g. "property_acquisition", "visa_application"
    jurisdiction: str = "Thailand"
    event_date: Optional[str] = None           # ISO or Year for temporal applicability
    turn_index: int = 0
    facts: List[FactRecord] = Field(default_factory=list)
    unknowns: List[str] = Field(default_factory=list)          # Missing facts required for advice
    legal_issues: List[str] = Field(default_factory=list)      # Abstract legal issues under review
    current_mode: ResponseMode = ResponseMode.ANSWER_AND_CLARIFY
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    def get_active_facts(self) -> Dict[str, Any]:
        """Returns map of active entity -> canonical value."""
        return {f.entity: f.value for f in self.facts if f.is_active and not f.superseded_by}

    def add_or_update_fact(self, entity: str, value: Any, fact_type: FactType = FactType.USER_FACT, confidence: float = 1.0, turn_id: int = 1) -> FactRecord:
        for existing in self.facts:
            if existing.entity == entity and existing.is_active:
                if existing.value == value:
                    return existing
                new_fact = FactRecord(
                    fact_type=FactType.USER_CORRECTION if fact_type == FactType.USER_FACT else fact_type,
                    entity=entity,
                    value=value,
                    confidence=confidence,
                    turn_id=turn_id,
                    source="user_correction" if fact_type == FactType.USER_FACT else "inferred"
                )
                existing.superseded_by = new_fact.fact_id
                existing.is_active = False
                self.facts.append(new_fact)
                self.updated_at = time.time()
                return new_fact

        new_fact = FactRecord(
            fact_type=fact_type,
            entity=entity,
            value=value,
            confidence=confidence,
            turn_id=turn_id,
            source="user_input"
        )
        self.facts.append(new_fact)
        self.updated_at = time.time()
        return new_fact


# ─────────────────────────────────────────────────────────────────────────────
# 3. ISSUE-BASED QUERY PLANNER (Multilingual & No Hardcoded Statutes)
# ─────────────────────────────────────────────────────────────────────────────

class LegalIssue(BaseModel):
    issue_id: str
    name: str                                  # e.g. "foreign_land_holding_restrictions"
    description: str                           # e.g. "Limitations on non-citizens owning freehold land"
    priority: int = 1                          # 1 = Highest


class QueryPlan(BaseModel):
    original_query: str
    canonical_summary: str
    detected_issues: List[LegalIssue] = Field(default_factory=list)
    activated_legal_concepts: List[str] = Field(default_factory=list)
    dense_queries: List[str] = Field(default_factory=list)    # Search phrases in EN/TH
    lexical_queries: List[str] = Field(default_factory=list)  # Search terms for full-text FTS
    temporal_anchor_year: Optional[int] = None

    @field_validator('dense_queries', 'lexical_queries', 'activated_legal_concepts', mode='before')
    @classmethod
    def coerce_query_lists(cls, v):
        if isinstance(v, str):
            return [v] if v.strip() else []
        if isinstance(v, list):
            return [str(x) for x in v if x is not None]
        return []


# ─────────────────────────────────────────────────────────────────────────────
# 4. EVIDENCE & TEMPORAL VERSIONING
# ─────────────────────────────────────────────────────────────────────────────

class TemporalValidity(BaseModel):
    is_active: bool = True
    effective_date_be: Optional[str] = None
    effective_date_ce: Optional[str] = None
    repealed_date_be: Optional[str] = None
    repealed_date_ce: Optional[str] = None
    last_amended_act: Optional[str] = None
    repealed_by: Optional[str] = None


class EvidenceCandidate(BaseModel):
    chunk_id: str
    doc_id: str
    title: str
    section_num: str
    chunk_text: str
    domain: str = "GENERAL"
    temporal_validity: TemporalValidity = Field(default_factory=TemporalValidity)
    authority_score: float = 1.0
    anchor_score: float = 0.0
    is_concept_anchor: bool = False
    dense_score: float = 0.0
    lexical_score: float = 0.0
    rrf_score: float = 0.0
    rerank_score: float = 0.0
    final_evidence_score: float = 0.0
    is_selected: bool = False
    rejection_reason: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# 5. REASONING PLAN & CLAIM-LEVEL GROUNDING
# ─────────────────────────────────────────────────────────────────────────────

class ReasoningPlan(BaseModel):
    legal_qualification: str
    applicable_options: List[Dict[str, Any]] = Field(default_factory=list)
    statutory_prohibitions: List[str] = Field(default_factory=list)
    financial_and_tax_formalities: List[str] = Field(default_factory=list)
    unknowns_identified: List[str] = Field(default_factory=list)
    next_high_yield_question: Optional[str] = None
    next_high_yield_question_target_lang: Optional[str] = None
    response_mode: ResponseMode = ResponseMode.ANSWER_AND_CLARIFY

    @field_validator('statutory_prohibitions', 'financial_and_tax_formalities', 'unknowns_identified', mode='before')
    @classmethod
    def coerce_list_of_strings(cls, v):
        if isinstance(v, str):
            return [v] if v.strip() else []
        if isinstance(v, list):
            return [str(x) for x in v if x is not None]
        return []

    @field_validator('applicable_options', mode='before')
    @classmethod
    def coerce_applicable_options(cls, v):
        if isinstance(v, list):
            res = []
            for item in v:
                if isinstance(item, dict):
                    res.append(item)
                elif isinstance(item, str):
                    res.append({"title": item, "description": item})
            return res
        elif isinstance(v, dict):
            return [v]
        elif isinstance(v, str):
            return [{"title": v, "description": v}]
        return []


class ClaimStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"


class ClaimType(str, Enum):
    SUBSTANTIVE_LEGAL_CLAIM = "SUBSTANTIVE_LEGAL_CLAIM"
    PROCEDURAL_DISCLAIMER = "PROCEDURAL_DISCLAIMER"
    CLARIFYING_QUESTION = "CLARIFYING_QUESTION"
    CAVEAT_RESERVATION = "CAVEAT_RESERVATION"


class ClaimRecord(BaseModel):
    claim_id: str = Field(default_factory=lambda: f"cl_{uuid.uuid4().hex[:6]}")
    claim_text: str
    claim_type: ClaimType = ClaimType.SUBSTANTIVE_LEGAL_CLAIM
    is_substantive: bool = True
    citing_section: Optional[str] = None
    supporting_chunk_ids: List[str] = Field(default_factory=list)
    status: ClaimStatus = ClaimStatus.SUPPORTED
    validation_explanation: str = ""
    refined_text: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# 6. RESPONSE & TRACE
# ─────────────────────────────────────────────────────────────────────────────

class StatutoryReferenceUI(BaseModel):
    id: str
    key: str
    title: str
    section_num: str
    snippet: str
    full_text: str
    official_th: str
    official_th_section: str
    official_th_text: str
    status: str = "ACTIVE"
    status_th: str = "มีผลใช้บังคับ"
    score: float = 0.95


class PrecedentReferenceUI(BaseModel):
    doc_id: str
    deka_no: str
    headline: str
    full_text: str


class ConsultantResponse(BaseModel):
    answer: str
    lang: str = "ru"
    statutory_references: List[Dict[str, Any]] = Field(default_factory=list)
    precedents: List[Dict[str, Any]] = Field(default_factory=list)
    proactive_clarifications: List[str] = Field(default_factory=list)
    domain: str = "GENERAL"
    mode: ResponseMode = ResponseMode.ANSWER_AND_CLARIFY
    trace_id: str
    session_id: Optional[str] = None
    sources: List[Dict[str, Any]] = Field(default_factory=list)


class StageLatency(BaseModel):
    stage: str
    duration_ms: float


class AgentTrace(BaseModel):
    trace_id: str = Field(default_factory=lambda: f"tr_{uuid.uuid4().hex[:12]}")
    request_id: str = Field(default_factory=lambda: f"req_{uuid.uuid4().hex[:8]}")
    user_id: str
    case_id: str
    turn_index: int
    input_type: str
    raw_input: str
    
    # Multilingual tracking
    detected_language: str = "ru"
    response_language: str = "ru"
    language_confidence: float = 1.0
    language_switch_detected: bool = False

    latencies: List[StageLatency] = Field(default_factory=list)
    case_state_before: Dict[str, Any] = Field(default_factory=dict)
    query_plan: Optional[QueryPlan] = None
    retrieval_dense_count: int = 0
    retrieval_lexical_count: int = 0
    retrieval_graph_count: int = 0
    rrf_candidate_count: int = 0
    reranked_top_count: int = 0
    discarded_chunks_reasons: Dict[str, str] = Field(default_factory=dict)
    
    reasoning_plan: Optional[ReasoningPlan] = None
    claims_evaluated: List[ClaimRecord] = Field(default_factory=list)
    issue_coverage: Dict[str, str] = Field(default_factory=dict)
    case_state_after: Dict[str, Any] = Field(default_factory=dict)
    
    fallback_triggered: bool = False
    degraded_mode: bool = False
    timestamp: float = Field(default_factory=time.time)
