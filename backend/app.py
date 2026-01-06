#!/usr/bin/env python3
# backend/app.py
from fastapi import FastAPI
import httpx
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
import os
import ollama # Import the ollama client
import redis
import hashlib
import json
import logging

logger = logging.getLogger(__name__)

# Import bot routers
from telegram_bot import router as telegram_router

app = FastAPI(title="Thai Law AI Assistant", version="2.0")

# Include bot routers
app.include_router(telegram_router)

# --- КОНФИГУРАЦИЯ СЕРВИСОВ ---
QDRANT_URL = os.getenv("QDRANT_URL", "http://thai-qdrant:6333")
COL = os.getenv("QDRANT_COLLECTION", "thai_law")
EMBED_MODEL = os.getenv("EMBED_MODEL", "VISAI-AI/nitibench-ccl-human-finetuned-bge-m3")
INDEXER_URL = os.getenv("INDEXER_URL", "http://thai-indexer:8001/index")
OLLAMA_HOST = os.getenv("OLLAMA_URL", "http://thai-ollama:11434")
REDIS_URL = os.getenv("REDIS_URL", "redis://thai-redis:6379/0")
CACHE_TTL = int(os.getenv("CACHE_TTL", "3600"))  # 1 hour cache

# --- ИНИЦИАЛИЗАЦИЯ КЛИЕНТОВ ---
# Модель для эмбеддингов
embed_model = SentenceTransformer(EMBED_MODEL)
# Клиент Qdrant
qclient = QdrantClient(url=QDRANT_URL)
# Клиент Ollama
# Обертываем вызов ollama.Client в try-except на случай, если ollama не запущен при старте
try:
    ollama_client = ollama.Client(host=OLLAMA_HOST)
    print(f"Connected to Ollama at {OLLAMA_HOST}")
except Exception as e:
    print(f"WARNING: Could not connect to Ollama at {OLLAMA_HOST}. RAG functionality will be limited. Error: {e}")
    ollama_client = None

# Redis client for caching
try:
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    redis_client.ping()
    print(f"Connected to Redis at {REDIS_URL}")
except Exception as e:
    print(f"WARNING: Could not connect to Redis at {REDIS_URL}. Caching disabled. Error: {e}")
    redis_client = None


def get_cache_key(query: str, model: str) -> str:
    """Generate a cache key based on query and model"""
    content = f"{query}:{model}"
    return f"rag:{hashlib.md5(content.encode()).hexdigest()}"


def get_cached_response(query: str, model: str) -> dict | None:
    """Try to get cached response from Redis"""
    if not redis_client:
        return None
    try:
        key = get_cache_key(query, model)
        cached = redis_client.get(key)
        if cached:
            logger.info(f"Cache hit for query: {query[:50]}...")
            return json.loads(cached)
    except Exception as e:
        logger.error(f"Redis get error: {e}")
    return None


def cache_response(query: str, model: str, response: dict) -> None:
    """Cache response to Redis"""
    if not redis_client:
        return
    try:
        key = get_cache_key(query, model)
        redis_client.setex(key, CACHE_TTL, json.dumps(response, ensure_ascii=False))
        logger.info(f"Cached response for query: {query[:50]}...")
    except Exception as e:
        logger.error(f"Redis set error: {e}")


# ============= SMART QUERY CLASSIFICATION =============
# Patterns for quick responses (no RAG needed)
GREETING_PATTERNS = [
    # Greetings
    "привет", "здравствуй", "добрый день", "добрый вечер", "доброе утро", "хай", "хелло",
    "hello", "hi", "hey", "good morning", "good evening", "good afternoon",
    "สวัสดี", "หวัดดี", "ดี",
    # Meta questions
    "кто ты", "что ты", "чем полез", "что умеешь", "как дела", "как поживаешь",
    "who are you", "what can you do", "how are you", "what do you know",
    "คุณคือใคร", "ทำอะไรได้",
    # Simple thanks
    "спасибо", "благодарю", "thank", "ขอบคุณ",
]

LEGAL_KEYWORDS = [
    # Russian
    "закон", "налог", "штраф", "виза", "разрешение", "лицензия", "договор", "суд", 
    "право", "статья", "кодекс", "регистрация", "бизнес", "компания", "работа",
    "правонарушение", "наказание", "документ", "паспорт", "недвижимость",
    # English
    "law", "tax", "fine", "visa", "permit", "license", "contract", "court", 
    "legal", "article", "code", "registration", "business", "company", "work",
    "violation", "penalty", "document", "passport", "property", "regulation",
    # Thai
    "กฎหมาย", "ภาษี", "ค่าปรับ", "วีซ่า", "ใบอนุญาต", "สัญญา", "ศาล",
    "มาตรา", "ทะเบียน", "ธุรกิจ", "บริษัท", "ทรัพย์สิน",
]


def is_greeting_or_meta(query: str) -> bool:
    """Check if query is a simple greeting or meta question (no RAG needed)"""
    query_lower = query.lower().strip()
    # Very short queries are usually greetings
    if len(query_lower) < 15:
        for pattern in GREETING_PATTERNS:
            if pattern in query_lower:
                return True
    return False


def is_legal_query(query: str) -> bool:
    """Check if query is about legal topics (needs RAG)"""
    query_lower = query.lower()
    for keyword in LEGAL_KEYWORDS:
        if keyword in query_lower:
            return True
    return False


def get_quick_response(query: str) -> str:
    """Generate quick response for greetings without using LLM"""
    query_lower = query.lower()
    
    # Detect language
    if any(c in query for c in "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"):
        lang = "ru"
    elif any(c in query for c in "กขคฆงจฉชซฌญฎฏฐฑฒณดตถทธนบปผฝพฟภมยรลวศษสหฬอฮ"):
        lang = "th"
    else:
        lang = "en"
    
    responses = {
        "ru": """👋 Привет! Я — AI-консультант по тайскому законодательству.

**Чем могу помочь:**
• 📋 Вопросы по законам Таиланда
• 💼 Налоги, визы, бизнес
• 📄 Разъяснение правовых норм

Просто задайте вопрос о тайском праве, и я постараюсь помочь!

_Примеры вопросов:_
• "Какой налог на недвижимость в Таиланде?"
• "Как продлить туристическую визу?"
• "Требования для открытия бизнеса"
""",
        "th": """👋 สวัสดีครับ! ผมคือผู้ช่วย AI ด้านกฎหมายไทย

**บริการของผม:**
• 📋 ตอบคำถามเกี่ยวกับกฎหมายไทย
• 💼 ภาษี, วีซ่า, ธุรกิจ
• 📄 อธิบายข้อกฎหมาย

ถามคำถามเกี่ยวกับกฎหมายไทยได้เลยครับ!
""",
        "en": """👋 Hello! I'm an AI legal consultant for Thai law.

**I can help with:**
• 📋 Questions about Thai laws
• 💼 Taxes, visas, business regulations
• 📄 Legal requirements and procedures

Just ask me any question about Thai law!

_Example questions:_
• "What are property taxes in Thailand?"
• "How to extend a tourist visa?"
• "Requirements for starting a business"
"""
    }
    return responses.get(lang, responses["en"])


class Query(BaseModel):
    query: str
    top_k: int = 3  # Reduced for faster search
    model: str = "qwen2.5:1.5b"  # Smaller, faster model for limited hardware

class AnswerResponse(BaseModel):
    text: str
    sources: list[dict]

@app.get("/health")
def health():
    return {"status": "ok"}

# System prompt for the legal AI assistant
SYSTEM_PROMPT = """You are a professional AI legal consultant specializing in Thai law (กฎหมายไทย).

🎯 YOUR ROLE:
- Primary audience: Thai lawyers and legal consultants
- Secondary audience: Tourists and expats seeking legal guidance (English, German, French, Russian speakers)

📋 CRITICAL RULES:
1. **LANGUAGE**: ALWAYS respond in the SAME language as the user's question
   - Thai question → Thai answer
   - English question → English answer  
   - Russian/German/French → respond in that language
2. **KNOWLEDGE BOUNDARY**: ONLY use information from the provided context
   - DO NOT invent, assume, or hallucinate any legal information
   - If the context is insufficient, clearly say: "Based on my current knowledge base, I cannot answer this question. Please consult a licensed Thai lawyer."
3. **ACCURACY**: Legal advice requires precision - never guess

💬 COMMUNICATION STYLE:
- Be professional yet approachable and human
- Show empathy: "I understand this situation can be stressful..."
- Be encouraging: "Great question! Let's figure this out together."
- Give clear step-by-step guidance when applicable
- You can be slightly warm and supportive, but maintain legal seriousness
- End with actionable next steps when possible

📝 RESPONSE FORMAT:
1. Acknowledge the question
2. Provide clear, structured answer based on context
3. Cite specific laws/articles when available
4. Suggest next steps or who to consult if needed

Remember: You are helping real people with real legal concerns. Be helpful, accurate, and responsible."""

@app.post("/query", response_model=AnswerResponse)
async def query(q: Query):
    # 0. Check cache first
    cached = get_cached_response(q.query, q.model)
    if cached:
        return AnswerResponse(**cached)
    
    # 1. FAST PATH: Greetings and meta questions (no RAG, no LLM)
    if is_greeting_or_meta(q.query) and not is_legal_query(q.query):
        quick_text = get_quick_response(q.query)
        response_data = {"text": quick_text, "sources": []}
        cache_response(q.query, q.model, response_data)
        return AnswerResponse(**response_data)
    
    # 2. Check if this is a legal query (needs RAG) or general question
    needs_rag = is_legal_query(q.query)
    
    contexts = []
    sources = []
    
    if needs_rag:
        # 3. Поиск релевантных документов в Qdrant
        query_vector = embed_model.encode(q.query).tolist()
        
        search_result = qclient.search(
            collection_name=COL,
            query_vector=query_vector,
            limit=q.top_k,
            with_payload=True,
        )

        contexts = [hit.payload.get("text", "") for hit in search_result]
        sources = [
            {
                "id": hit.id,
                "url": hit.payload.get("source_url"),
                "doc_id": hit.payload.get("doc_id"),
                "chunk_id": hit.payload.get("chunk_id"),
                "score": hit.score
            }
            for hit in search_result
        ]

    # 4. Generate response with LLM
    if ollama_client:
        if needs_rag and contexts:
            context_str = "\n---\n".join(contexts)
            full_prompt = f"""{SYSTEM_PROMPT}

=== CONTEXT FROM KNOWLEDGE BASE ===
{context_str}

=== USER QUESTION ===
{q.query}

=== YOUR RESPONSE ==="""
        else:
            # Simpler prompt for general questions (no context needed)
            full_prompt = f"""You are a helpful AI assistant for Thai law. 
Answer in the same language as the question.
Be brief and helpful. If this is not about Thai law, politely redirect.

Question: {q.query}

Answer:"""

        # 5. Call Ollama
        try:
            llm_response = ollama_client.generate(
                model=q.model,
                prompt=full_prompt,
                stream=False,
                options={
                    "num_predict": 500,  # Limit response length for speed
                    "temperature": 0.7,
                }
            )
            generated_text = llm_response['response'].strip()
        except Exception as e:
            print(f"Error calling Ollama: {e}")
            generated_text = f"Извините, произошла ошибка при генерации ответа. ({e})"
    else:
        generated_text = "Сервис Ollama недоступен."


    # 6. Cache and return response
    response_data = {"text": generated_text, "sources": sources}
    cache_response(q.query, q.model, response_data)
    return AnswerResponse(**response_data)

class IndexRequest(BaseModel):
    filenames: list[str] | None = None

@app.post("/admin/index")
async def admin_index(req: IndexRequest):
    # This endpoint allows triggering re-indexing from the backend if needed
    # It calls the actual indexer service
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(INDEXER_URL, json=req.dict())
    return resp.json()