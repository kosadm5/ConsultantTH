#!/usr/bin/env python3
"""
telegram_poller.py
Production Long-Polling Daemon for @ThaiLawBot (v6.0-PROD)
Integrated with Consultant+ RAG Backend (Port 8100).
- Resilient HTTP connection management with automatic session recreation on drops
- Chat Menu Button and persistent ReplyKeyboardMarkup for 100% WebApp launch reliability
- Real-time language and profile synchronization with Web App & Postgres
- Multi-session dialogue lifecycle (/new)
- Zero technical leak standards
"""

import sys
import os
import time
import json
import logging
import re
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Dict, Any, List

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("telegram_bot")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8521415927:AAFOiPqP88Gp29qPTtyRBOwmFFJEsiL1AlE")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8100")
MINI_APP_URL = os.getenv("MINI_APP_URL", "https://experiments-september-drill-sand.trycloudflare.com")

user_clarifications: Dict[int, List[str]] = {}
user_langs: Dict[str, str] = {}
user_active_session: Dict[str, str] = {}

def create_session() -> requests.Session:
    sess = requests.Session()
    retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=20)
    sess.mount('https://', adapter)
    sess.mount('http://', adapter)
    return sess

http_session = create_session()

def normalize_id(user_id: Any) -> str:
    s = str(user_id).strip()
    if not s.startswith("tg_"):
        return f"tg_{s}"
    return s

def call_tg(method: str, payload: Dict[str, Any] = None, timeout: int = 15) -> Dict[str, Any]:
    global http_session
    url = f"{API_URL}/{method}"
    try:
        resp = http_session.post(url, json=payload or {}, timeout=(5.0, float(timeout)))
        if resp.status_code == 200:
            return resp.json()
        logger.error(f"Telegram API {method} error ({resp.status_code}): {resp.text}")
    except Exception as e:
        logger.error(f"Telegram call exception ({method}): {e}")
        try:
            http_session.close()
        except Exception:
            pass
        http_session = create_session()
    return {}

def clean_for_telegram(text: str) -> str:
    """Strips HTML tags into clean text."""
    text = re.sub(r"<a\s+[^>]*>(.*?)</a>", r"*\1*", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return text

def send_message(chat_id: int, text: str, reply_markup: Dict[str, Any] = None, parse_mode: str = "Markdown") -> Dict[str, Any]:
    text = clean_for_telegram(text)
    if len(text) > 4000:
        text = text[:3950] + "\n\n... *(полный текст и статьи доступны в Web App)*"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "reply_markup": reply_markup or {}
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
        
    res = call_tg("sendMessage", payload)
    if not res.get("ok") and parse_mode:
        payload.pop("parse_mode", None)
        res = call_tg("sendMessage", payload)
    return res

def send_chat_action(chat_id: int, action: str = "typing"):
    call_tg("sendChatAction", {"chat_id": chat_id, "action": action})

def get_user_lang(user_id: str) -> str:
    nid = normalize_id(user_id)
    if nid in user_langs:
        return user_langs[nid]
    try:
        resp = http_session.get(f"{BACKEND_URL}/api/user/{nid}/profile", timeout=(3.0, 5.0))
        if resp.status_code == 200:
            prof = resp.json().get("profile", {})
            l = prof.get("preferred_language", "en")
            if l in ["ru", "en", "th", "zh"]:
                user_langs[nid] = l
                return l
    except Exception:
        pass
    return "en"

def sync_user_lang_to_backend(user_id: str, new_lang: str):
    nid = normalize_id(user_id)
    user_langs[nid] = new_lang
    try:
        http_session.post(
            f"{BACKEND_URL}/api/user/profile",
            json={"user_id": nid, "preferred_language": new_lang, "user_role": "client"},
            timeout=(3.0, 5.0)
        )
        logger.info(f"Synced language {new_lang} to backend for user {nid}")
    except Exception as e:
        logger.warning(f"Failed to sync language to backend: {e}")

def get_or_create_user_session(user_id: str) -> str:
    nid = normalize_id(user_id)
    if nid not in user_active_session:
        user_active_session[nid] = f"sess_{nid}_{int(time.time())}"
    return user_active_session[nid]

def reset_user_session(user_id: str) -> str:
    nid = normalize_id(user_id)
    new_sess = f"sess_{nid}_{int(time.time())}"
    user_active_session[nid] = new_sess
    return new_sess

def get_persistent_reply_keyboard(lang: str = "en") -> Dict[str, Any]:
    open_btn = {
        "ru": "📱 Открыть Consultant+",
        "en": "📱 Open Consultant+",
        "th": "📱 เปิด Consultant+",
        "zh": "📱 打开 Consultant+"
    }.get(lang, "📱 Открыть Consultant+")
    
    calc_btn = {
        "ru": "⚡ Экспресс-калькулятор",
        "en": "⚡ Legal Calculator",
        "th": "⚡ เครื่องคำนวณกฎหมาย",
        "zh": "⚡ 快捷法务计算器"
    }.get(lang, "⚡ Экспресс-калькулятор")

    new_btn = {
        "ru": "➕ Новый диалог",
        "en": "➕ New Consultation",
        "th": "➕ เริ่มแชทใหม่",
        "zh": "➕ 开启新会话"
    }.get(lang, "➕ Новый диалог")

    return {
        "keyboard": [
            [{"text": open_btn, "web_app": {"url": MINI_APP_URL}}],
            [{"text": calc_btn, "web_app": {"url": f"{MINI_APP_URL}#calculator"}}, {"text": new_btn}]
        ],
        "resize_keyboard": True,
        "is_persistent": True
    }

def build_clarification_keyboard(clarifications: List[str], lang: str = "en") -> Dict[str, Any]:
    buttons = []
    # Up to 2 sharp contextual follow-up questions
    for i, q in enumerate(clarifications[:2]):
        short_text = f"💡 {q[:42]}..." if len(q) > 45 else f"💡 {q}"
        buttons.append([{"text": short_text, "callback_data": f"clarify_{i}"}])
    
    new_dialog_labels = {
        "ru": "➕ Новый диалог",
        "en": "➕ New Chat",
        "th": "➕ เริ่มแชทใหม่",
        "zh": "➕ 开启新对话"
    }

    app_btn_text = {
        "ru": "📱 Открыть Consultant+",
        "en": "📱 Open Consultant+",
        "th": "📱 เปิด Consultant+",
        "zh": "📱 打开 Consultant+"
    }.get(lang, "📱 Открыть Consultant+")

    # Single sleek bottom row
    bottom_row = [
        {"text": app_btn_text, "web_app": {"url": MINI_APP_URL}},
        {"text": new_dialog_labels.get(lang, "➕ Новый диалог"), "callback_data": "cmd_new_dialog"}
    ]
    buttons.append(bottom_row)
    return {"inline_keyboard": buttons}

def handle_start(chat_id: int, user_id: str, first_name: str):
    lang = get_user_lang(user_id)
    
    # 1. Update Chat Menu Button directly for this user chat
    call_tg("setChatMenuButton", {
        "chat_id": chat_id,
        "menu_button": {
            "type": "web_app",
            "text": "📱 Consultant+",
            "web_app": {"url": MINI_APP_URL}
        }
    })
    
    welcomes = {
        "ru": (
            f"👋 **Привет, {first_name}!**\n\n"
            "Я твой надежный юридический советник в Таиланде — **Consultant+** 🏛️\n\n"
            "Объясняю законы Королевства простым языком, строю надежные пошаговые планы, "
            "подсвечиваю лазейки и защищаю от скрытых ловушек в недвижимости, налогах и бизнесе.\n\n"
            "Задай любой вопрос прямо сюда или запусти Web App для комфортной работы со статьями законов, калькуляторами и кодексами!"
        ),
        "en": (
            f"👋 **Hello, {first_name}!**\n\n"
            "I'm your practical legal advisor in Thailand — **Consultant+** 🏛️\n\n"
            "I translate complex Thai statutes into plain, actionable roadmaps, uncover legal loopholes, "
            "and protect you from costly pitfalls in real estate, taxation, and corporate setup.\n\n"
            "Ask me anything here, or launch the Web App for full-text statute viewing, calculators, and legal tools!"
        ),
        "th": (
            f"👋 **สวัสดีครับ คุณ {first_name}!**\n\n"
            "ผมคือที่ปรึกษากฎหมายส่วนตัวของคุณ — **Consultant+** 🏛️\n\n"
            "อธิบายกฎหมายไทยให้เข้าใจง่าย ชัดเจน วางแผนการดำเนินการทีละขั้นตอน "
            "พร้อมชี้ช่องทางที่ถูกต้องตามกฎหมายและป้องกันความเสี่ยงด้านอสังหาริมทรัพย์ ภาษี และธุรกิจ\n\n"
            "พิมพ์คำถามของคุณได้ทันที หรือเปิดใช้งาน Web App เพื่อดูตัวบทกฎหมายและเครื่องคำนวณฉบับเต็มได้เลยครับ!"
        ),
        "zh": (
            f"👋 **您好，{first_name}！**\n\n"
            "我是您的泰国法务私人顾问 — **Consultant+** 🏛️\n\n"
            "用最通俗易懂的语言为您剖析泰王国法律，量身定制实操步骤，"
            "指引合规捷径并规避房产、税务和公司经营中的法律陷阱。\n\n"
            "您可以直接提问，或开启专属 Web App 查看完整王家宪报法规原文与快捷计算工具！"
        )
    }

    text = welcomes.get(lang, welcomes["ru"])
    
    app_btn_label = {
        "ru": "📱 Открыть Consultant+",
        "en": "📱 Open Consultant+",
        "th": "📱 เปิด Consultant+",
        "zh": "📱 打开 Consultant+"
    }.get(lang, "📱 Открыть Consultant+")

    quick_btns = {
        "ru": [
            [{"text": "🏢 Квартиры (Freehold & FET)", "callback_data": "quick_condo"}, {"text": "🏡 Земля и виллы (Leasehold 30)", "callback_data": "quick_villa"}],
            [{"text": "💰 Налог на ввоз денег (P.161)", "callback_data": "quick_tax"}, {"text": "💼 Бизнес и компания 51/49", "callback_data": "quick_fba"}],
            [{"text": "⚖️ Выходное пособие (ст. 118)", "callback_data": "quick_labor"}, {"text": "🛂 Визы и Work Permit", "callback_data": "quick_visa"}]
        ],
        "en": [
            [{"text": "🏢 Condo (49% Freehold)", "callback_data": "quick_condo"}, {"text": "🏡 Land & Villa (30-Yr Lease)", "callback_data": "quick_villa"}],
            [{"text": "💰 Tax Remittance (P.161)", "callback_data": "quick_tax"}, {"text": "💼 Business & Nominee (FBA)", "callback_data": "quick_fba"}],
            [{"text": "⚖️ Labor & Severance (LPA 118)", "callback_data": "quick_labor"}, {"text": "🛂 Visas & Work Permit", "callback_data": "quick_visa"}]
        ],
        "th": [
            [{"text": "🏢 ห้องชุด (โควตา 49% Freehold)", "callback_data": "quick_condo"}, {"text": "🏡 ที่ดินและวิลล่า (Leasehold 30 ปี)", "callback_data": "quick_villa"}],
            [{"text": "💰 ภาษีเงินได้ต่างประเทศ (ป.161)", "callback_data": "quick_tax"}, {"text": "💼 บริษัทและความเสี่ยง Nominee", "callback_data": "quick_fba"}],
            [{"text": "⚖️ ค่าชดเชยการเลิกจ้าง (ม.118)", "callback_data": "quick_labor"}, {"text": "🛂 วีซ่าและ Work Permit", "callback_data": "quick_visa"}]
        ],
        "zh": [
            [{"text": "🏢 公寓大厦（49%永久产权）", "callback_data": "quick_condo"}, {"text": "🏡 土地与别墅（30年租赁权）", "callback_data": "quick_villa"}],
            [{"text": "💰 境外所得纳税（P.161号令）", "callback_data": "quick_tax"}, {"text": "💼 合资企业与代持刑事风险", "callback_data": "quick_fba"}],
            [{"text": "⚖️ 辞退员工补偿（LPA第118条）", "callback_data": "quick_labor"}, {"text": "🛂 工作证与LTR签证", "callback_data": "quick_visa"}]
        ]
    }.get(lang, [])

    keyboard = {
        "inline_keyboard": [
            [{"text": app_btn_label, "web_app": {"url": MINI_APP_URL}}],
            [
                {"text": "🇬🇧 English", "callback_data": "set_lang_en"},
                {"text": "🇹🇭 ภาษาไทย", "callback_data": "set_lang_th"},
                {"text": "🇷🇺 Русский", "callback_data": "set_lang_ru"},
                {"text": "🇨🇳 中文", "callback_data": "set_lang_zh"}
            ],
            *quick_btns
        ]
    }
    send_message(chat_id, text, reply_markup=keyboard)
    
    # 2. Also send/activate persistent bottom reply keyboard
    quick_bar_text = {
        "ru": "⚡ *Быстрый доступ закреплен в нижней панели и меню слева ⬇️*",
        "en": "⚡ *Quick access is pinned to your keyboard bar & menu below ⬇️*",
        "th": "⚡ *เข้าถึงด่วนผ่านแป้นพิมพ์และเมนูด้านล่าง ⬇️*",
        "zh": "⚡ *快捷操作已置顶在您的键盘底栏与左下角菜单 ⬇️*"
    }.get(lang, "⚡ *Быстрый доступ закреплен в нижней панели и меню слева ⬇️*")
    
    send_message(chat_id, quick_bar_text, reply_markup=get_persistent_reply_keyboard(lang))

def query_rag_backend(query: str, user_id: str, session_id: str, lang: str = "en") -> Dict[str, Any]:
    try:
        resp = http_session.post(
            f"{BACKEND_URL}/api/chat",
            json={
                "user_id": user_id,
                "query": query,
                "lang": lang,
                "user_role": "client",
                "jurisdiction": "Thailand",
                "session_id": session_id
            },
            timeout=(5.0, 35.0)
        )
        if resp.status_code == 200:
            return resp.json()
        logger.error(f"Backend error {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.error(f"Error querying backend: {e}")
    return {}

def process_query_and_reply(chat_id: int, user_id: str, query_text: str, first_name: str):
    send_chat_action(chat_id, "typing")
    
    nid = normalize_id(user_id)
    lang = get_user_lang(nid)
    session_id = get_or_create_user_session(nid)

    data = query_rag_backend(query_text, user_id=nid, session_id=session_id, lang=lang)
    if not data:
        err_msg = {
            "en": "⚠️ The legal consultation engine is momentarily syncing updates. Please retry in one minute.",
            "th": "⚠️ ระบบกำลังประมวลผลการอัปเดตข้อมูลกฎหมาย กรุณาลองใหม่อีกครั้งใน 1 นาทีครับ",
            "ru": "⚠️ Сервер консультаций временно обрабатывает обновление базы. Пожалуйста, повторите запрос через минуту.",
            "zh": "⚠️ 法律咨询引擎正在同步最新法规数据，请稍候一分钟后重试。"
        }.get(lang, "⚠️ Сервер консультаций временно обрабатывает обновление базы. Пожалуйста, повторите запрос через минуту.")
        send_message(chat_id, err_msg)
        return
        
    answer = data.get("answer", "")
    clarifications = data.get("proactive_clarifications", [])
    user_clarifications[chat_id] = clarifications
    resp_lang = data.get("lang", lang or "en")
    user_langs[nid] = resp_lang

    # Highlight related past case if present
    related = data.get("related_case")
    if related:
        hint_text = related.get("hint") or ""
        past_title = related.get("title") or ""
        prefix = f"💡 **Смежный кейс из вашего прошлого диалога «{past_title}»:**\n_{hint_text}_\n\n---\n\n"
        answer = prefix + answer
    
    # Append clean statute titles if present
    statutes = data.get("statutory_references", [])
    if statutes:
        header = {
            "ru": "\n\n📜 **Нормативно-правовая база:**\n",
            "en": "\n\n📜 **Governing Statutory Provisions:**\n",
            "th": "\n\n📜 **บทบัญญัติกฎหมายที่เกี่ยวข้อง:**\n",
            "zh": "\n\n📜 **核心法规依据：**\n"
        }.get(resp_lang, "\n\n📜 **Нормативно-правовая база:**\n")
        
        statute_lines = []
        for s in statutes[:3]:
            title = s.get("title") or ""
            sec = s.get("section_num") or ""
            if title:
                statute_lines.append(f"• **{title}**" + (f" — _{sec}_" if sec else ""))
        if statute_lines:
            answer += header + "\n".join(statute_lines)
    
    keyboard = build_clarification_keyboard(clarifications, lang=resp_lang)
    send_message(chat_id, answer, reply_markup=keyboard)

def main():
    logger.info("Starting Telegram Poller v6.0-PROD for @ThaiLawBot with resilient session pooling...")
    logger.info(f"Connected to backend at: {BACKEND_URL}")
    logger.info(f"Mini App URL set to: {MINI_APP_URL}")
    
    call_tg("deleteWebhook")
    
    # Global default chat menu button
    call_tg("setChatMenuButton", {
        "menu_button": {
            "type": "web_app",
            "text": "📱 Consultant+",
            "web_app": {"url": MINI_APP_URL}
        }
    })
    
    offset = 0
    last_heartbeat = time.time()
    
    while True:
        try:
            if time.time() - last_heartbeat > 60:
                logger.info(f"Poller heartbeat: active and listening (offset={offset})...")
                last_heartbeat = time.time()
                
            updates_res = call_tg("getUpdates", {"offset": offset, "timeout": 20}, timeout=25)
            if not updates_res.get("ok"):
                time.sleep(2)
                continue
                
            updates = updates_res.get("result", [])
            for u in updates:
                offset = max(offset, u["update_id"] + 1)
                
                # Handle Message
                if "message" in u:
                    msg = u["message"]
                    chat_id = msg.get("chat", {}).get("id")
                    text = msg.get("text", "").strip()
                    user = msg.get("from", {})
                    first_name = user.get("first_name", "User")
                    user_id = str(user.get("id", chat_id))
                    
                    if not text:
                        continue
                        
                    logger.info(f"Received message from {first_name} ({user_id}): {text[:50]}")
                    clean_lower = text.lower().strip()
                    
                    if clean_lower in ["/start", "/help", "start", "старт", "помощь"]:
                        handle_start(chat_id, user_id, first_name)
                    elif clean_lower in ["/calc", "/calculator", "калькулятор", "⚡ калькулятор", "⚡ экспресс-калькулятор", "calculator"]:
                        lang = get_user_lang(user_id)
                        calc_msg = {
                            "ru": "⚡ **Экспресс-калькулятор сделок и налогов Таиланда**\n\nВам доступны 5 интерактивных модулей:\n🏢 **Недвижимость**: Freehold vs Leasehold, сбор 2%, SBT 3.3%, Stamp 0.5%, WHT, FET\n💰 **Налог на доход**: правило 180 дней, P.161/162, шкала PIT 0-35%, DTA\n⚖️ **Выходное пособие**: ст. 118 LPA (от 30 до 400 дней зарплаты)\n💼 **Компания 51/49**: капитал и квота 4 тайца на 1 экспата, BOI\n🛂 **Подбор виз**: скоринг и расчет совпадения DTV, LTR, Elite, Non-B\n\nНажмите кнопку ниже для запуска в один клик:",
                            "en": "⚡ **Thai Legal and Tax Calculator**\n\n5 interactive modules for property closing costs, income remittance tax, severance pay, corporate quotas, and visa scoring.\n\nTap below to launch:"
                        }.get(lang, "⚡ **Экспресс-калькулятор сделок и налогов Таиланда**\n\nНажмите кнопку ниже для запуска:")
                        calc_kb = {
                            "inline_keyboard": [
                                [{"text": "⚡ Открыть калькулятор", "web_app": {"url": MINI_APP_URL + "#calculator"}}]
                            ]
                        }
                        send_message(chat_id, calc_msg, reply_markup=calc_kb)
                    elif clean_lower in ["/new", "новый диалог", "➕ новый диалог", "new dialogue", "new", "➕ new chat"]:
                        reset_user_session(user_id)
                        lang = get_user_lang(user_id)
                        resp_msg = {
                            "ru": "✅ **Начата новая юридическая консультация!**\nКонтекст прошлых бесед сохранен в вашем юридическом профиле. Задайте любой новый вопрос:",
                            "en": "✅ **New legal consultation session started!**\nPrior case history is preserved in your legal profile. What legal matter would you like to explore?",
                            "th": "✅ **เปิดบทสนทนาการปรึกษาใหม่เรียบร้อยแล้วครับ!**\nข้อมูลประวัติการปรึกษาก่อนหน้ายังคงถูกบันทึกในโปรไฟล์ของท่าน กรุณาพิมพ์คำถามที่ต้องการปรึกษาครับ:",
                            "zh": "✅ **已为您开启全新法律咨询会话！**\n先前的咨询背景已安全留存在您的案情档案中。请问有什么新的法律事项需要咨询？"
                        }.get(lang, "✅ **Начата новая юридическая консультация!**\nЗадайте вопрос:")
                        send_message(chat_id, resp_msg, reply_markup=get_persistent_reply_keyboard(lang))
                    elif clean_lower in ["/lang", "language", "язык", "ภาษา"]:
                        kb = {
                            "inline_keyboard": [
                                [
                                    {"text": "🇬🇧 English", "callback_data": "set_lang_en"},
                                    {"text": "🇹🇭 ภาษาไทย", "callback_data": "set_lang_th"}
                                ],
                                [
                                    {"text": "🇷🇺 Русский", "callback_data": "set_lang_ru"},
                                    {"text": "🇨🇳 中文", "callback_data": "set_lang_zh"}
                                ]
                            ]
                        }
                        send_message(chat_id, "Please choose your preferred language / กรุณาเลือกภาษา / Выберите язык / 请选择语言:", reply_markup=kb)
                    else:
                        process_query_and_reply(chat_id, user_id, text, first_name)
                        
                # Handle Callback Query (Button clicks)
                elif "callback_query" in u:
                    cq = u["callback_query"]
                    cb_id = cq.get("id")
                    cb_data = cq.get("data", "")
                    from_user = cq.get("from", {})
                    chat_id = cq.get("message", {}).get("chat", {}).get("id")
                    first_name = from_user.get("first_name", "User")
                    user_id = str(from_user.get("id", chat_id))
                    
                    call_tg("answerCallbackQuery", {"callback_query_id": cb_id})
                    logger.info(f"Callback from {first_name}: {cb_data}")

                    if cb_data == "cmd_new_dialog":
                        reset_user_session(user_id)
                        lang = get_user_lang(user_id)
                        resp_msg = {
                            "ru": "✅ **Открыт новый диалог!** Задайте интересующий вас вопрос по праву Таиланда:",
                            "en": "✅ **New consultation opened!** Ask your question regarding Thai law:",
                            "th": "✅ **เปิดบทสนทนาใหม่แล้วครับ!** พิมพ์คำถามทางกฎหมายได้ทันทีครับ:",
                            "zh": "✅ **已成功开启新会话！** 请输入您关心的泰王国法律议题："
                        }.get(lang, "✅ **Открыт новый диалог!**")
                        send_message(chat_id, resp_msg, reply_markup=get_persistent_reply_keyboard(lang))
                        continue

                    if cb_data.startswith("set_lang_"):
                        new_lang = cb_data.replace("set_lang_", "")
                        if new_lang in ["en", "th", "ru", "zh"]:
                            sync_user_lang_to_backend(user_id, new_lang)
                            confirms = {
                                "en": "🇬🇧 Language set to **English**. How can I assist you with Thai law today?",
                                "th": "🇹🇭 ตั้งค่าภาษาเป็น **ภาษาไทย** เรียบร้อยแล้วครับ มีประเด็นกฎหมายใดที่ต้องการปรึกษาครับ?",
                                "ru": "🇷🇺 Язык переключен на **Русский**. Какой юридический вопрос по Таиланду вас интересует?",
                                "zh": "🇨🇳 语言已成功切换为 **中文**。请问有什么泰王国法律问题需要为您解答？"
                            }
                            send_message(chat_id, confirms.get(new_lang, confirms["en"]))
                            handle_start(chat_id, user_id, first_name)
                            continue
                    
                    cur_lang = get_user_lang(user_id)
                    quick_queries = {
                        "en": {
                            "quick_condo": "Can a foreigner purchase 100% freehold of a condominium under the 49% quota and what are the FET requirements?",
                            "quick_villa": "How can a foreign national legally register a 30-year Leasehold for land and villa in Thailand?",
                            "quick_tax": "Are foreign earnings remitted into Thailand subject to personal income tax under RD Orders P.161 and P.162?",
                            "quick_fba": "What are the rules and criminal penalties for nominee shareholders in a 51/49 Thai company under FBA Section 36?",
                            "quick_labor": "What are the mandatory severance scales when dismissing an employee under LPA Section 118?",
                            "quick_visa": "What are the requirements and employee ratios for getting a Digital Work Permit and LTR Visa?"
                        },
                        "th": {
                            "quick_condo": "คนต่างด้าวสามารถซื้อห้องชุดในโควตาคนต่างด้าว 49% (Freehold) 100% ได้อย่างไร และต้องใช้แบบรับรอง FET หรือไม่?",
                            "quick_villa": "คนต่างด้าวจะจดทะเบียนสิทธิการเช่าระยะยาว 30 ปี (Leasehold) สำหรับที่ดินและวิลล่าได้อย่างไร?",
                            "quick_tax": "เงินได้จากต่างประเทศที่นำเข้ามาในไทยต้องเสียภาษีเงินได้บุคคลธรรมดาตามคำสั่ง ป.161 และ ป.162 หรือไม่?",
                            "quick_fba": "หลักเกณฑ์และโทษทางอาญาเกี่ยวกับการใช้ตัวแทนถือหุ้นแทน (Nominee) ตาม พ.ร.บ.การประกอบธุรกิจของคนต่างด้าว มาตรา 36 มีอะไรบ้าง?",
                            "quick_labor": "อัตราค่าชดเชยการเลิกจ้างตามอายุงานตามมาตรา 118 แห่ง พ.ร.บ.คุ้มครองแรงงาน มีเกณฑ์อย่างไร?",
                            "quick_visa": "เงื่อนไขการขอใบอนุญาตทำงาน Work Permit และสิทธิประโยชน์ของวีซ่า LTR 10 ปี มีอะไรบ้าง?"
                        },
                        "ru": {
                            "quick_condo": "Может ли иностранец купить квартиру в кондоминиуме в 100% собственность (Freehold 49%) и какие документы нужны?",
                            "quick_villa": "Как иностранцу законно оформить землю и виллу через долгосрочную аренду Leasehold на 30 лет?",
                            "quick_tax": "Облагаются ли налогом в Таиланде переводы личных средств и сбережений из-за рубежа по распоряжениям RD P.161 и P.162?",
                            "quick_fba": "Какие правила и риски при открытии компании 51% тайских партнеров и 49% иностранных по закону FBA?",
                            "quick_labor": "Каков точный размер выходного пособия при увольнении сотрудника по трудовому закону LPA ст. 118?",
                            "quick_visa": "Какие требования и соотношение сотрудников для получения Work Permit и 10-летней визы LTR?"
                        },
                        "zh": {
                            "quick_condo": "外籍人士如何依法取得泰国公寓大厦49%永久产权（Foreign Freehold）并开具FET外汇核准函？",
                            "quick_villa": "外籍人士如何通过30年法定登记租赁权（Leasehold）及地上权合规持有泰国土地与别墅？",
                            "quick_tax": "根据泰国税务局P.161及P.162号令，汇入泰国的境外个人所得应如何依法纳税？",
                            "quick_fba": "依《外籍商法》设立51/49合资企业有哪些合规要点？名义代持（Nominee，第36条）面临何种刑事处罚？",
                            "quick_labor": "依据《劳动保护法》第118条，辞退无过错员工各工龄梯队法定遣散补偿金核算标准？",
                            "quick_visa": "外籍雇员办理Digital Work Permit工作证的注册资本配比及10年期LTR签证申请要件？"
                        }
                    }
                    
                    lang_dict = quick_queries.get(cur_lang, quick_queries["ru"])
                    
                    if cb_data in lang_dict:
                        process_query_and_reply(chat_id, user_id, lang_dict[cb_data], first_name)
                    elif cb_data.startswith("clarify_"):
                        try:
                            idx = int(cb_data.split("_")[1])
                            saved = user_clarifications.get(chat_id, [])
                            if 0 <= idx < len(saved):
                                clarify_text = saved[idx]
                                process_query_and_reply(chat_id, user_id, clarify_text, first_name)
                        except Exception as e:
                            logger.error(f"Error handling clarification click: {e}")
                            
        except Exception as e:
            logger.error(f"Polling loop error: {e}")
            time.sleep(2)

if __name__ == "__main__":
    main()
