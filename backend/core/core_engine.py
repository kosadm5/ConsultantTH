"""
backend/core/core_engine.py
Consultant+ Core Engine 2.0 — Master Multilingual Legal AI Orchestrator.
Seamlessly unifies RU / EN / TH / Mixed inputs into a language-independent CaseState,
executes issue-based multilingual retrieval, performs two-pass reasoning, and composes
the authoritative response strictly in the user's detected response_language.
"""

import time
from typing import Optional, Dict, Any, List

from core.models import (
    UserTurnInput,
    UserProfile,
    LegalCaseState,
    ConsultantResponse,
    ResponseMode,
    AgentTrace
)
from core.gateway import ModelGateway
from core.telemetry.trace_logger import AgentTraceLogger
from core.state.case_manager import CaseStateManager
from core.adapters.thai_adapter import THKnowledgeAdapter
from core.retrieval.evidence_engine import EvidenceEngine
from core.retrieval.hybrid_retriever import MasterHybridRetriever
from core.pipeline.conversation_brain import ConversationBrain
from core.pipeline.query_planner import QueryPlanner
from core.pipeline.reasoning_engine import TwoPassReasoningEngine
from core.pipeline.claim_validator import ClaimGroundingValidator
from core.pipeline.response_composer import ResponseComposer
from core.pipeline.degraded_mode import SafeDegradedHandler



def detect_matter_type(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ["налог", "tax", "ภาษี", "p.161", "p161", "п.161", "п161", "161/2566", "162/2567", "remittance", "ввоз денег", "перевод денег", "доход из-за границы", "ндфл", "pit", "сбор", "пошлин"]):
        return "taxation"
    if any(w in t for w in ["виз", "visa", "วีซ่า", "ltr", "dtv", "elite", "work permit", "ворк пермит", "разрешение на работу", "внж", "residence", "overstay", "бордер", "выезд"]):
        return "immigration_visa"
    if any(w in t for w in ["увольнен", "компенсац", "severance", "dismissal", "labor", "เลิกจ้าง", "ค่าชดเชย", "сотрудник", "работник", "зарплат", "отпуск", "трудов"]):
        return "labor_employment"
    if any(w in t for w in ["завещан", "наслед", "will", "probate", "heir", "พินัยกรรม", "มรดก", "ทายาท", "смерт", "умер"]):
        return "inheritance_estate"
    if any(w in t for w in ["номин", "nominee", "นอมินี", "компани", "бизнес", "fba", "юридическ", "акционер", "director", "директор", "учредител", "51/49", "firm"]):
        return "corporate_business"
    if any(w in t for w in ["недвиж", "condo", "villa", "дом", "квартир", "วิลล่า", "ที่ดิน", "คอนโด", "leasehold", "freehold", "аренд", "покупк", "земл", "собственност"]):
        return "property_acquisition"
    if any(w in t for w in ["брак", "брачн", "супруг", "тайка", "жена", "муж", "prenup", "marriage", "สมรส"]):
        return "family_marriage"
    return "general_inquiry"


class ConsultantPlusCoreEngine:
    def __init__(
        self,
        gateway: Optional[ModelGateway] = None,
        adapter: Optional[THKnowledgeAdapter] = None,
        case_manager: Optional[CaseStateManager] = None,
        trace_logger: Optional[AgentTraceLogger] = None
    ):
        self.gateway = gateway or ModelGateway()
        self.adapter = adapter or THKnowledgeAdapter()
        self.case_manager = case_manager or CaseStateManager()
        self.trace_logger = trace_logger or AgentTraceLogger()

        self.evidence_engine = EvidenceEngine()
        self.retriever = MasterHybridRetriever(adapter=self.adapter, evidence_engine=self.evidence_engine)
        self.brain = ConversationBrain(gateway=self.gateway)
        self.query_planner = QueryPlanner(gateway=self.gateway)
        self.reasoning_engine = TwoPassReasoningEngine(gateway=self.gateway)
        self.claim_validator = ClaimGroundingValidator(gateway=self.gateway)

    def process_turn(self, turn_input: UserTurnInput) -> ConsultantResponse:
        """Processes a single conversational legal consultation turn end-to-end with full multilingual trace."""
        user_id = turn_input.user_id
        
        # 1. Voice Guardrail: verify STT confidence
        if turn_input.input_type == "voice" and turn_input.voice_metadata:
            if turn_input.voice_metadata.stt_confidence < 0.70:
                lang = turn_input.language_hint or "ru"
                clarif = {
                    "ru": "Пожалуйста, повторите голосовое сообщение чуть ближе к микрофону или введите ваш вопрос текстом.",
                    "en": "The audio recognition confidence is below legal threshold. Please repeat closer to the microphone or type your question.",
                    "th": "ความชัดเจนของเสียงต่ำกว่าเกณฑ์ทางกฎหมาย กรุณาส่งข้อความเสียงอีกครั้งหรือพิมพ์คำถามทางข้อความครับ"
                }.get(lang, "Please repeat your question with higher audio clarity or type it in text.")
                return ConsultantResponse(
                    answer=f"### 🎙️ Audio Recognition Quality Notice\n\n{clarif}",
                    lang=lang,
                    proactive_clarifications=["Повторить вопрос текстом" if lang == "ru" else "Type question in text"],
                    domain="GENERAL",
                    trace_id="voice_low_confidence"
                )

        # 2. Resolve User Profile & Case State
        profile = self.case_manager.get_or_create_profile(user_id)
        prior_lang = profile.preferred_language
        
        # Determine current matter type from turn input
        current_detected_matter = detect_matter_type(turn_input.raw_text)
        
        case_state = self.case_manager.get_or_create_case(
            user_id=user_id,
            case_id=turn_input.case_id,
            matter_type=current_detected_matter if current_detected_matter != "general_inquiry" else "general_inquiry"
        )
        if current_detected_matter != "general_inquiry" and case_state.matter_type != current_detected_matter:
            case_state.matter_type = current_detected_matter
            
        current_turn = case_state.turn_index + 1

        # 3. Start Agent Trace
        trace = self.trace_logger.start_trace(
            user_id=user_id,
            case_id=case_state.case_id,
            turn_index=current_turn,
            input_type=turn_input.input_type,
            raw_input=turn_input.raw_text
        )
        self.trace_logger.record_case_before(case_state.model_dump())

        try:
            # 4. Stage: Multilingual Conversation Brain
            with self.trace_logger.measure_stage("conversation_understanding"):
                brain_analysis = self.brain.analyze_turn(turn_input, case_state)

            detected_lang = brain_analysis.get("detected_language", "en")
            # CRITICAL: Response language is governed strictly by user's profile / explicit language_hint
            if turn_input.language_hint and turn_input.language_hint in ["en", "th", "ru", "zh"]:
                response_lang = turn_input.language_hint
            elif profile.preferred_language in ["en", "th", "ru", "zh"]:
                response_lang = profile.preferred_language
            else:
                response_lang = "en"

            lang_confidence = float(brain_analysis.get("language_confidence", 1.0))
            is_switch = (prior_lang != response_lang) and (case_state.turn_index > 0)

            # Update trace with language metrics
            trace.detected_language = detected_lang
            trace.response_language = response_lang
            trace.language_confidence = lang_confidence
            trace.language_switch_detected = is_switch

            # Only update profile's active language if explicitly selected/hinted by user
            if turn_input.language_hint and turn_input.language_hint in ["en", "th", "ru", "zh"]:
                profile.preferred_language = response_lang
                profile.updated_at = time.time()

            extracted_facts = brain_analysis.get("extracted_facts", [])
            missing_unknowns = brain_analysis.get("missing_unknowns", [])
            response_mode_raw = brain_analysis.get("response_mode", "ANSWER_AND_CLARIFY")
            response_mode = ResponseMode(response_mode_raw) if response_mode_raw in ResponseMode.__members__ else ResponseMode.ANSWER_AND_CLARIFY

            # Update Case State with new canonical facts and active matter
            case_state = self.case_manager.apply_turn_update(
                case_id=case_state.case_id,
                turn_index=current_turn,
                extracted_facts=extracted_facts,
                detected_issues=[],
                identified_unknowns=missing_unknowns,
                response_mode=response_mode,
                matter_type=case_state.matter_type
            )

            # 5. Stage: Issue-Based Query Planner (Multilingual EN/TH search generation)
            with self.trace_logger.measure_stage("query_planning"):
                query_plan = self.query_planner.plan_queries(turn_input.raw_text, case_state)
            self.trace_logger.record_query_plan(query_plan)

            # 6. Stage: Master Hybrid Retrieval + RRF + Reranking
            with self.trace_logger.measure_stage("hybrid_retrieval_and_rerank"):
                evidence_chunks, discarded_reasons, counts = self.retriever.retrieve(
                    query_plan=query_plan,
                    top_evidence=8,
                    event_year=2026
                )
            
            self.trace_logger.record_retrieval_counts(
                dense=counts["dense_count"],
                lexical=counts["lexical_count"],
                graph=counts["graph_count"],
                rrf=counts["rrf_pool_count"],
                reranked=counts["selected_evidence_count"]
            )
            for cid, reason in discarded_reasons.items():
                self.trace_logger.record_chunk_rejection(cid, reason)

            # Check if retrieval yielded 0 evidence -> Safe Degraded Mode
            if not evidence_chunks:
                self.trace_logger.mark_fallback(degraded=True)
                degraded_resp = SafeDegradedHandler.build_degraded_response(
                    query=turn_input.raw_text,
                    evidence_chunks=[],
                    lang=response_lang,
                    trace_id=trace.trace_id
                )
                self.trace_logger.finalize_and_save()
                return degraded_resp

            # 7. Stage: Two-Pass Legal Reasoning in response_lang (Authoritative CURRENT USER INQUIRY)
            with self.trace_logger.measure_stage("legal_reasoning_pass1_and_pass2"):
                reasoning_plan, raw_generated_answer = self.reasoning_engine.execute_two_pass_reasoning(
                    case_state=case_state,
                    evidence_chunks=evidence_chunks,
                    target_lang=response_lang,
                    user_query=turn_input.raw_text
                )
            self.trace_logger.record_reasoning_plan(reasoning_plan)

            # 8. Stage: Claim-Level Grounding Validation & Substantive Issue Coverage
            with self.trace_logger.measure_stage("claim_grounding_validation"):
                detected_issue_names = [iss.name for iss in query_plan.detected_issues]
                validated_answer, claims, issue_coverage, was_clean = self.claim_validator.validate_answer(
                    generated_answer=raw_generated_answer,
                    evidence_chunks=evidence_chunks,
                    detected_issues=detected_issue_names,
                    target_lang=response_lang
                )
            self.trace_logger.record_claims(claims)
            self.trace_logger.record_issue_coverage(issue_coverage)

            # 9. Stage: Response Composition
            with self.trace_logger.measure_stage("response_composition"):
                final_response = ResponseComposer.compose(
                    validated_text=validated_answer,
                    reasoning_plan=reasoning_plan,
                    evidence_chunks=evidence_chunks,
                    lang=response_lang,
                    trace_id=trace.trace_id,
                    session_id=turn_input.session_id
                )

            # 10. Record Case State After and Finalize Trace
            self.trace_logger.record_case_after(case_state.model_dump())
            self.trace_logger.finalize_and_save()

            return final_response

        except Exception as e:
            print(f"Core Engine exception, engaging Safe Degraded Mode: {e}")
            self.trace_logger.mark_fallback(degraded=True)
            fallback_resp = SafeDegradedHandler.build_degraded_response(
                query=turn_input.raw_text,
                evidence_chunks=[],
                lang=profile.preferred_language or "ru",
                trace_id=trace.trace_id
            )
            self.trace_logger.finalize_and_save()
            return fallback_resp
