#!/usr/bin/env python3
"""
backend/user_profile.py
User Legal Profile, Session Memory & Multi-Session Dialog Architecture for Consultant+.
v5.0: Unified client profile, dynamic real-time sync, and canonical Telegram ID normalization.
"""

from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field
import time
import uuid
import re
import logging

logger = logging.getLogger("user_profile")

def normalize_user_id(user_id: Optional[str]) -> str:
    """
    Normalizes user IDs across Telegram bot, Mini App, and API.
    Converts raw Telegram numeric IDs (e.g. '28122117' or 28122117) to 'tg_28122117',
    ensuring 100% online state and language synchronization.
    """
    if not user_id:
        return "anonymous"
    u = str(user_id).strip()
    if u.isdigit():
        return f"tg_{u}"
    return u

class DialogMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    role: str  # "user" or "assistant"
    content: str
    domain: Optional[str] = None
    timestamp: float = Field(default_factory=time.time)
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    precedents: List[Dict[str, Any]] = Field(default_factory=list)
    proactive_clarifications: List[str] = Field(default_factory=list)
    related_case: Optional[Dict[str, Any]] = None

class DialogSession(BaseModel):
    session_id: str
    user_id: str
    title: str = "Новая консультация"
    domain: str = "GENERAL"
    messages: List[DialogMessage] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

class UserLegalProfile(BaseModel):
    user_id: str
    preferred_language: str = "en"
    user_role: str = "client"
    jurisdiction_focus: str = "national"
    active_legal_matter: Optional[str] = None
    query_history: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

class UserProfileManager:
    """Manages persistent in-memory user profiles & multi-session dialogs with instant sync."""

    def __init__(self):
        self._profiles: Dict[str, UserLegalProfile] = {}
        self._sessions: Dict[str, DialogSession] = {}
        self._user_sessions: Dict[str, List[str]] = {}

    def get_or_create(self, user_id: str, default_lang: str = "ru") -> UserLegalProfile:
        u = normalize_user_id(user_id)
        if u not in self._profiles:
            self._profiles[u] = UserLegalProfile(
                user_id=u,
                preferred_language=default_lang
            )
        return self._profiles[u]

    def update_language(self, user_id: str, lang: str) -> UserLegalProfile:
        u = normalize_user_id(user_id)
        valid_langs = ["en", "th", "ru", "zh"]
        if lang not in valid_langs:
            lang = "ru"
        profile = self.get_or_create(u)
        profile.preferred_language = lang
        profile.updated_at = time.time()
        logger.info(f"Updated language for user {u} to {lang}")
        return profile

    def update_matter(self, user_id: str, matter: str) -> UserLegalProfile:
        u = normalize_user_id(user_id)
        profile = self.get_or_create(u)
        profile.active_legal_matter = matter
        profile.updated_at = time.time()
        return profile

    def record_query(self, user_id: str, query: str, domain: str = "GENERAL") -> UserLegalProfile:
        u = normalize_user_id(user_id)
        profile = self.get_or_create(u)
        profile.query_history.append({"query": query, "domain": domain, "timestamp": time.time()})
        profile.updated_at = time.time()
        return profile

    # ─────────────────────────────────────────────────────────────
    # SESSION & MULTI-TURN DIALOG MANAGEMENT
    # ─────────────────────────────────────────────────────────────
    def get_or_create_session(self, session_id: Optional[str], user_id: str, default_lang: str = "ru") -> DialogSession:
        u = normalize_user_id(user_id)
        if not session_id or session_id not in self._sessions:
            new_id = session_id or f"sess_{str(uuid.uuid4())[:8]}"
            title_by_lang = {
                "en": "New Legal Consultation",
                "th": "การปรึกษากฎหมายใหม่",
                "ru": "Новая консультация",
                "zh": "新法律咨询案例"
            }
            session = DialogSession(
                session_id=new_id,
                user_id=u,
                title=title_by_lang.get(default_lang, "Новая консультация")
            )
            self._sessions[new_id] = session
            if u not in self._user_sessions:
                self._user_sessions[u] = []
            if new_id not in self._user_sessions[u]:
                self._user_sessions[u].insert(0, new_id)
            return session
        return self._sessions[session_id]

    def create_new_session(self, user_id: str, title: Optional[str] = None, domain: str = "GENERAL", lang: str = "ru") -> DialogSession:
        u = normalize_user_id(user_id)
        new_id = f"sess_{str(uuid.uuid4())[:8]}"
        default_titles = {
            "en": "New Legal Consultation",
            "th": "การปรึกษากฎหมายใหม่",
            "ru": "Новая консультация",
            "zh": "新法律咨询案例"
        }
        actual_title = title or default_titles.get(lang, "Новая консультация")
        session = DialogSession(
            session_id=new_id,
            user_id=u,
            title=actual_title,
            domain=domain
        )
        self._sessions[new_id] = session
        if u not in self._user_sessions:
            self._user_sessions[u] = []
        self._user_sessions[u].insert(0, new_id)
        return session

    def list_user_sessions(self, user_id: str) -> List[Dict[str, Any]]:
        u = normalize_user_id(user_id)
        sess_ids = self._user_sessions.get(u, [])
        result = []
        for sid in sess_ids:
            s = self._sessions.get(sid)
            if s:
                last_msg = s.messages[-1].content[:70] + "..." if s.messages else ""
                result.append({
                    "session_id": s.session_id,
                    "title": s.title,
                    "domain": s.domain,
                    "message_count": len(s.messages),
                    "last_preview": last_msg,
                    "created_at": s.created_at,
                    "updated_at": s.updated_at
                })
        return result

    def get_session(self, session_id: str) -> Optional[DialogSession]:
        return self._sessions.get(session_id)

    def get_session_data(self, session_id: str) -> Optional[Dict[str, Any]]:
        s = self._sessions.get(session_id)
        if not s:
            return None
        return {
            "session_id": s.session_id,
            "user_id": s.user_id,
            "title": s.title,
            "domain": s.domain,
            "messages": [m.dict() for m in s.messages],
            "created_at": s.created_at,
            "updated_at": s.updated_at
        }

    def delete_session(self, session_id: str, user_id: str) -> bool:
        u = normalize_user_id(user_id)
        if session_id in self._sessions:
            del self._sessions[session_id]
        if u in self._user_sessions and session_id in self._user_sessions[u]:
            self._user_sessions[u].remove(session_id)
            return True
        return False

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        domain: Optional[str] = None,
        citations: Optional[List[Dict[str, Any]]] = None,
        precedents: Optional[List[Dict[str, Any]]] = None,
        proactive_clarifications: Optional[List[str]] = None,
        related_case: Optional[Dict[str, Any]] = None
    ) -> DialogMessage:
        session = self._sessions.get(session_id)
        if not session:
            session = self.get_or_create_session(session_id, user_id="anonymous")

        msg = DialogMessage(
            role=role,
            content=content,
            domain=domain,
            citations=citations or [],
            precedents=precedents or [],
            proactive_clarifications=proactive_clarifications or [],
            related_case=related_case
        )
        session.messages.append(msg)
        session.updated_at = time.time()
        
        # Auto-update session title on first user query
        if role == "user" and (session.title in ["New Legal Consultation", "การปรึกษากฎหมายใหม่", "Новая консультация", "新法律咨询案例"] or len(session.messages) <= 2):
            clean_title = " ".join(content.strip().split())
            if len(clean_title) > 36:
                clean_title = clean_title[:33] + "..."
            session.title = clean_title

        if domain and domain not in ["GENERAL", "CIVIL_COMMERCIAL"]:
            session.domain = domain

        return msg

    def get_session_history(self, session_id: str, limit: int = 6) -> List[Dict[str, Any]]:
        session = self._sessions.get(session_id)
        if not session or not session.messages:
            return []
        msgs = session.messages[-limit:]
        return [{"role": m.role, "content": m.content, "domain": m.domain} for m in msgs]

    # ─────────────────────────────────────────────────────────────
    # CROSS-DIALOG INSIGHT & RELATED CASE DETECTION
    # ─────────────────────────────────────────────────────────────
    def find_related_past_case(
        self,
        user_id: str,
        current_session_id: str,
        current_domain: str,
        current_query: str,
        lang: str = "ru"
    ) -> Optional[Dict[str, Any]]:
        u = normalize_user_id(user_id)
        sess_ids = self._user_sessions.get(u, [])
        if not sess_ids:
            return None

        related_domain_matrix = {
            "CONDO_PROPERTY": ["TAX_REVENUE", "LAND_PROPERTY", "IMMIGRATION_VISA"],
            "LAND_PROPERTY": ["CONDO_PROPERTY", "CORPORATE_FOREIGN_BUSINESS"],
            "TAX_REVENUE": ["CONDO_PROPERTY", "CORPORATE_FOREIGN_BUSINESS", "IMMIGRATION_VISA"],
            "CORPORATE_FOREIGN_BUSINESS": ["LAND_PROPERTY", "IMMIGRATION_VISA", "LABOR_EMPLOYMENT", "TAX_REVENUE"],
            "IMMIGRATION_VISA": ["CORPORATE_FOREIGN_BUSINESS", "LABOR_EMPLOYMENT", "TAX_REVENUE"],
            "LABOR_EMPLOYMENT": ["CORPORATE_FOREIGN_BUSINESS", "IMMIGRATION_VISA"],
            "FAMILY_INHERITANCE": ["CONDO_PROPERTY", "LAND_PROPERTY"],
            "DISPUTE_RESOLUTION_ARBITRATION": ["CORPORATE_FOREIGN_BUSINESS", "LAND_PROPERTY"]
        }

        for sid in sess_ids:
            if sid == current_session_id:
                continue
            s = self._sessions.get(sid)
            if not s or not s.messages or len(s.messages) < 2:
                continue

            # Case 1: Same domain past discussion
            if s.domain == current_domain and current_domain != "GENERAL":
                hints = {
                    "ru": f"Ранее мы уже разбирали тему «{s.title}». Контекст и наработки учтены в консультации.",
                    "en": f"You previously explored '{s.title}'. Historical context is integrated.",
                    "th": f"ท่านเคยปรึกษาหัวข้อ «{s.title}» ก่อนหน้านี้ ระบบได้เชื่อมโยงข้อมูลให้เรียบร้อยแล้วครับ",
                    "zh": f"已自动关联您先前咨询的「{s.title}」案情背景。"
                }
                return {
                    "session_id": s.session_id,
                    "title": s.title,
                    "domain": s.domain,
                    "hint": hints.get(lang, hints["ru"])
                }

            # Case 2: Cross-domain synergy
            allowed_synergies = related_domain_matrix.get(current_domain, [])
            if s.domain in allowed_synergies:
                hints = {
                    "ru": f"Связано с вашей прошлой консультацией «{s.title}».",
                    "en": f"Synergized with your prior consultation '{s.title}'.",
                    "th": f"เชื่อมโยงกับบทสนทนาก่อนหน้า «{s.title}»",
                    "zh": f"与您先前的「{s.title}」咨询相关联。"
                }
                return {
                    "session_id": s.session_id,
                    "title": s.title,
                    "domain": s.domain,
                    "hint": hints.get(lang, hints["ru"])
                }

        return None
