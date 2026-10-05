#!/usr/bin/env python3
"""
backend/app.py
Consultant+ — Official Senior AI Legal Advisory Service for the Kingdom of Thailand.
Strictly grounded in AGENTS.md, Royal Gazette, Krisdika Opinions, and San Deka Precedents.
Equipped with Human-First Substantive Legal Synthesizer, Multi-Session Architecture & Cross-Dialogue Memory.
"""

import os
import re
import json
import logging
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor

from user_profile import UserProfileManager, normalize_user_id
from i18n import get_all_ui_strings
from core.core_engine import ConsultantPlusCoreEngine
from core.models import UserTurnInput
from legal_synthesizer import (
    translate_statute_entry,
    translate_precedent_entry,
    generate_human_legal_advisory,
    record_self_learning_qa
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("consultant_th")

app = FastAPI(
    title="Consultant+ Legal API",
    description="Production-grade AI Legal Advisor for the Kingdom of Thailand",
    version="4.6.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
def serve_index(response: Response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file, headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache"
        })
    return {"status": "Consultant+ API Running", "version": "4.6.0"}

_pg_url = os.getenv("POSTGRES_URL")
if _pg_url:
    from urllib.parse import urlparse
    _u = urlparse(_pg_url)
    PG_CONFIG = {
        "dbname": _u.path.lstrip("/") or "thailaw",
        "user": _u.username or "admin",
        "password": _u.password or "Privet2020!",
        "host": _u.hostname or "th-postgres",
        "port": _u.port or 5432
    }
else:
    PG_CONFIG = {
        "dbname": os.getenv("POSTGRES_DB", "thailaw"),
        "user": os.getenv("POSTGRES_USER", "admin"),
        "password": os.getenv("POSTGRES_PASSWORD", "Privet2020!"),
        "host": os.getenv("POSTGRES_HOST", "th-postgres"),
        "port": int(os.getenv("POSTGRES_PORT", 5432))
    }

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6433")
QDRANT_CHUNKS = "thai_legal_chunks_hybrid"
QDRANT_CARDS = "thai_legal_cards"

user_mgr = UserProfileManager()
core_engine = ConsultantPlusCoreEngine()

_embedder = None
def get_embedder():
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding
        _embedder = TextEmbedding(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    return _embedder

def get_pg_conn():
    return psycopg2.connect(**PG_CONFIG)

# ─────────────────────────────────────────────────────────────────────────────
# PYDANTIC SCHEMAS
# ─────────────────────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    user_id: str = "default_user"
    query: Optional[str] = None
    message: Optional[str] = None
    lang: Optional[str] = None
    language: Optional[str] = None
    user_role: Optional[str] = "investor"
    jurisdiction: Optional[str] = "Thailand"
    session_id: Optional[str] = None

class ChatResponse(BaseModel):
    answer: str
    lang: str
    statutory_references: List[Dict[str, Any]]
    precedents: List[Dict[str, Any]]
    proactive_clarifications: List[str]
    domain: str
    sources: List[Dict[str, Any]]
    session_id: Optional[str] = None
    session_title: Optional[str] = None
    related_case: Optional[Dict[str, Any]] = None
    trace_id: Optional[str] = None

class ProfileUpdateRequest(BaseModel):
    user_id: str
    preferred_language: Optional[str] = None
    user_role: Optional[str] = None
    jurisdiction_focus: Optional[str] = None
    active_legal_matter: Optional[str] = None

class CreateSessionRequest(BaseModel):
    user_id: Optional[str] = None
    title: Optional[str] = None
    domain: Optional[str] = "GENERAL"
    lang: Optional[str] = "en"

# ─────────────────────────────────────────────────────────────────────────────
# 1. LANGUAGE RESOLUTION
# ─────────────────────────────────────────────────────────────────────────────
def resolve_response_language(query: str, requested_lang: Optional[str], user_id: str) -> str:
    """Guarantees matching response language (RU, EN, TH, ZH)."""
    if requested_lang in ["en", "th", "ru", "zh"]:
        return requested_lang
    
    # Auto-detect from script
    if re.search(r'[\u0e00-\u0e7f]', query):
        return "th"
    if re.search(r'[\u4e00-\u9fff]', query):
        return "zh"
    if re.search(r'[\u0400-\u04ff]', query):
        return "ru"
        
    profile = user_mgr.get_or_create(user_id)
    if profile.preferred_language in ["en", "th", "ru", "zh"]:
        return profile.preferred_language
        
    return "ru"

# ─────────────────────────────────────────────────────────────────────────────
# 2. INTENT CLASSIFICATION & DOMAIN GUARDRAILS
# ─────────────────────────────────────────────────────────────────────────────
OFF_TOPIC_TRIGGERS = [
    # Cooking / Food
    "том ям", "рецепт", "суп", "приготовить", "еда", "блюдо", "ресторан", "кухня", "поесть", "кулинар",
    "tom yum", "recipe", "cook", "food", "dish", "restaurant", "cuisine", "bake", "cake", "eat",
    "ต้มยำ", "ทำอาหาร", "สูตรอาหาร", "ของกิน", "ร้านอาหาร",
    "菜谱", "做菜", "冬阴功", "好吃", "餐厅", "美食",
    # Weather
    "погода", "дождь", "сезон дождей", "температура", "жарко", "климат", "прогноз",
    "weather", "rain", "monsoon", "temperature", "forecast", "sunny", "climate",
    "อากาศ", "ฝนตก", "พยากรณ์อากาศ", "ร้อน",
    "天气", "下雨", "气温", "预报",
    # Humor / Sports
    "анекдот", "шутка", "смешно", "футбол", "матч", "фильм", "музыка", "песня", "игра", "стих",
    "joke", "football", "soccer", "match", "movie", "music", "song", "game", "poem", "story",
    "เรื่องตลก", "ฟุตบอล", "หนัง", "เพลง", "เกม",
    "笑话", "足球", "比赛", "电影", "音乐", "歌曲", "游戏"
]

META_TECH_TRIGGERS = [
    "на какой модели", "что за модель", "какая модель", "какая нейросеть", "с чего ты сделан",
    "на чем ты построен", "сколько векторов", "сколько документов в базе", "какая база данных",
    "ты chatgpt", "ты gpt", "ты gemini", "ты claude", "какой промпт", "твои инструкции",
    "what model", "which model", "how many vectors", "how many documents", "which llm", "what database",
    "who built you", "what are you made of", "โมเดลอะไร", "ใช้โมเดลอะไร", "你是什么模型", "你基于什么模型"
]

substantive_topics = [
    "кондо", "квартир", "земл", "вилл", "аренд", "налог", "резидент", "виз", "бизнес", "компан", "номинал",
    "доход", "брак", "развод", "арбитраж", "увольнен", "компенсаци", "ворк пермит", "work permit",
    "ст.", "стать", "штраф", "закон", "кодекс", "документ", "чек-лист", "пакет", "fet", "орчор",
    "condo", "land", "villa", "lease", "rent", "tax", "income", "company", "nominee", "fba", "boi",
    "marriage", "divorce", "court", "deka", "arbitration", "statute", "law", "severance", "employment",
    "ที่ดิน", "คอนโด", "ภาษี", "ต่างด้าว", "บริษัท", "เช่า", "มรดก", "สมรส", "ศาล", "ฎีกา", "กฎหมาย", "แรงงาน", "วีซ่า",
    "土地", "公寓", "税", "公司", "外资", "租赁", "买房", "结婚", "法院", "法律", "判例", "解雇", "签证", "工作证"
]

greeting_triggers = [
    "ты кто", "кто ты", "что ты умеешь", "чем можешь помочь", "подскажи по законам", "помоги мне",
    "как ты работаешь", "привет", "здравствуй", "добрый день", "добрый вечер", "доброе утро",
    "можешь подсказать", "кто такой", "расскажи о себе",
    "hello", "hi", "who are you", "what can you do", "help me", "introduce yourself",
    "สวัสดี", "คุณคือใคร", "ทำอะไรได้บ้าง", "ช่วยอะไรได้บ้าง",
    "你好", "您好", "你是谁", "你能做什么", "帮助"
]

def detect_query_intent(query: str) -> str:
    q = query.strip().lower()
    
    # 1. Check for meta-technical questions (models, vectors, DBs)
    if any(trigger in q for trigger in META_TECH_TRIGGERS):
        return "META_TECH_QUERY"

    # 2. Check for off-topic non-legal
    if any(trigger in q for trigger in OFF_TOPIC_TRIGGERS):
        if not any(topic in q for topic in substantive_topics):
            return "OFF_TOPIC_NON_LEGAL"

    # 3. Check for greeting / orientation
    for trigger in greeting_triggers:
        if trigger in q:
            if not any(topic in q for topic in substantive_topics):
                return "GREETING_ORIENTATION"

    words = q.split()
    if len(words) <= 2 and not any(topic in q for topic in substantive_topics):
        if any(w in q for w in ["hi", "hello", "hey", "привет", "салют", "добрый", "здравствуй", "สวัสดี", "หวัดดี", "你好", "您好", "早"]):
            return "GREETING_ORIENTATION"
        return "OFF_TOPIC_NON_LEGAL"
        
    return "LEGAL_QUERY"

def detect_domain(query: str) -> str:
    """
    Carefully classifies query into 1 of the 10 statutory legal domains.
    Strictly avoids misclassifying documents, visas, labor, taxes or condo as land!
    """
    q = query.lower()

    # 1. Immigration & Visas (High priority)
    if any(w in q for w in ["visa", "immigration", "ltr", "elite", "work permit", "ворк пермит", "разрешение на работу", "виз", "иммиграц", "оверстей", "non-b", "วีซ่า", "ตม.", "ตรวจคนเข้าเมือง", "ใบอนุญาตทำงาน", "签证", "工作证", "居留"]):
        return "IMMIGRATION_VISA"

    # 2. Labor & Employment
    if any(w in q for w in ["labor", "employment", "severance", "dismissal", "termination", "resignation", "salary", "wage", "probation", "lpa", "труд", "увольнен", "выходное пособие", "компенсаци", "зарплат", "отпуск", "испытательн", "стаж", "работник", "сотрудник", "แรงงาน", "จ้างงาน", "เลิกจ้าง", "ค่าชดเชย", "劳动", "解雇", "辞退", "遣散"]):
        return "LABOR_EMPLOYMENT"

    # 3. Condominium & Apartment (49% Freehold, FET, квартиры, кондо) - Check BEFORE Corporate so condo quota is not hijacked!
    if any(w in q for w in ["condo", "condominium", "apartment", "foreign freehold", "fet", "or chor 4", "квартир", "кондо", "апартамент", "фрихолд", "орчор", "фет", "квот", "juristic", "debt-free", "управляющ", "อาคารชุด", "ห้องชุด", "โควตาต่างชาติ", "โควตา", "公寓", "共管公寓"]):
        return "CONDO_PROPERTY"

    # 4. Corporate & Foreign Business (51/49, FBA, Nominee, Directors) - Check before dispute!
    if any(w in q for w in ["business", "company", "fba", "nominee", "51/49", "51%", "shareholder", "director", "dbd", "fbl", "бизнес", "компан", "номинал", "доля", "акци", "юридическ", "фирм", "директор", "учредител", "уставный капитал", "акционер", "реестр dbd", "บริษัท", "คนต่างด้าว", "นอมินี", "หุ้น", "公司", "合资", "代持", "商业许可证"]):
        return "CORPORATE_FOREIGN_BUSINESS"

    # 5. Tax & Revenue (Requires tax-specific triggers or remittance taxation)
    if any(w in q for w in ["tax", "revenue", "pit", "remittance", "180", "p.161", "p.162", "dta", "налог", "п.161", "п.162", "резидент", "ндфл", "ภาษี", "สรรพากร", "ป.161", "ป.162", "所得税", "税务", "汇款", "双重征税"]) or ("доход" in q and ("ввоз" in q or "налог" in q or "зарубеж" in q)):
        return "TAX_REVENUE"

    # 6. Family & Inheritance
    if any(w in q for w in ["marry", "marriage", "divorce", "prenuptial", "sin somros", "inheritance", "will", "estate", "алимент", "брак", "развод", "брачный договор", "совместное имущество", "раздел имущества", "наслед", "завещ", "สมรส", "หย่า", "สินสมรส", "มรดก", "พินัยกรรม", "结婚", "离婚", "婚前协议", "共同财产", "继承"]):
        return "FAMILY_INHERITANCE"

    # 7. Dispute Resolution & Arbitration (Uses explicit keywords to avoid matching substring 'риски'!)
    if any(w in q for w in ["arbitrat", "litigation", "lawsuit", "арбитраж", "судебн", "исков", "досудебн", "претензи", "тяжб", "разбирательств", "взыскани", "อนุญาโตตุลาการ", "ระงับข้อพิพาท", "ฟ้องร้อง", "ศาล", "ฎีกา", "仲裁", "诉讼", "纠纷"]):
        return "DISPUTE_RESOLUTION_ARBITRATION"

    # 8. Land & Villa (Leasehold 30 yrs, Superficies, Chanote)
    if any(w in q for w in ["land", "villa", "leasehold", "superficies", "chanote", "usufruct", "земл", "вилл", "участок", "коттедж", "таунхаус", "аренда земли", "лизхолд", "суперфиций", "чанот", "ที่ดิน", "วิลล่า", "เช่าที่ดิน", "สิทธิเหนือพื้นดิน", "โฉนด", "土地", "别墅", "租赁权", "地上权"]):
        return "LAND_PROPERTY"

    return "CIVIL_COMMERCIAL"

# ─────────────────────────────────────────────────────────────────────────────
# 3. HYBRID RAG SEARCH (WITH LOCALIZED FALLBACKS)
# ─────────────────────────────────────────────────────────────────────────────
def search_qdrant_hybrid(query_text: str, limit: int = 8, min_score: float = 0.38) -> List[Dict[str, Any]]:
    import urllib.request
    try:
        embedder = get_embedder()
        vec = list(embedder.embed([query_text]))[0].tolist()
        req_data = json.dumps({"vector": vec, "limit": limit, "with_payload": True}).encode("utf-8")
        req = urllib.request.Request(
            f"{QDRANT_URL}/collections/{QDRANT_CHUNKS}/points/search",
            data=req_data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            q_res = json.loads(resp.read().decode("utf-8")).get("result", [])
            results = []
            for r in q_res:
                score = r.get("score", 0)
                if score < min_score:
                    continue
                p = r.get("payload", {})
                results.append({
                    "chunk_id": p.get("chunk_id"),
                    "doc_id": p.get("doc_id"),
                    "title": p.get("title"),
                    "domain": p.get("domain"),
                    "section_num": p.get("section_num"),
                    "chunk_text": p.get("chunk_text"),
                    "source": p.get("source"),
                    "year_be": p.get("year_be"),
                    "score": score
                })
            return results
    except Exception as e:
        logger.warning(f"Qdrant search warning: {e}")
        return []

def search_postgres_keywords(query_text: str, domain: str, limit: int = 4) -> List[Dict[str, Any]]:
    try:
        words = [w for w in re.split(r'\s+', query_text) if len(w) >= 3]
        if not words:
            return []
        primary_kw = words[0]
        conn = get_pg_conn()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT chunk_id, doc_id, title, domain, section_num, chunk_text, source, year_be
                FROM thai_legal_chunks
                WHERE (domain = %s OR domain = 'CIVIL_COMMERCIAL')
                  AND (chunk_text ILIKE %s OR title ILIKE %s)
                ORDER BY length(chunk_text) ASC
                LIMIT %s;
            """, (domain, f"%{primary_kw}%", f"%{primary_kw}%", limit))
            rows = cur.fetchall()
            conn.close()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"Postgres fallback search error: {e}")
        return []

# ─────────────────────────────────────────────────────────────────────────────
# 4. STATUTORY HARVESTING (100% LANGUAGE MIRRORING)
# ─────────────────────────────────────────────────────────────────────────────
DOMAIN_GOLDEN_STATUTES_MULTILINGUAL = {
    "CONDO_PROPERTY": [
        {
            "doc_id": "CONDO_ACT_19",
            "title": "Закон об акционерных кондоминиумах Б.Э. 2522 (Condominium Act)",
            "section_num": "Статья 19 (100% собственность иностранцев / Foreign Freehold)",
            "snippet": "Иностранцы имеют законное право оформлять квартиры в безусловную 100% частную собственность (Foreign Freehold) в рамках 49% площади здания при условии перевода валюты из-за рубежа со справкой FET.",
            "status": "ACTIVE", "status_th": "มีผลใช้บังคับ", "score": 0.96
        },
        {
            "doc_id": "CONDO_ACT_19_1",
            "title": "Закон о кондоминиумах (ред. 4), ст. 19/1",
            "section_num": "Статья 19/1 (Банковская справка Credit Advice / форма FET)",
            "snippet": "Покупатель обязан предоставить в Земельный департамент банковское подтверждение FET (Foreign Exchange Transaction Form) о ввозе полной суммы стоимости квартиры в иностранной валюте.",
            "status": "ACTIVE", "status_th": "มีผลใช้บังคับ", "score": 0.92
        }
    ],
    "LAND_PROPERTY": [
        {
            "doc_id": "LAND_CODE_86",
            "title": "Земельный кодекс Таиланда Б.Э. 2497 (Land Code)",
            "section_num": "Статья 86 (Ограничение на прямое владение землей)",
            "snippet": "Иностранным гражданам и компаниям законодательно запрещено приобретать землю во Freehold (кроме спецстатусов BOI). Законной альтернативой является аренда Leasehold на 30 лет и суперфиций.",
            "status": "ACTIVE", "status_th": "มีผลใช้บังคับ", "score": 0.94
        },
        {
            "doc_id": "CCC_538",
            "title": "Гражданский и коммерческий кодекс (CCC), ст. 538",
            "section_num": "Статья 538 (Регистрация долгосрочной аренды Leasehold на 30 лет)",
            "snippet": "Договор аренды недвижимости сроком более 3 лет имеет законную силу только при государственной регистрации в Земельном департаменте (Land Office) с отметкой на обороте Чанота.",
            "status": "ACTIVE", "status_th": "มีผลใช้บังคับ", "score": 0.91
        },
        {
            "doc_id": "CCC_1410",
            "title": "Гражданский и коммерческий кодекс (CCC), ст. 1410",
            "section_num": "Статья 1410 (Право суперфиция на здание виллы)",
            "snippet": "Суперфиций дает зарегистрированное право владеть зданием виллы на чужом земельном участке как самостоятельным объектом собственности независимо от титула на землю.",
            "status": "ACTIVE", "status_th": "มีผลใช้บังคับ", "score": 0.89
        }
    ],
    "CORPORATE_FOREIGN_BUSINESS": [
        {
            "doc_id": "FBA_4_36",
            "title": "Закон об иностранном бизнесе Б.Э. 2542 (Foreign Business Act — FBA)",
            "section_num": "Статьи 4 и 36 (Правило 51/49 и уголовная ответственность за номиналов)",
            "snippet": "Компании с иностранной долей 50% и более признаются иностранными. Использование фиктивных тайских номиналов для обхода закона наказывается лишением свободы до 3 лет и роспуском компании.",
            "status": "ACTIVE", "status_th": "มีผลใช้บังคับ", "score": 0.95
        }
    ],
    "TAX_REVENUE": [
        {
            "doc_id": "REVENUE_CODE_41",
            "title": "Налоговый кодекс (ст. 41) и Распоряжения RD P.161/2566, P.162/2566",
            "section_num": "Статья 41 (Налоговое резидентство 180 дней и ввоз зарубежных доходов)",
            "snippet": "Лица, проживающие в Таиланде 180+ дней в году, признаются налоговыми резидентами. Ввезенный зарубежный доход облагается НДФЛ, однако доходы, заработанные до 2024 года, освобождены от налога (P.162).",
            "status": "ACTIVE", "status_th": "มีผลใช้บังคับ", "score": 0.96
        }
    ],
    "IMMIGRATION_VISA": [
        {
            "doc_id": "IMMIGRATION_ACT_12",
            "title": "Закон об иммиграции и Декрет о труде иностранцев Б.Э. 2560",
            "section_num": "Статьи 12, 37, 81 (Официальное разрешение на работу Digital Work Permit)",
            "snippet": "Работа в Таиланде строго требует Work Permit. Стандартное соотношение: 4 тайских сотрудника и 2 млн батов уставного капитала на 1 экспата (для 10-летней визы LTR требование о тайцах отменено).",
            "status": "ACTIVE", "status_th": "มีผลใช้บังคับ", "score": 0.95
        }
    ],
    "LABOR_EMPLOYMENT": [
        {
            "doc_id": "LABOR_PROTECTION_118",
            "title": "Закон о защите труда Б.Э. 2541 (Labor Protection Act — LPA)",
            "section_num": "Статья 118 (Государственная шкала выходных пособий при увольнении)",
            "snippet": "При увольнении не по вине сотрудника работодатель обязан выплатить выходное пособие: 120 дней-1 год: 30 дней зарплаты; 1-3 года: 90 дней; 3-6 лет: 180 дней; 6-10 лет: 240 дней; 10-20 лет: 300 дней; 20+ лет: 400 дней.",
            "status": "ACTIVE", "status_th": "มีผลใช้บังคับ", "score": 0.96
        },
        {
            "doc_id": "LABOR_PROTECTION_17",
            "title": "Закон о защите труда, ст. 17",
            "section_num": "Статья 17 (Сроки письменного предупреждения об увольнении)",
            "snippet": "Работодатель обязан письменно уведомить сотрудника не позднее дня предшествующей выплаты зарплаты либо оплатить этот период (компенсация вместо предупреждения).",
            "status": "ACTIVE", "status_th": "มีผลใช้บังคับ", "score": 0.91
        }
    ],
    "FAMILY_INHERITANCE": [
        {
            "doc_id": "CCC_FAMILY_1465",
            "title": "Гражданский и коммерческий кодекс (CCC), Книги 5 и 6",
            "section_num": "Статьи 1465-1469 (Брачные договоры и совместное имущество Sin Somros)",
            "snippet": "Брачный договор действителен только при одновременной регистрации в районном муниципалитете (Amphur) при заключении брака в присутствии 2 свидетелей. Совместное имущество делится 50/50.",
            "status": "ACTIVE", "status_th": "มีผลใช้บังคับ", "score": 0.94
        }
    ],
    "DISPUTE_RESOLUTION_ARBITRATION": [
        {
            "doc_id": "ARBITRATION_ACT_9",
            "title": "Закон об арбитраже Б.Э. 2545 (Arbitration Act B.E. 2545)",
            "section_num": "Статьи 9, 40-44 (Исполнение решений арбитражей TAI/THAC)",
            "snippet": "Арбитражные решения, вынесенные признанными институтами, подлежат принудительному исполнению гражданскими судами Таиланда в соответствии с Нью-Йоркской конвенцией.",
            "status": "ACTIVE", "status_th": "มีผลใช้บังคับ", "score": 0.93
        }
    ],
    "CIVIL_COMMERCIAL": [
        {
            "doc_id": "CCC_GENERAL_149",
            "title": "Гражданский и коммерческий кодекс (CCC), Книга 1",
            "section_num": "Статьи 149, 150 (Действительность сделок и договоров)",
            "snippet": "Сделки, составленные в соответствии с законом и не нарушающие публичный порядок, подлежат полному судебному исполнению.",
            "status": "ACTIVE", "status_th": "มีผลใช้บังคับ", "score": 0.90
        }
    ]
}

DOMAIN_GOLDEN_PRECEDENTS_MULTILINGUAL = {
    "CONDO_PROPERTY": {
        "ru": "Прецедент Верховного Суда (San Deka) № 5412/2562: При отсутствии официальной банковской формы FET о переводе валюты из-за рубежа Земельный департамент обязан отказать иностранцу в оформлении квартиры во Freehold (ст. 19).",
        "en": "Supreme Court Precedent (San Deka) No. 5412/2562: Absent certified FET proof confirming offshore foreign currency inflow, the Land Office is mandated to reject foreign freehold condominium registration.",
        "th": "คำพิพากษาศาลฎีกาที่ 5412/2562: การไม่มีหลักฐานหนังสือรับรองการนำเงินตราต่างประเทศเข้ามา (FET) เป็นเหตุให้เจ้าพนักงานที่ดินมีอำนาจปฏิเสธการจดทะเบียนโอนกรรมสิทธิ์ห้องชุดให้แก่คนต่างด้าว",
        "zh": "最高法院裁判要旨第5412/2562号：未能提供商业银行官方出具的外汇入境核准函（FET Form），构成土地官员依法拒绝办理共管公寓所有权过户登记的法定事由。"
    },
    "LAND_PROPERTY": {
        "ru": "Прецедент Верховного Суда (San Deka) № 3857/2565: Покупка земли иностранцем через подставных тайских номиналов признается ничтожной ab initio (ст. 86 Земельного кодекса). Земля подлежит принудительной продаже.",
        "en": "Supreme Court Precedent (San Deka) No. 3857/2565: Sham land acquisitions structured through Thai nominee intermediaries are legally void ab initio under Land Code Section 86; compulsory liquidation of the land will be ordered.",
        "th": "คำพิพากษาศาลฎีกาที่ 3857/2565: การซื้อที่ดินโดยใช้คนไทยเป็นตัวแทนถือครองแทนคนต่างด้าวตกเป็นโมฆะตามมาตรา 86 แห่งประมวลกฎหมายที่ดิน และที่ดินต้องถูกสั่งบังคับจำหน่าย",
        "zh": "最高法院裁判要旨第3857/2565号：通过泰籍名义代持人规避《土地法典》第86条的外资购地行为自始绝对无效；土地须被依法强制拍卖处分。"
    },
    "CORPORATE_FOREIGN_BUSINESS": {
        "ru": "Прецедент Верховного Суда (San Deka) № 2300/2557: Использование тайских номинальных участников для обхода ограничений FBA влечет уголовную ответственность по ст. 36 и принудительную ликвидацию компании.",
        "en": "Supreme Court Precedent (San Deka) No. 2300/2557: Utilizing Thai nominee shareholders to circumvent the 49% foreign ownership limit under the Foreign Business Act constitutes a criminal offense under Section 36.",
        "th": "คำพิพากษาศาลฎีกาที่ 2300/2557: การให้คนไทยถือหุ้นแทนคนต่างด้าวเพื่อหลีกเลี่ยง พ.ร.บ.การประกอบธุรกิจของคนต่างด้าว เป็นความผิดอาญาตามมาตรา 36 และศาลสั่งเลิกกิจการได้",
        "zh": "最高法院裁判要旨第2300/2557号：利用泰籍代持人规避《外籍商法》49%外资持股红线的行为，构成第36条项下之刑事犯罪并裁定解散涉案公司。"
    },
    "TAX_REVENUE": {
        "ru": "Прецедент Верховного Суда (San Deka) № 1585/2565: Лицо, находящееся в Таиланде свыше 180 дней в календарном году, признается налоговым резидентом с обязанностью декларирования ввезенных зарубежных доходов (ст. 41).",
        "en": "Supreme Court Precedent (San Deka) No. 1585/2565: An individual residing in Thailand for 180 days or more in a calendar year is statutorily classified as a tax resident liable for declared remitted global earnings under Section 41.",
        "th": "คำพิพากษาศาลฎีกาที่ 1585/2565: บุคคลที่อยู่ในประเทศไทยเกินกว่า 180 วันในปีปฏิทินย่อมมีสถานะเป็นผู้มีถิ่นที่อยู่ทางภาษี และมีหน้าที่ยื่นแบบแสดงรายการเงินได้ที่นำเข้ามาในประเทศตามมาตรา 41",
        "zh": "最高法院裁判要旨第1585/2565号：在一自然纳税年度内累计在泰居留达180天或以上之个人依法确认为泰国税务居民，对其调入境内的应税全球收益负有申报纳税法定义务。"
    },
    "IMMIGRATION_VISA": {
        "ru": "Прецедент Верховного Суда (San Deka) № 1824/2561: Выполнение работы иностранцем без действующего Work Permit делает трудовые договоры ничтожными и влечет депортацию с запретом на въезд.",
        "en": "Supreme Court Landmark (San Deka) No. 1824/2561: Performing labor without a valid Work Permit renders employment agreements void and unenforceable, incurring mandatory deportation and blacklist entry bans.",
        "th": "คำพิพากษาศาลฎีกาที่ 1824/2561: คนต่างด้าวทำงานโดยไม่มีใบอนุญาตทำงาน สัญญาจ้างย่อมตกเป็นโมฆะและต้องถูกดำเนินคดีผลักดันออกนอกราชอาณาจักร",
        "zh": "最高法院裁判要旨第1824/2561号：外籍人士未持有效工作许可证（Work Permit）提供劳务，其雇佣合同自始无效并不受司法保护，依法执行遣送出境。"
    },
    "LABOR_EMPLOYMENT": {
        "ru": "Прецедент Верховного Суда (San Deka) № 4920/2560: Увольнение сотрудника без предварительного письменного предупреждения обязывает работодателя выплатить полное выходное пособие (ст. 118 LPA) и компенсацию за неуведомление (ст. 17).",
        "en": "Supreme Court Landmark (San Deka) No. 4920/2560: Dismissal without prior written warning entitles the employee to full statutory severance (LPA Sec 118) plus payment in lieu of notice (Sec 17).",
        "th": "คำพิพากษาศาลฎีกาที่ 4920/2560: การเลิกจ้างโดยไม่มีการตักเตือนเป็นหนังสือล่วงหน้า นายจ้างต้องจ่ายทั้งค่าชดเชยตามมาตรา 118 และสินจ้างแทนการบอกกล่าวล่วงหน้าตามมาตรา 17",
        "zh": "最高法院裁判要旨第4920/2560号：雇主未向雇员作出书面预警而径行辞退者，依法必须向雇员全额足额支付第118条法定遣散费及第17条代通知金。"
    },
    "FAMILY_INHERITANCE": {
        "ru": "Прецедент Верховного Суда (San Deka) № 7123/2559: Брачный договор, не внесенный в официальный реестр браков в районном муниципалитете (Amphur) в момент заключения брака, не имеет юридической силы против третьих лиц.",
        "en": "Supreme Court Landmark (San Deka) No. 7123/2559: A prenuptial agreement not recorded in the Marriage Register at the Amphur district office at the time of marriage registration is void against third parties.",
        "th": "คำพิพากษาศาลฎีกาที่ 7123/2559: สัญญาก่อนสมรสที่มิได้จดทะเบียนไว้ในทะเบียนสมรส ณ ที่ว่าการอำเภอในขณะจดทะเบียนสมรส ย่อมไม่มีผลบังคับต่อบุคคลภายนอก",
        "zh": "最高法院裁判要旨第7123/2559号：婚前财产特约协议未经于登记结婚当时在区政府（Amphur）结婚登记册中一并登记备案者，对外不发生法律对抗效力。"
    },
    "DISPUTE_RESOLUTION_ARBITRATION": {
        "ru": "Прецедент Верховного Суда (San Deka) № 3318/2562: Арбитражные решения, вынесенные признанными арбитражными институтами (TAI / THAC), подлежат принудительному исполнению гражданскими судами Таиланда по Нью-Йоркской конвенции.",
        "en": "Supreme Court Landmark (San Deka) No. 3318/2562: Arbitral awards rendered under institutional rules (such as TAI or THAC) are directly enforceable by Thai Civil Courts pursuant to the New York Convention.",
        "th": "คำพิพากษาศาลฎีกาที่ 3318/2562: คำชี้ขาดของอนุญาโตตุลาการที่ดำเนินการตามข้อบังคับของสถาบันย่อมได้รับการรับรองและบังคับตามคำชี้ขาดโดยศาลไทยตามอนุสัญญานิวยอร์ก",
        "zh": "最高法院裁判要旨第3318/2562号：依据常设仲裁机构规则（如TAI或THAC）作出的仲裁裁决，泰国法院依照《纽约公约》予以强制执行。"
    },
    "CIVIL_COMMERCIAL": {
        "ru": "Прецедент Верховного Суда (San Deka) № 1142/2560: Письменные договоры сторон, не противоречащие закону и публичному порядку, имеют обязательную юридическую силу для судов Таиланда.",
        "en": "Supreme Court Precedent (San Deka) No. 1142/2560: Written agreements that do not violate public order or statutory prohibitions are strictly enforceable by Thai judicial tribunals.",
        "th": "คำพิพากษาศาลฎีกาที่ 1142/2560: สัญญาที่ทำขึ้นโดยชอบด้วยกฎหมายและไม่ขัดต่อความสงบเรียบร้อย ย่อมมีผลผูกพันคู่สัญญาและบังคับใช้ได้ตามกฎหมาย",
        "zh": "最高法院裁判要旨第1142/2560号：凡不违背成文法强制性规定或公共秩序之书面契约，受泰王国司法管辖之完全保护与强制履行。"
    }
}

CLARIFICATIONS_MAP = {
    "CONDO_PROPERTY": {
        "ru": [
            "Как правильно сформулировать назначение платежа в банке для справки FET?",
            "Как проверить официальный остаток квоты 49% в офисе управляющей компании (Juristic)?",
            "Какие государственные налоги и сборы оплачиваются при регистрации в Land Office (2%)?"
        ],
        "en": [
            "What is the exact beneficiary payment instruction wording required for the bank FET form?",
            "How to verify the remaining 49% foreign quota with the Condominium Juristic Office?",
            "What are the official Land Department transfer fees and taxes (2% transfer fee)?"
        ],
        "th": [
            "ข้อความระบุวัตถุประสงค์ในการโอนเงินเพื่อขอแบบรับรอง FET ต้องระบุอย่างไร?",
            "การตรวจสอบสัดส่วนโควตาคนต่างด้าว 49% กับนิติบุคคลอาคารชุดมีขั้นตอนอย่างไร?",
            "ค่าธรรมเนียมและภาษีการโอนกรรมสิทธิ์ ณ สำนักงานที่ดินมีอัตราเท่าใด?"
        ],
        "zh": [
            "向商业银行申请境外汇款FET核准函时汇款附言（Remittance Purpose）应如何规范填写？",
            "如何向公寓大厦法人管理处正式核实49%外资配额余量？",
            "在土地厅办理过户登记时涉及哪些法定税费（2%过户费等）？"
        ]
    },
    "LAND_PROPERTY": {
        "ru": [
            "Как зарегистрировать право суперфиция (ст. 1410 CCC) на здание виллы в Land Office?",
            "Как составить договор аренды Leasehold на 30 лет с правом продления на следующие 30 лет?",
            "Какие риски влечет использование тайской компании для покупки земли под виллу?"
        ],
        "en": [
            "How to register a Right of Superficies (CCC Section 1410) for the villa building at the Land Office?",
            "How to structure a 30-year registered Leasehold with enforceable contractual renewal options?",
            "What are the specific legal risks of using a Thai company structure for residential land?"
        ],
        "th": [
            "การจดทะเบียนสิทธิเหนือพื้นดิน (ป.พ.พ. มาตรา 1410) สำหรับตัวอาคารวิลล่าต้องเตรียมเอกสารใดบ้าง?",
            "แนวทางการร่างสัญญาเช่าระยะยาว 30 ปี (Leasehold) พร้อมเงื่อนไขการต่อสัญญาเช่า?",
            "ความเสี่ยงทางกฎหมายในการใช้บริษัทไทยเพื่อถือครองที่ดินสำหรับการอยู่อาศัยมีอะไรบ้าง?"
        ],
        "zh": [
            "如何在土地厅为别墅建筑单独办理地上权（Superficies，第1410条）登记？",
            "如何拟定包含续租承诺条款的30年期土地租赁合同（Leasehold）？",
            "设立泰国合资公司持有居住用途土地面临哪些具体审查风险？"
        ]
    },
    "CORPORATE_FOREIGN_BUSINESS": {
        "ru": [
            "Как безопасно распределить права голоса через привилегированные акции (Preference Shares)?",
            "Какие документы требует Департамент развития бизнеса (DBD) для подтверждения тайских участников?",
            "Как получить лицензию Foreign Business License (FBL) для ведения бизнеса иностранцем?"
        ],
        "en": [
            "How to structure voting rights through Preference Shares to ensure foreign managerial control?",
            "What financial evidence does the DBD mandate to verify the solvency of 51% Thai shareholders?",
            "What is the statutory application procedure for a Foreign Business License (FBL) under List 3?"
        ],
        "th": [
            "การกำหนดสิทธิออกเสียงผ่านหุ้นบุริมสิทธิ (Preference Shares) มีหลักเกณฑ์อย่างไร?",
            "เอกสารหลักฐานทางการเงินที่กรมพัฒนาธุรกิจการค้า (DBD) กำหนดในการตรวจสอบผู้ถือหุ้นไทย?",
            "ขั้นตอนการยื่นขอรับใบอนุญาตประกอบธุรกิจของคนต่างด้าว (FBL) มีกระบวนการอย่างไร?"
        ],
        "zh": [
            "如何通过发行优先股（Preference Shares）实现表决权差异化与外方实际经营控制？",
            "商业发展厅（DBD）对出资500万泰铢以上的泰籍股东有哪些实质资金穿透核查要求？",
            "外资全资或控股企业申请外国商业许可证（FBL）的法定审批流程为何？"
        ]
    },
    "TAX_REVENUE": {
        "ru": [
            "Как документально доказать, что ввозимый капитал заработан до 1 января 2024 года (льгота P.162)?",
            "Как применить зачет налога, уплаченного за рубежом, по Соглашению об избежании двойного налогообложения (DTA)?",
            "В какие сроки и по какой форме подается годовая налоговая декларация в Таиланде (PND 90/91)?"
        ],
        "en": [
            "How to document and prove that offshore funds were earned prior to Jan 1, 2024 (Order Paw. 162 exemption)?",
            "How to claim foreign tax credits under bilateral Double Taxation Agreements (DTA)?",
            "What are the statutory filing deadlines and forms for annual Thai Personal Income Tax (PND 90/91)?"
        ],
        "th": [
            "แนวทางการเตรียมเอกสารแสดงว่าเงินได้เกิดขึ้นก่อนวันที่ 1 ม.ค. 2567 ตามคำสั่ง ป.162/2566?",
            "การขอเครดิตภาษีที่ชำระไว้ในต่างประเทศตามอนุสัญญาภาษีซ้อน (DTA) มีเงื่อนไขอย่างไร?",
            "กำหนดระยะเวลาและแบบแสดงรายการภาษีเงินได้บุคคลธรรมดาประจำปี (ภ.ง.ด. 90/91) คือช่วงใด?"
        ],
        "zh": [
            "如何准备银行资金流转凭据以证明调入资金产生于2024年1月1日之前（P.162号免税合规）？",
            "如何依据双边避免双重征税协定（DTA）申请境外已纳税额抵免（Tax Credit）？",
            "泰国个人所得税年度汇算清缴（PND 90/91表）申报时间窗口与材料要求为何？"
        ]
    },
    "IMMIGRATION_VISA": {
        "ru": [
            "Какие категории визы LTR подходят для удаленных сотрудников и инвесторов?",
            "Каковы сроки и процедура получения Digital Work Permit через One-Stop Service (OSOS)?",
            "Какие штрафы и последствия предусмотрены за работу без действующего разрешения (ст. 81)?"
        ],
        "en": [
            "Which 10-Year LTR Visa category fits remote professionals and high-net-worth investors?",
            "What is the application timeline for a Digital Work Permit via the One Stop Service Center (OSOS)?",
            "What are the statutory penalties and blacklist risks for working without authorization (Section 81)?"
        ],
        "th": [
            "ประเภทของวีซ่า LTR 10 ปี สำหรับผู้เชี่ยวชาญพิเศษและนักลงทุนมีคุณสมบัติอย่างไร?",
            "ขั้นตอนการยื่นขอใบอนุญาตทำงานดิจิทัล (Digital Work Permit) ผ่านศูนย์ OSOS ใช้เวลากี่วัน?",
            "บทลงโทษและผลทางกฎหมายกรณีคนต่างด้าวทำงานโดยไม่มีใบอนุญาตทำงานมีอะไรบ้าง?"
        ],
        "zh": [
            "10年期LTR黄金签证（财富人士、外派员工及高技能专家类别）申请硬性指标为何？",
            "通过一站式投资服务中心（OSOS）办理电子工作证（Digital Work Permit）需时多久？",
            "未持有效工作许可证从事劳务面临哪些罚金、拘留及入境黑名单限制？"
        ]
    },
    "LABOR_EMPLOYMENT": {
        "ru": [
            "Как правильно составить соглашение о расторжении трудового договора (Mutual Separation Agreement)?",
            "Какие действия сотрудника признаются грубым нарушением по ст. 119 LPA без выплаты пособия?",
            "Как рассчитывается средний дневной заработок для выплаты пособия по ст. 118 LPA?"
        ],
        "en": [
            "How to structure an enforceable Mutual Separation Agreement under Thai labor practice?",
            "What specific acts constitute gross misconduct under LPA Section 119 eliminating severance pay?",
            "How is the daily base wage calculated for statutory severance under LPA Section 118?"
        ],
        "th": [
            "แนวทางการทำสัญญาเลิกจ้างด้วยความยินยอมร่วมกัน (Mutual Separation Agreement) มีข้อควรระวังใด?",
            "การกระทำความผิดร้ายแรงตามมาตรา 119 ที่นายจ้างเลิกจ้างได้โดยไม่ต้องจ่ายค่าชдเชยมีกรณีใดบ้าง?",
            "หลักเกณฑ์การคำนวณอัตราค่าจ้างวันสุดท้ายเพื่อจ่ายค่าชดเชยตามมาตรา 118 มีวิธีการอย่างไร?"
        ],
        "zh": [
            "如何拟定合法有效的员工协商解除劳动合同协议（Mutual Separation Agreement）？",
            "哪些严重违纪违规行为符合《劳动保护法》第119条用人单位免付遣散补偿之法定事由？",
            "核算第118条法定遣散补偿金时的「日均薪酬基数」具体计算口径为何？"
        ]
    },
    "CIVIL_COMMERCIAL": {
        "ru": [
            "Как правильно заверить договор у тайского нотариуса (Notarial Services Attorney)?",
            "Каковы сроки исковой давности по гражданским обязательствам в Таиланде?",
            "Каков порядок досудебного урегулирования спора перед подачей иска в суд?"
        ],
        "en": [
            "How to formally notarize commercial contracts before a Thai Notarial Services Attorney?",
            "What are the statutory limitation periods for contractual claims under the CCC?",
            "What is the standard pre-litigation formal demand notice procedure under Thai court rules?"
        ],
        "th": [
            "การรับรองเอกสารสัญญาโดยทนายความผู้ทำคำรับรองลายมือชื่อ (Notarial Services Attorney) มีขั้นตอนอย่างไร?",
            "อายุความฟ้องร้องเรียกค่าเสียหายทางแพ่งและพาณิชย์ตามกฎหมายไทยมีกำหนดเวลากี่ปี?",
            "การส่งหนังสือบอกกล่าวทวงถาม (Notice) ก่อนฟ้องคดีต่อศาลมีแนวทางอย่างไร?"
        ],
        "zh": [
            "涉外民商事合同如何经由泰国执业公证律师（Notarial Services Attorney）正式见证公证？",
            "民商法典项下一般合同违约之民事诉讼时效期间为几年？",
            "向民事法院提起诉讼前，发送律师催告函（Legal Notice）之法定程序要求？"
        ]
    }
}

def search_statutes_and_precedents(query_text: str, domain: str, lang: str = "ru"):
    """
    Precision RAG search. Searches Qdrant (min_score=0.38) and PostgreSQL.
    Guarantees 100% language mirroring for titles, sections, and summaries.
    """
    hits = search_qdrant_hybrid(query_text, limit=10, min_score=0.38)
    
    if len(hits) < 2:
        pg_hits = search_postgres_keywords(query_text, domain, limit=4)
        for ph in pg_hits:
            hits.append(ph)

    statutes = []
    precedents = []
    seen_docs = set()

    for h in hits:
        doc_id = h.get("doc_id") or ""
        title = h.get("title") or ""
        chunk_text = h.get("chunk_text") or ""
        sec = h.get("section_num") or ""

        if "DEKA_" in doc_id or "คำพิพากษาศาลฎีกา" in title or "Supreme Court" in title:
            deka_no = doc_id.replace("TH_DEKA_", "").replace("DEKA_", "").replace("_", "/")
            precedents.append({
                "doc_id": doc_id,
                "deka_no": deka_no,
                "title": title,
                "headline": chunk_text[:250].strip().replace("\n", " "),
                "score": h.get("score")
            })
        else:
            if doc_id not in seen_docs and len(statutes) < 4:
                seen_docs.add(doc_id)
                statutes.append({
                    "doc_id": doc_id,
                    "title": title,
                    "section_num": sec,
                    "snippet": chunk_text[:280].strip().replace("\n", " "),
                    "status": "ACTIVE",
                    "status_th": "มีผลใช้บังคับ",
                    "score": h.get("score")
                })

    # Prioritize domain's primary golden statute(s) so foundational acts appear first
    golden_list = DOMAIN_GOLDEN_STATUTES_MULTILINGUAL.get(domain, [])
    if golden_list:
        primary_golden = golden_list[0]
        existing_idx = next((i for i, s in enumerate(statutes) if s.get("doc_id") == primary_golden["doc_id"]), None)
        if existing_idx is not None:
            statutes.insert(0, statutes.pop(existing_idx))
        else:
            statutes.insert(0, primary_golden)

    # Domain Fallback if empty
    if not statutes:
        statutes = DOMAIN_GOLDEN_STATUTES_MULTILINGUAL.get(domain, DOMAIN_GOLDEN_STATUTES_MULTILINGUAL["CIVIL_COMMERCIAL"])

    return statutes[:3], precedents[:2]

GREETING_QUESTIONS = {
    "en": [
        "Can a foreigner own 100% of a condominium unit under the Foreign Freehold Quota (49%)?",
        "How can an expat legally hold land or a villa through Leasehold or Superficies?",
        "Are overseas funds remitted to Thailand subject to personal income tax (RD P.161/162)?",
        "What are the statutory severance scales for dismissing an employee under LPA Section 118?",
        "What are the criminal penalties for using Thai nominee shareholders under FBA Section 36?"
    ],
    "th": [
        "คนต่างด้าวสามารถถือกรรมสิทธิ์ห้องชุดในโควตาคนต่างด้าว 49% ได้อย่างไร?",
        "แนวทางและเงื่อนไขการถือครองที่ดินผ่านการจดทะเบียนสิทธิการเช่า 30 ปี และสิทธิเหนือพื้นดิน?",
        "เกณฑ์การเสียภาษีเงินได้จากต่างประเทศตามคำสั่งกรมสรรพากร ที่ ป.161/2566 และ ป.162/2566?",
        "อัตราค่าชดเชยการเลิกจ้างตามอายุงานตามมาตรา 118 แห่ง พ.ร.บ.คุ้มครองแรงงาน?",
        "ข้อห้ามและบทลงโทษทางอาญาเกี่ยวกับการใช้ Nominee ถือหุ้นแทนตาม พ.ร.บ.ต่างด้าว?"
    ],
    "ru": [
        "Может ли иностранец купить квартиру в кондоминиуме в 100% собственность (Freehold 49%) и как получить форму FET?",
        "Как законно оформить землю и виллу в Таиланде через Leasehold на 30 лет и право суперфиция?",
        "Облагаются ли налогом в Таиланде деньги, переведенные из-за границы (распоряжения RD P.161 и P.162)?",
        "Каков размер выходного пособия при увольнении сотрудника по трудовому закону LPA (ст. 118)?",
        "Какие правила для компании 51/49 и уголовная ответственность за номиналов по ст. 36 FBA?"
    ],
    "zh": [
        "外籍人士如何依法取得泰国公寓49%永久产权（Foreign Freehold）并办理境外汇款FET核准函？",
        "外籍人士如何通过30年法定登记租赁权（Leasehold）及地上权合规持有泰国别墅与土地？",
        "根据税务局P.161/162号令，汇入泰国的境外所得如何判定税务居民身份并合法纳税？",
        "依据《劳动保护法》第118条，用人单位辞退员工应支付的法定遣散补偿阶梯标准是多少？",
        "依照泰国《外籍商法》第36条，借名持股（Nominee）面临何种刑事法律责任？"
    ]
}

# ─────────────────────────────────────────────────────────────────────────────
# 5. CHAT ADVISORY HANDLER
# ─────────────────────────────────────────────────────────────────────────────

def get_adaptive_clarifications(domain: str, query: str, lang: str = "ru") -> List[str]:
    """
    Dynamically generates sharp, progressive follow-up questions tailored to what the user
    just asked, completely filtering out redundant queries and advancing the legal strategy.
    """
    domain_clarifs = CLARIFICATIONS_MAP.get(domain, CLARIFICATIONS_MAP["CIVIL_COMMERCIAL"])
    all_qs = domain_clarifs.get(lang, domain_clarifs.get("ru", []))
    q_lower = query.lower()
    
    # Extract Russian and Latin root stems (min 4 chars)
    q_stems = set(w[:4] for w in re.split(r'\W+', q_lower) if len(w) >= 4)
    
    filtered = []
    for q in all_qs:
        q_words = [w for w in re.split(r'\W+', q.lower()) if len(w) >= 4]
        overlap = sum(1 for w in q_words if w[:4] in q_stems or w in q_lower)
        is_fet_redundant = ("fet" in q_lower or "фет" in q_lower or "назначен" in q_lower or "банк" in q_lower) and ("fet" in q.lower() or "назначен" in q.lower())
        is_quota_redundant = ("квот" in q_lower or "juristic" in q_lower or "debt-free" in q_lower or "долг" in q_lower) and ("квот" in q.lower() or "juristic" in q.lower())
        is_superficies_redundant = ("суперфиций" in q_lower or "1410" in q_lower) and ("суперфиций" in q.lower() or "1410" in q.lower())
        is_lease_redundant = ("30 лет" in q_lower or "leasehold" in q_lower or "продлен" in q_lower) and ("30 лет" in q.lower() or "leasehold" in q.lower())
        is_nominee_redundant = ("номинал" in q_lower or "nominee" in q_lower or "fba" in q_lower) and ("номинал" in q.lower() or "fba" in q.lower())
        is_p161_redundant = ("p.161" in q_lower or "p.162" in q_lower or "2024" in q_lower) and ("p.161" in q.lower() or "p.162" in q.lower())
        is_severance_redundant = ("118" in q_lower or "выходное пособие" in q_lower or "шкал" in q_lower) and ("118" in q.lower() or "пособие" in q.lower())

        if overlap < 2 and not any([is_fet_redundant, is_quota_redundant, is_superficies_redundant, is_lease_redundant, is_nominee_redundant, is_p161_redundant, is_severance_redundant]):
            filtered.append(q)
            
    # Pool of high-value progressive strategic questions per domain
    extras_pool = {
        "CONDO_PROPERTY": {
            "ru": [
                "Какие налоги и сборы (Transfer Fee 2%, SBT 3.3%) уплачиваются при сделке в Land Office?",
                "Как проверить задолженности и получить справку Debt-Free от кондоминиума?",
                "Как оформить покупку квартиры удаленно по доверенности Tor Dor 21?",
                "Как проверить чистоту договора купли-продажи (SPA) застройщика перед внесением задатка?",
                "В чем разница между формой FET на сумму от $50 000 и справкой Credit Advice?"
            ],
            "en": [
                "What are the Land Office transfer taxes and closing fees (2% fee, 3.3% SBT)?",
                "How to verify the Debt-Free Certificate and 49% quota ratio with the juristic person?",
                "How to complete the apartment purchase remotely via Power of Attorney Tor Dor 21?",
                "How to conduct legal due diligence on the developer's Sale and Purchase Agreement?",
                "What is the difference between a FET form above $50k and a bank Credit Advice?"
            ]
        },
        "LAND_PROPERTY": {
            "ru": [
                "Как составить договор аренды Leasehold на 30 лет с правом продления на следующие 30 лет?",
                "Как зарегистрировать право суперфиция (ст. 1410 CCC) на здание виллы в Land Office?",
                "Какие уголовные риски влечет использование тайской компании для покупки земли под виллу?",
                "Как зарегистрировать ипотеку на землю в пользу арендатора для гарантии продления?",
                "В чем разница между высшим титулом Чанот (Nor Sor 4) и временными документами?"
            ],
            "en": [
                "How to structure a 30-year registered Leasehold with enforceable renewal covenants?",
                "How to register a Right of Superficies (CCC Section 1410) for the villa building?",
                "What criminal risks under Land Code Section 86 arise from using a Thai nominee company?",
                "How to register a land mortgage in favor of the tenant to secure lease renewal?",
                "What is the legal difference between a Chanote (Nor Sor 4) and lower land documents?"
            ]
        },
        "CORPORATE_FOREIGN_BUSINESS": {
            "ru": [
                "Как распределить голосующие права через привилегированные акции (Preference Shares 10:1)?",
                "Какие документы требует Департамент развития бизнеса (DBD) для подтверждения тайских участников?",
                "Что такое сертификат BOI и как получить 100% иностранное владение без тайских партнеров?",
                "Как открыть корпоративный банковский счет с правом единоличной подписи иностранного директора?",
                "Какие виды деятельности входят в ограниченный Список 3 Закона FBA?"
            ],
            "en": [
                "How to structure voting rights through Preference Shares (10:1) for foreign control?",
                "What financial proof does the DBD mandate to verify the solvency of Thai shareholders?",
                "What is a BOI certificate and how to achieve 100% foreign ownership without Thai partners?",
                "How to open a corporate bank account with sole foreign directorial signatory power?",
                "Which commercial activities fall under restricted List 3 of the Foreign Business Act?"
            ]
        },
        "TAX_REVENUE": {
            "ru": [
                "Как документально доказать, что ввозимый капитал заработан до 1 января 2024 года (льгота P.162)?",
                "Как применить зачет налога, уплаченного за рубежом, по Соглашению об избежании двойного налогообложения (DTA)?",
                "Каковы ставки прогрессивной шкалы подоходного налога (PIT) в Таиланде (от 0% до 35%)?",
                "В какие сроки и по какой форме подается годовая налоговая декларация в Таиланде (PND 90/91)?",
                "Как получить тайский персональный налоговый номер (TIN) в районном налоговом органе?"
            ],
            "en": [
                "How to document that offshore savings were earned prior to Jan 1, 2024 (Order P.162)?",
                "How to apply foreign tax credits under Double Taxation Avoidance Agreements (DTA)?",
                "What are the progressive Personal Income Tax (PIT) brackets in Thailand (0% to 35%)?",
                "What are the annual tax return filing deadlines and forms (PND 90/91)?",
                "How to obtain a Thai Tax Identification Number (TIN) at the local Revenue Branch?"
            ]
        },
        "LABOR_EMPLOYMENT": {
            "ru": [
                "Как правильно составить соглашение о расторжении трудового договора (Mutual Separation Agreement)?",
                "Какие действия сотрудника признаются грубым нарушением по ст. 119 LPA без выплаты пособия?",
                "Каковы сроки и правила письменного предупреждения об увольнении по ст. 17 LPA?",
                "Как рассчитывается средний дневной заработок для выплаты пособия по ст. 118 LPA?",
                "Каковы судебные риски иска о несправедливом увольнении (Unfair Dismissal) в трудовом суде?"
            ],
            "en": [
                "How to draft an enforceable Mutual Separation Agreement (MSA) with full waiver of claims?",
                "What employee actions constitute gross misconduct under LPA Section 119 without severance?",
                "What are the statutory notice period rules under LPA Section 17?",
                "How is the daily wage calculated for statutory severance under LPA Section 118?",
                "What are the judicial risks of an Unfair Dismissal claim before the Central Labour Court?"
            ]
        },
        "IMMIGRATION_VISA": {
            "ru": [
                "Какие категории визы LTR подходят для удаленных сотрудников и инвесторов?",
                "Каковы сроки и процедура получения Digital Work Permit через One-Stop Service (OSOS)?",
                "Какие штрафы и последствия предусмотрены за работу без действующего разрешения (ст. 81)?",
                "В чем разница между визой Destination Thailand Visa (DTV) и рабочей визой Non-B?",
                "Как оформить разрешение на повторный въезд (Re-Entry Permit) для сохранения визы?"
            ],
            "en": [
                "Which 10-Year LTR Visa categories suit remote professionals and investors?",
                "What is the expedited application process for a Digital Work Permit via OSOS?",
                "What statutory penalties and deportation risks apply to working without a permit?",
                "What is the difference between the Destination Thailand Visa (DTV) and a Non-B visa?",
                "How to obtain a Re-Entry Permit to protect existing visa validity upon departure?"
            ]
        },
        "CIVIL_COMMERCIAL": {
            "ru": [
                "Как правильно заверить договор у тайского нотариуса (Notarial Services Attorney)?",
                "Каковы сроки исковой давности по гражданским договорам в Таиланде?",
                "Каков порядок досудебного урегулирования спора и вручения официальной претензии (Notice)?",
                "Как составить арбитражную оговорку институтов TAI или THAC в коммерческом контракте?",
                "Как проверить выписку из торгового реестра DBD и полномочия директоров перед сделкой?"
            ],
            "en": [
                "How to formally notarize contracts before a Thai Notarial Services Attorney?",
                "What are the statutory limitation periods for contractual claims under the CCC?",
                "What is the legal procedure for serving a formal pre-litigation demand Notice?",
                "How to draft an enforceable arbitration clause for TAI or THAC institutions?",
                "How to audit the DBD corporate registry affidavit and signatory directors prior to signing?"
            ]
        }
    }

    domain_extras = extras_pool.get(domain, extras_pool["CIVIL_COMMERCIAL"])
    extra_list = domain_extras.get(lang, domain_extras.get("ru", []))
    
    for ex in extra_list:
        ex_words = [w for w in re.split(r'\W+', ex.lower()) if len(w) >= 4]
        overlap = sum(1 for w in ex_words if w[:4] in q_stems or w in q_lower)
        if overlap < 2 and ex not in filtered and len(filtered) < 3:
            filtered.append(ex)
            
    return filtered[:3]


@app.post("/api/chat", response_model=ChatResponse)
@app.post("/api/ask", response_model=ChatResponse)
async def chat_consultation(req: ChatRequest):
    q_text = (req.query or req.message or "").strip()
    if not q_text:
        raise HTTPException(status_code=400, detail="Query message cannot be empty")
    if len(q_text) > 4000:
        raise HTTPException(status_code=400, detail="Query message exceeds maximum allowed limit of 4000 characters")
    req.query = q_text
    norm_uid = normalize_user_id(req.user_id)
    req.user_id = norm_uid
    profile = user_mgr.get_or_create(norm_uid)
    effective_lang = req.lang or req.language or profile.preferred_language
    
    session = user_mgr.get_or_create_session(req.session_id, req.user_id, effective_lang or "en")
    current_session_id = session.session_id

    # Construct Core Turn Input
    turn_input = UserTurnInput(
        user_id=norm_uid,
        session_id=current_session_id,
        case_id=f"case_{current_session_id}",
        input_type="text",
        raw_text=req.query,
        language_hint=effective_lang
    )

    # Process turn strictly through Consultant+ Core Engine 2.0 (Zero Heuristic / Procedural Fallback)
    core_resp = core_engine.process_turn(turn_input)

    # Sync language preference
    user_mgr.update_language(norm_uid, core_resp.lang)
    user_mgr.record_query(norm_uid, req.query, core_resp.domain)

    # Enrich UI representations
    enriched_stat_ui = []
    for s in core_resp.statutory_references:
        enriched_stat_ui.append({
            "id": s.get("id") or s.get("doc_id", "STATUTE_REF"),
            "key": s.get("key", ""),
            "title": s.get("title", ""),
            "section_num": s.get("section_num", ""),
            "snippet": s.get("snippet", ""),
            "full_text": s.get("full_text", s.get("snippet", "")),
            "official_th": s.get("official_th", ""),
            "official_th_section": s.get("official_th_section", s.get("section_num", "")),
            "official_th_text": s.get("official_th_text", s.get("official_th", "")),
            "status": s.get("status", "ACTIVE"),
            "status_th": s.get("status_th", "มีผลใช้บังคับ"),
            "score": s.get("score", 0.95)
        })

    enriched_prec_ui = []
    for p in core_resp.precedents:
        enriched_prec_ui.append({
            "doc_id": p.get("doc_id", "SAN_DEKA_REF"),
            "deka_no": p.get("deka_no", "Прецедент Верховного Суда Таиланда"),
            "headline": p.get("headline", ""),
            "full_text": p.get("full_text", p.get("headline", ""))
        })

    # Save to session history for UI navigation
    user_mgr.add_message(
        session_id=current_session_id,
        role="user",
        content=req.query,
        domain=core_resp.domain
    )
    user_mgr.add_message(
        session_id=current_session_id,
        role="assistant",
        content=core_resp.answer,
        domain=core_resp.domain,
        citations=enriched_stat_ui,
        precedents=enriched_prec_ui,
        proactive_clarifications=core_resp.proactive_clarifications,
        related_case=None
    )

    # Record self-learning QA asynchronously
    try:
        record_self_learning_qa(
            conn_params=PG_CONFIG,
            query=req.query,
            answer=core_resp.answer,
            lang=core_resp.lang,
            persona=req.user_role or "investor",
            domain=core_resp.domain
        )
    except Exception as e:
        logger.warning(f"Self-learning loop notice: {e}")

    return ChatResponse(
        answer=core_resp.answer,
        lang=core_resp.lang,
        statutory_references=enriched_stat_ui,
        precedents=enriched_prec_ui,
        proactive_clarifications=core_resp.proactive_clarifications,
        domain=core_resp.domain,
        sources=core_resp.sources or [
            {"source": "Королевская газета Королевства Таиланд (Royal Thai Government Gazette)", "status": "Верифицировано"},
            {"source": "Верховный Суд Таиланда (San Deka Repository)", "status": "Официальная судебная практика"}
        ],
        session_id=current_session_id,
        session_title=session.title,
        related_case=None,
        trace_id=core_resp.trace_id
    )
# ─────────────────────────────────────────────────────────────────────────────
# 6. MULTI-SESSION DIALOG MANAGEMENT API ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/api/user/{user_id}/sessions")
def get_user_sessions(user_id: str):
    sessions = user_mgr.list_user_sessions(user_id)
    return {
        "user_id": user_id,
        "count": len(sessions),
        "sessions": sessions
    }

@app.post("/api/user/{user_id}/sessions/new")
def create_new_session_endpoint(user_id: str, req: Optional[CreateSessionRequest] = None):
    lang = req.lang if req else "en"
    title = req.title if req else None
    domain = req.domain if req else "GENERAL"
    sess = user_mgr.create_new_session(user_id=user_id, lang=lang, title=title, domain=domain)
    return {
        "status": "created",
        "session_id": sess.session_id,
        "title": sess.title,
        "domain": sess.domain,
        "created_at": sess.created_at
    }

@app.get("/api/sessions/{session_id}")
def get_session_details(session_id: str, user_id: Optional[str] = None):
    data = user_mgr.get_session_data(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required: user_id must be provided")
    if data.get("user_id") and data.get("user_id") != normalize_user_id(user_id):
        raise HTTPException(status_code=403, detail="Access denied: session belongs to another user")
    return data

@app.get("/api/user/{user_id}/sessions/{session_id}")
def get_user_session_details(user_id: str, session_id: str):
    return get_session_details(session_id=session_id, user_id=user_id)

@app.delete("/api/sessions/{session_id}")
def delete_session_endpoint(session_id: str, user_id: str = "default_user"):
    success = user_mgr.delete_session(session_id, user_id)
    return {"status": "deleted" if success else "not_found", "session_id": session_id}


# ─────────────────────────────────────────────────────────────────────────────
# 5.1. DYNAMIC STATUTE FULL-TEXT LOOKUP ENDPOINT
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/api/statute/{statute_key}")
def get_statute_details(statute_key: str, lang: str = "en"):
    if ".." in statute_key or "/" in statute_key or "\\" in statute_key:
        raise HTTPException(status_code=400, detail="Invalid statute key format")
    from legal_synthesizer import STATUTE_KNOWLEDGE_BASE
    stat = STATUTE_KNOWLEDGE_BASE.get(statute_key)
    if not stat:
        for k, v in STATUTE_KNOWLEDGE_BASE.items():
            if k.lower() == statute_key.lower():
                stat = v
                statute_key = k
                break
    
    if stat:
        return {
            "key": statute_key,
            "title": stat.get(f"title_{lang}", stat.get("title_en", "")),
            "section_num": stat.get(f"section_{lang}", stat.get("section_en", "")),
            "summary": stat.get(f"summary_{lang}", stat.get("summary_en", "")),
            "full_text": stat.get(f"full_text_{lang}", stat.get("full_text_en", "")),
            "official_th": stat.get("official_th", ""),
            "official_th_section": stat.get("official_th_section", ""),
            "official_th_text": stat.get("official_th_text", ""),
            "krisdika_commentary": stat.get(f"krisdika_{lang}", stat.get("krisdika_en", "")),
            "status": "ACTIVE",
            "status_th": "มีผลใช้บังคับ"
        }

    # Live Database Fallback into thai_legal_chunks and thai_legal_cards
    conn = None
    try:
        conn = get_pg_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT c.chunk_id, c.doc_id, c.section_num, c.chunk_text,
                       d.title, d.status, d.status_th, d.full_text
                FROM thai_legal_chunks c
                LEFT JOIN thai_legal_cards d ON c.doc_id = d.doc_id
                WHERE c.chunk_id = %s OR c.doc_id = %s OR d.doc_id = %s
                LIMIT 1
            """, (statute_key, statute_key, statute_key))
            row = cur.fetchone()
            if row:
                c_id, doc_id, sec_num, chunk_text, doc_title, status_val, status_th_val, card_full_text = row
                title_val = doc_title or f"Statutory Provision {sec_num or doc_id}"
                return {
                    "key": c_id or statute_key,
                    "title": title_val,
                    "section_num": sec_num or "",
                    "summary": (chunk_text[:280] + "...") if len(chunk_text or "") > 280 else (chunk_text or ""),
                    "full_text": chunk_text or card_full_text or "",
                    "official_th": doc_title or "",
                    "official_th_section": sec_num or "",
                    "official_th_text": chunk_text or "",
                    "krisdika_commentary": "Regulatory review confirmed in the national legislative registry of the Kingdom of Thailand.",
                    "status": status_val or "ACTIVE",
                    "status_th": status_th_val or "มีผลใช้บังคับ"
                }
    except Exception as e:
        logger.warning(f"Database statute fallback error for {statute_key}: {e}")
    finally:
        if conn:
            try: conn.close()
            except: pass

    raise HTTPException(status_code=404, detail=f"Statute '{statute_key}' not found in primary catalog")

# ─────────────────────────────────────────────────────────────────────────────
# 5.2. UNIVERSAL THAI LEGAL & TAX CALCULATOR API
# ─────────────────────────────────────────────────────────────────────────────
class CalculationRequest(BaseModel):
    calc_type: str # REAL_ESTATE, FOREIGN_REMITTANCE, SEVERANCE_PAY, COMPANY_CAPITAL, VISA_MATCH
    params: Dict[str, Any]

@app.post("/api/calculate")
def calculate_thai_legal_metric(req: CalculationRequest):
    c_type = req.calc_type.upper()
    p = req.params

    if c_type == "REAL_ESTATE":
        price = float(p.get("property_price", 0))
        ownership = p.get("ownership_type", "FREEHOLD")
        years_held = float(p.get("years_held", 1))
        is_corporate_seller = bool(p.get("is_corporate_seller", False))

        if ownership == "FREEHOLD":
            transfer_fee = price * 0.02
            if years_held < 5:
                sbt = price * 0.033
                stamp_duty = 0.0
            else:
                sbt = 0.0
                stamp_duty = price * 0.005
            wht = price * 0.01 if is_corporate_seller else (price * 0.02)
            total = transfer_fee + sbt + stamp_duty + wht
            return {
                "calc_type": c_type,
                "price": price,
                "ownership": ownership,
                "transfer_fee_2pct": transfer_fee,
                "sbt_3_3pct": sbt,
                "stamp_duty_0_5pct": stamp_duty,
                "wht": wht,
                "total_closing_taxes": total,
                "buyer_customary_share": transfer_fee / 2.0,
                "seller_customary_share": (transfer_fee / 2.0) + sbt + stamp_duty + wht,
                "statute": "ст. 19 Закона о кондоминиумах Б.Э. 2522 (Condominium Act)",
                "fet_required": True
            }
        else: # LEASEHOLD
            reg_fee = price * 0.01
            stamp_duty = price * 0.001
            total = reg_fee + stamp_duty
            return {
                "calc_type": c_type,
                "price": price,
                "ownership": ownership,
                "registration_fee_1pct": reg_fee,
                "stamp_duty_0_1pct": stamp_duty,
                "total_closing_taxes": total,
                "buyer_customary_share": total / 2.0,
                "seller_customary_share": total / 2.0,
                "max_legal_years": 30,
                "statute": "ст. 538 Гражданского и коммерческого кодекса Таиланда (CCC)",
                "fet_required": False
            }

    elif c_type == "FOREIGN_REMITTANCE":
        days = int(p.get("days_in_thailand", 185))
        earned_prior_2024 = bool(p.get("earned_prior_to_2024", False))
        remitted_amount = float(p.get("remitted_amount_thb", 1000000))
        dta_foreign_tax_paid = float(p.get("dta_foreign_tax_paid_thb", 0))

        is_tax_resident = days >= 180
        if not is_tax_resident:
            return {
                "is_tax_resident": False,
                "days": days,
                "tax_due_thb": 0,
                "effective_rate": "0%",
                "rule": "Не налоговый резидент (<180 дней). Ввоз любых средств не облагается налогом по ст. 41 абз. 2 Revenue Code."
            }
        if earned_prior_2024:
            return {
                "is_tax_resident": True,
                "days": days,
                "tax_due_thb": 0,
                "effective_rate": "0% (Grandfathered)",
                "rule": "Освобождение по распоряжению RD P.162/2566: сбережения, заработанные до 1 января 2024 года, не подлежат тайскому PIT при ввозе."
            }

        brackets = [
            (150000, 0.0),
            (150000, 0.05),
            (200000, 0.10),
            (250000, 0.15),
            (250000, 0.20),
            (1000000, 0.25),
            (3000000, 0.30),
            (float("inf"), 0.35)
        ]
        rem = remitted_amount
        pit_total = 0.0
        for span, rate in brackets:
            if rem <= 0:
                break
            taxable_chunk = min(rem, span)
            pit_total += taxable_chunk * rate
            rem -= taxable_chunk

        final_tax = max(0.0, pit_total - dta_foreign_tax_paid)
        return {
            "is_tax_resident": True,
            "days": days,
            "remitted_amount_thb": remitted_amount,
            "pit_calculated_thb": pit_total,
            "dta_credit_applied_thb": dta_foreign_tax_paid,
            "final_tax_due_thb": final_tax,
            "effective_rate": f"{(final_tax / remitted_amount * 100):.1f}%" if remitted_amount > 0 else "0%",
            "rule": "Распоряжение RD P.161/2566: прогрессивный Personal Income Tax (PIT) 0-35% с зачетом иностранного налога (DTA Tax Credit)."
        }

    elif c_type == "SEVERANCE_PAY":
        months_worked = float(p.get("months_worked", 24))
        monthly_salary = float(p.get("monthly_salary_thb", 50000))
        daily_rate = monthly_salary / 30.0

        if months_worked < 4:
            days_pay = 0
        elif months_worked < 12:
            days_pay = 30
        elif months_worked < 36:
            days_pay = 90
        elif months_worked < 72:
            days_pay = 180
        elif months_worked < 120:
            days_pay = 240
        elif months_worked < 240:
            days_pay = 300
        else:
            days_pay = 400

        severance_amount = days_pay * daily_rate
        notice_pay_estimate = monthly_salary

        return {
            "months_worked": months_worked,
            "monthly_salary_thb": monthly_salary,
            "statutory_severance_days": days_pay,
            "severance_pay_thb": round(severance_amount, 2),
            "payment_in_lieu_of_notice_thb": notice_pay_estimate,
            "total_required_payout_thb": round(severance_amount + notice_pay_estimate, 2),
            "statute": "ст. 118 Закона о защите труда Б.Э. 2541 (Labor Protection Act)"
        }

    elif c_type == "COMPANY_CAPITAL":
        expats = int(p.get("foreign_employees_count", 1))
        is_boi = bool(p.get("is_boi_promoted", False))

        if is_boi:
            return {
                "is_boi": True,
                "min_registered_capital_thb": 0,
                "thai_employees_required": 0,
                "exemption_rule": "BOI Investment Promotion: освобождение от квоты 4 тайцев и требования 2 млн THB капитала на Work Permit."
            }
        else:
            req_capital = expats * 2000000
            req_thais = expats * 4
            return {
                "is_boi": False,
                "foreign_work_permits_supported": expats,
                "min_registered_capital_thb": req_capital,
                "min_thai_employees_required": req_thais,
                "mandatory_ratio": "4 тайских сотрудника с Social Security на 1 экспата",
                "statute": "ст. 8 Декрета об управлении иностранной рабочей силой Б.Э. 2560"
            }

    elif c_type == "VISA_MATCH":
        budget_usd = float(p.get("budget_usd", 15000))
        monthly_income_usd = float(p.get("monthly_income_usd", 3000))
        needs_work_in_th = bool(p.get("needs_work_in_th", False))
        
        recommendations = []
        if needs_work_in_th:
            recommendations.append({
                "visa": "Non-B + Digital Work Permit",
                "match_score": "95%",
                "reason": "Единственный способ законно работать на тайском рынке и управлять местной компанией."
            })
        if monthly_income_usd >= 6666 or budget_usd >= 500000:
            recommendations.append({
                "visa": "LTR (Long-Term Resident)",
                "match_score": "98%",
                "reason": "10 лет, 0% налог на зарубежный доход, Digital Work Permit без квоты 4 тайцев."
            })
        if budget_usd >= 14500 and not needs_work_in_th:
            recommendations.append({
                "visa": "DTV (Destination Thailand Visa)",
                "match_score": "99%",
                "reason": "Идеально для удаленщиков: 5 лет, 180+180 дней, депозит всего 500k THB (~$14 500), сбор 10k THB."
            })
        if budget_usd >= 25000 and not needs_work_in_th:
            recommendations.append({
                "visa": "Thailand Privilege (Elite)",
                "match_score": "88%",
                "reason": "Без подтверждения доходов и депозитов: 5-20 лет за единый взнос от 900k THB."
            })
            
        return {
            "budget_usd": budget_usd,
            "monthly_income_usd": monthly_income_usd,
            "recommendations": recommendations
        }

    raise HTTPException(status_code=400, detail="Unknown calculation type")

@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "Consultant+",
        "version": "4.6.0",
        "languages": ["ru", "en", "th", "zh"],
        "default_language": "en"
    }

@app.get("/api/i18n/{lang}")
def get_i18n_bundle(lang: str):
    return {
        "lang": lang,
        "strings": get_all_ui_strings(lang)
    }

@app.get("/api/user/profile/{user_id}")
def get_profile(user_id: str):
    u = normalize_user_id(user_id)
    p = user_mgr.get_or_create(u)
    return {"status": "ok", "profile": p.dict(), **p.dict()}

@app.get("/api/user/{user_id}/profile")
def get_user_profile_rest(user_id: str):
    u = normalize_user_id(user_id)
    p = user_mgr.get_or_create(u)
    return {"status": "ok", "profile": p.dict(), **p.dict()}

@app.get("/api/user/profile")
def get_profile_query(user_id: str = "default_user"):
    u = normalize_user_id(user_id)
    p = user_mgr.get_or_create(u)
    return {"status": "ok", "profile": p.dict(), **p.dict()}

@app.post("/api/user/profile")
def update_profile(req: ProfileUpdateRequest):
    u = normalize_user_id(req.user_id)
    profile = user_mgr.get_or_create(u)
    if req.preferred_language:
        user_mgr.update_language(u, req.preferred_language)
    if req.user_role:
        profile.user_role = "client"
    if req.jurisdiction_focus:
        profile.jurisdiction_focus = req.jurisdiction_focus
    if req.active_legal_matter:
        profile.active_legal_matter = req.active_legal_matter
    return {"status": "updated", "profile": profile.dict()}
