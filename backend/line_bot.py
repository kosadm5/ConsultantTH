# backend/line_bot.py
from fastapi import FastAPI, Request, Header
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
import requests

app = FastAPI()

LINE_TOKEN = os.getenv("LINE_CHANNEL_TOKEN")
LINE_SECRET = os.getenv("LINE_CHANNEL_SECRET")
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")

line_api = LineBotApi(LINE_TOKEN)
handler = WebhookHandler(LINE_SECRET)

@app.post("/line/webhook")
async def webhook(req: Request, x_line_signature: str = Header(None)):
    body = await req.json()
    for ev in body.get("events", []):
        if ev["type"] == "message" and ev["message"]["type"] == "text":
            user_text = ev["message"]["text"]
            reply_token = ev["replyToken"]
            # отправляем запрос в /query
            r = requests.post(f"{BACKEND_URL}/query", json={"query": user_text}, timeout=120)
            data = r.json()
            answer = data.get("text", "ขออภัย เกิดข้อผิดพลาดในการประมวลผล")
            line_api.reply_message(reply_token, TextSendMessage(text=answer))
    return "OK"
