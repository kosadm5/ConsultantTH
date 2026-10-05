"""
backend/core/pipeline/conversation_brain.py
Consultant+ Core Engine 2.0 — Multilingual Conversation Brain with Topic Relation & Adaptive Retrieval Policy.
Understands user input across Russian, English, Thai, and mixed code-switching.
Extracts canonical, language-independent facts vs assumptions, detects corrections,
identifies missing legal information, and outputs explicit language detection.
"""

import re
from typing import Dict, Any, List, Optional
from core.models import (
    UserTurnInput,
    LegalCaseState,
    ResponseMode,
    FactType
)
from core.gateway import ModelGateway


SYSTEM_PROMPT = """You are the Senior Multilingual Legal Intake & Qualification Brain of Consultant+ for the Kingdom of Thailand.
Your duty is to analyze the user's message in the context of their existing case dossier across Russian, English, Thai, or mixed code-switching.

TASKS:
1. Language Detection:
   - "detected_language": "ru" | "en" | "th" | "zh"
   - "response_language": The language the user expects to be answered in (match dominant user language).
   - "language_confidence": 0.0 - 1.0
   - "is_mixed_language": true/false (e.g. "Хочу купить villa для short-term rental в Phuket")

2. Canonical Legal Fact Extraction (Language-Independent):
   Extract facts using standard canonical keys and values:
   - "property_type": "villa" | "condominium" | "land" | "commercial"
   - "purpose_of_acquisition": "investment" | "own_living" | "mixed"
   - "usage_purpose": "short_term_rental_to_tourists" | "long_term_residential_lease" | "commercial_operations"
   - "role": "investor" | "buyer" | "tenant" | "spouse" | "director"
   - "nationality": "Russian" | "Kazakhstani" | "American" | "Thai" | etc.
   - "location": "Phuket" | "Pattaya" | "Bangkok" | "Hua Hin" | "Samui" | etc.

   Label each fact_type:
   - "USER_FACT": newly stated fact
   - "USER_CORRECTION": user correcting, changing, or negating a previous fact (e.g., changing from short-term to long-term rental, or correcting nationality). You MUST emit the new canonical value with fact_type "USER_CORRECTION" so it supersedes the previous value.
   - "SYSTEM_ASSUMPTION": inference from context

3. Missing Information (Unknowns):
   Critical legal prerequisites still needed (e.g. "nationality", "budget", "property_type", "usage_purpose").

4. Response Mode:
   - "DIRECT_ANSWER": User provided all necessary constraints or asked a direct statutory question.
   - "ANSWER_AND_CLARIFY": Broad exploratory question needing structured overview + 1 high-yield clarifying question.
   - "CLARIFY_FIRST": Action legally perilous without immediate clarification.

5. Topic Relation:
   - "NEW_TOPIC": user transitioned to a different legal matter (e.g. from real estate purchase to employee termination or company tax).
   - "CONTINUE": user is continuing the existing matter / logical follow-up question ("What if through a Thai company?", "What are the registration fees?").
   - "MODIFY_FACT": user is correcting, overriding, or negating a previously stated fact ("No, actually it is...", "I am from Kazakhstan, not Russia").
   - "CLARIFY": user is answering a specific question asked by the consultant.
   - "RETURN_TO_TOPIC": user explicitly returns to an earlier discussed matter ("Let's go back to the villa...", "Regarding the first question...").

6. Retrieval Decision:
   - "DIRECT_ANSWER": greeting, capabilities, or self-contained legal definition.
   - "CONTEXT_ONLY": follow-up fully covered by verified rules already in the case dossier.
   - "REUSE_EVIDENCE": ongoing matter where existing retrieved Thai statutes remain directly relevant and sufficient.
   - "RETRIEVE": new legal topic or new statutory search needed in Thai KB.
   - "RETRIEVE_WITH_EXPANSION": complex multi-statute scenario.

CRITICAL RULE: Do NOT hardcode or output specific statutory section numbers (like Section 19 or Section 538).
Output strictly JSON:
{
  "detected_language": "ru",
  "response_language": "ru",
  "language_confidence": 0.98,
  "is_mixed_language": false,
  "primary_intent": "property_acquisition",
  "confidence": 0.95,
  "matter_type": "property_acquisition",
  "topic_relation": "NEW_TOPIC",
  "retrieval_decision": "RETRIEVE",
  "extracted_facts": [
    {"entity": "property_type", "value": "villa", "fact_type": "USER_FACT", "confidence": 1.0}
  ],
  "missing_unknowns": ["nationality", "budget"],
  "response_mode": "ANSWER_AND_CLARIFY",
  "qualification_summary": "User interested in villa acquisition for investment."
}
"""


class ConversationBrain:
    def __init__(self, gateway: Optional[ModelGateway] = None):
        self.gateway = gateway or ModelGateway()

    @staticmethod
    def fallback_detect_language(text: str) -> str:
        """Fast regex heuristic fallback for script identification."""
        if re.search(r'[\u0e00-\u0e7f]', text):
            return "th"
        if re.search(r'[\u0400-\u04ff]', text):
            return "ru"
        if re.search(r'[\u4e00-\u9fff]', text):
            return "zh"
        return "en"

    def analyze_turn(
        self,
        user_input: UserTurnInput,
        case_state: LegalCaseState
    ) -> Dict[str, Any]:
        """Runs LLM intake analysis on user message + existing active facts."""
        active_facts = case_state.get_active_facts()
        script_lang = self.fallback_detect_language(user_input.raw_text)
        
        context_prompt = f"""EXISTING CASE DOSSIER:
Matter: {case_state.matter_type}
Turn: {case_state.turn_index}
Known Active Facts: {active_facts}
Current Unknowns: {case_state.unknowns}
Client Language Hint: {user_input.language_hint or script_lang}

NEW USER MESSAGE ({user_input.input_type}):
\"{user_input.raw_text}\"
"""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": context_prompt}
        ]

        try:
            res = self.gateway.chat_structured_json(messages, temperature=0.1)
            # Ensure detected_language and response_language exist
            if not res.get("detected_language"):
                res["detected_language"] = script_lang
            if not res.get("response_language"):
                res["response_language"] = res["detected_language"]
            if not res.get("topic_relation"):
                res["topic_relation"] = "CONTINUE" if case_state.turn_index > 0 else "NEW_TOPIC"
            if not res.get("retrieval_decision"):
                res["retrieval_decision"] = "RETRIEVE"
            return res
        except Exception as e:
            print(f"ConversationBrain fallback due to error: {e}")
            lang = user_input.language_hint or script_lang
            lower_txt = user_input.raw_text.lower()
            topic_rel = "NEW_TOPIC"
            if case_state.turn_index > 0:
                if any(w in lower_txt for w in ["нет,", "ошибся", "no,", "actually", "ไม่ใช่"]):
                    topic_rel = "MODIFY_FACT"
                elif any(w in lower_txt for w in ["вернемся", "let's go back", "กลับไป"]):
                    topic_rel = "RETURN_TO_TOPIC"
                else:
                    topic_rel = "CONTINUE"

            return {
                "detected_language": lang,
                "response_language": lang,
                "language_confidence": 0.8,
                "is_mixed_language": False,
                "primary_intent": "legal_inquiry",
                "confidence": 0.7,
                "matter_type": case_state.matter_type or "general_inquiry",
                "topic_relation": topic_rel,
                "retrieval_decision": "RETRIEVE",
                "extracted_facts": [],
                "missing_unknowns": [],
                "response_mode": "ANSWER_AND_CLARIFY",
                "qualification_summary": "General inquiry"
            }
