#!/usr/bin/env python3
# backend/telegram_bot.py
"""
Telegram Bot integration for Thai Law AI Assistant.
Handles incoming messages via webhook and responds using the RAG backend.
"""

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
import httpx
import os
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telegram", tags=["telegram"])

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# Request timeout for RAG queries (can be slow)
RAG_TIMEOUT = 180.0  # 3 minutes


class TelegramUpdate(BaseModel):
    """Simplified Telegram Update model"""
    update_id: int
    message: dict | None = None


async def send_telegram_message(chat_id: int, text: str, parse_mode: str = "Markdown"):
    """Send a message to Telegram chat"""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not configured")
        return False
    
    # Truncate long messages (Telegram limit is 4096 chars)
    if len(text) > 4000:
        text = text[:4000] + "\n\n... _(ข้อความถูกตัดเนื่องจากยาวเกินไป)_"
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{TELEGRAM_API_URL}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                }
            )
            if resp.status_code != 200:
                logger.error(f"Telegram API error: {resp.text}")
                return False
            return True
        except Exception as e:
            logger.error(f"Error sending Telegram message: {e}")
            return False


async def send_typing_action(chat_id: int):
    """Send typing indicator to show the bot is processing"""
    if not TELEGRAM_BOT_TOKEN:
        return
    
    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                f"{TELEGRAM_API_URL}/sendChatAction",
                json={"chat_id": chat_id, "action": "typing"}
            )
        except Exception:
            pass  # Non-critical, ignore errors


def format_response(text: str, sources: list) -> str:
    """Format the RAG response for Telegram"""
    response = text
    
    # Add sources if available
    if sources:
        source_links = []
        for s in sources[:3]:  # Limit to 3 sources
            doc_id = s.get("doc_id", "")
            if doc_id:
                source_links.append(f"• {doc_id}")
        
        if source_links:
            response += "\n\n📚 *แหล่งอ้างอิง / Sources:*\n" + "\n".join(source_links)
    
    return response


@router.post("/webhook")
async def telegram_webhook(request: Request):
    """
    Handle incoming Telegram webhook updates.
    Set webhook URL via Telegram API:
    https://api.telegram.org/bot<TOKEN>/setWebhook?url=<YOUR_URL>/telegram/webhook
    """
    if not TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=500, detail="Telegram bot not configured")
    
    try:
        body = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse webhook body: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    # Extract message data
    message = body.get("message")
    if not message:
        # Could be an edit, callback, etc. - acknowledge but don't process
        return {"ok": True}
    
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")
    user = message.get("from", {})
    username = user.get("username", user.get("first_name", "User"))
    
    if not chat_id or not text:
        return {"ok": True}
    
    # Handle /start command
    if text.startswith("/start"):
        welcome = (
            "🏛️ *สวัสดีครับ! ยินดีต้อนรับสู่ Thai Law AI Assistant*\n\n"
            "ผมคือผู้ช่วย AI ด้านกฎหมายไทย พร้อมช่วยตอบคำถามเกี่ยวกับกฎหมายครับ\n\n"
            "_Hello! I'm your Thai Law AI Assistant. Ask me any questions about Thai law in Thai, English, Russian, German, or French._\n\n"
            "💬 ส่งคำถามมาได้เลยครับ!"
        )
        await send_telegram_message(chat_id, welcome)
        return {"ok": True}
    
    # Handle /help command
    if text.startswith("/help"):
        help_text = (
            "📋 *วิธีใช้งาน / How to Use*\n\n"
            "1. พิมพ์คำถามเกี่ยวกับกฎหมายไทย\n"
            "2. รอสักครู่ ผมจะค้นหาข้อมูลจากฐานข้อมูลกฎหมาย\n"
            "3. ได้รับคำตอบพร้อมแหล่งอ้างอิง\n\n"
            "_Type your question about Thai law in any supported language._\n\n"
            "⚠️ _คำเตือน: ข้อมูลนี้เป็นการให้คำปรึกษาเบื้องต้น กรุณาปรึกษาทนายความสำหรับกรณีที่ซับซ้อน_"
        )
        await send_telegram_message(chat_id, help_text)
        return {"ok": True}
    
    # Process user query
    logger.info(f"Processing query from {username}: {text[:50]}...")
    
    # Send typing indicator
    await send_typing_action(chat_id)
    
    try:
        async with httpx.AsyncClient(timeout=RAG_TIMEOUT) as client:
            resp = await client.post(
                f"{BACKEND_URL}/query",
                json={"query": text}
            )
            
            if resp.status_code != 200:
                await send_telegram_message(
                    chat_id, 
                    "❌ ขออภัย เกิดข้อผิดพลาดในการประมวลผล กรุณาลองใหม่อีกครั้ง"
                )
                return {"ok": True}
            
            data = resp.json()
            answer_text = data.get("text", "ไม่สามารถสร้างคำตอบได้")
            sources = data.get("sources", [])
            
            formatted_response = format_response(answer_text, sources)
            await send_telegram_message(chat_id, formatted_response)
            
    except httpx.TimeoutException:
        await send_telegram_message(
            chat_id,
            "⏱️ ขออภัย การประมวลผลใช้เวลานานเกินไป กรุณาลองใหม่อีกครั้ง\n\n"
            "_Sorry, the request timed out. Please try again._"
        )
    except Exception as e:
        logger.error(f"Error processing Telegram message: {e}")
        await send_telegram_message(
            chat_id,
            "❌ เกิดข้อผิดพลาด กรุณาลองใหม่อีกครั้ง"
        )
    
    return {"ok": True}


@router.get("/health")
async def telegram_health():
    """Check Telegram bot health"""
    return {
        "status": "ok",
        "bot_configured": bool(TELEGRAM_BOT_TOKEN),
    }
