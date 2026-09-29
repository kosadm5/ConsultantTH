"""
backend/core/state/case_manager.py
Consultant+ Core Engine 2.0 — Decoupled UserProfile and LegalCaseState Manager.
Handles multi-case tracking per user, historical fact logging, corrections, and conflict detection.
"""

import os
import json
import time
from typing import Dict, Any, Optional, List
from core.models import (
    UserProfile,
    LegalCaseState,
    FactRecord,
    FactType,
    ResponseMode
)


class CaseStateManager:
    def __init__(self, persistence_dir: Optional[str] = None):
        self.persistence_dir = persistence_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "data", "case_store"
        )
        os.makedirs(self.persistence_dir, exist_ok=True)
        self.profiles: Dict[str, UserProfile] = {}
        self.cases: Dict[str, LegalCaseState] = {}
        self._load_all()

    def _load_all(self):
        profile_file = os.path.join(self.persistence_dir, "profiles.json")
        if os.path.exists(profile_file):
            try:
                with open(profile_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for uid, pdata in data.items():
                        self.profiles[uid] = UserProfile(**pdata)
            except Exception as e:
                print(f"Error loading profiles: {e}")

        case_file = os.path.join(self.persistence_dir, "cases.json")
        if os.path.exists(case_file):
            try:
                with open(case_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for cid, cdata in data.items():
                        self.cases[cid] = LegalCaseState(**cdata)
            except Exception as e:
                print(f"Error loading cases: {e}")

    def _save_all(self):
        try:
            profile_file = os.path.join(self.persistence_dir, "profiles.json")
            with open(profile_file, "w", encoding="utf-8") as f:
                json.dump({uid: p.model_dump() for uid, p in self.profiles.items()}, f, indent=2, ensure_ascii=False)

            case_file = os.path.join(self.persistence_dir, "cases.json")
            with open(case_file, "w", encoding="utf-8") as f:
                json.dump({cid: c.model_dump() for cid, c in self.cases.items()}, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving case store: {e}")

    def get_or_create_profile(self, user_id: str, preferred_lang: Optional[str] = None) -> UserProfile:
        if user_id not in self.profiles:
            profile = UserProfile(
                user_id=user_id,
                preferred_language=preferred_lang or "en"
            )
            self.profiles[user_id] = profile
            self._save_all()
            return profile
            
        profile = self.profiles[user_id]
        if preferred_lang and profile.preferred_language != preferred_lang:
            profile.preferred_language = preferred_lang
            profile.updated_at = time.time()
            self._save_all()
        return profile

    def get_or_create_case(
        self,
        user_id: str,
        case_id: Optional[str] = None,
        matter_type: str = "general_inquiry",
        jurisdiction: str = "Thailand"
    ) -> LegalCaseState:
        profile = self.get_or_create_profile(user_id)

        if case_id and case_id in self.cases:
            case = self.cases[case_id]
            if case.user_id == user_id:
                return case

        # Look for existing active case of same matter_type for this user
        if not case_id:
            for existing_id in profile.active_case_ids:
                if existing_id in self.cases:
                    c = self.cases[existing_id]
                    if c.matter_type == matter_type or matter_type == "general_inquiry":
                        return c

        # Create brand new case (preserving case_id if passed)
        kwargs: Dict[str, Any] = {
            "user_id": user_id,
            "matter_type": matter_type,
            "jurisdiction": jurisdiction,
            "turn_index": 0
        }
        if case_id:
            kwargs["case_id"] = case_id

        new_case = LegalCaseState(**kwargs)
        self.cases[new_case.case_id] = new_case
        profile.active_case_ids.append(new_case.case_id)
        self._save_all()
        return new_case

    def apply_turn_update(
        self,
        case_id: str,
        turn_index: int,
        extracted_facts: List[Dict[str, Any]],
        detected_issues: List[str],
        identified_unknowns: List[str],
        response_mode: ResponseMode,
        matter_type: Optional[str] = None
    ) -> LegalCaseState:
        """Atomically updates case state with new facts, corrections, and issues."""
        if case_id not in self.cases:
            raise KeyError(f"Case {case_id} not found")

        case = self.cases[case_id]
        case.turn_index = turn_index
        case.current_mode = response_mode
        case.legal_issues = list(set(case.legal_issues + detected_issues))
        case.unknowns = identified_unknowns
        if matter_type:
            case.matter_type = matter_type

        for f_item in extracted_facts:
            entity = f_item.get("entity")
            val = f_item.get("value")
            ftype_raw = f_item.get("fact_type", "USER_FACT")
            conf = float(f_item.get("confidence", 1.0))
            
            ftype = FactType(ftype_raw) if ftype_raw in FactType.__members__ else FactType.USER_FACT
            if entity and val is not None:
                case.add_or_update_fact(
                    entity=entity,
                    value=val,
                    fact_type=ftype,
                    confidence=conf,
                    turn_id=turn_index
                )

        case.updated_at = time.time()
        self._save_all()
        return case
