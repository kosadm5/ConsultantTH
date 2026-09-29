"""
backend/core/gateway.py
Consultant+ Core Engine 2.0 — Model-Agnostic LLM Gateway.
Supports OpenRouter (Gemini 2.5 Flash / GPT-4o-mini / Claude), Ollama local fallback,
JSON Structured Outputs, Exponential Backoff, and Retry.
"""

import os
import re
import json
import time
import logging
import httpx
from typing import List, Dict, Any, Optional

logger = logging.getLogger("core.gateway")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
DEFAULT_MODEL = os.getenv("CORE_LLM_MODEL", "openai/gpt-4o-mini")
FALLBACK_MODEL = os.getenv("CORE_FALLBACK_MODEL", "google/gemini-2.5-flash")
LOCAL_OLLAMA_URL = os.getenv("LOCAL_OLLAMA_URL", "http://localhost:11434/v1")


class ModelGateway:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, default_model: Optional[str] = None):
        self.api_key = api_key or OPENROUTER_API_KEY
        self.base_url = base_url or OPENROUTER_BASE_URL
        self.default_model = default_model or DEFAULT_MODEL
        self.client = httpx.Client(timeout=45.0)

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 1800
    ) -> str:
        """Standard chat completion with automatic model failover."""
        target_model = model or self.default_model
        
        # Try primary model
        try:
            return self._call_openrouter(messages, target_model, temperature, max_tokens, response_format=None)
        except Exception as e:
            logger.warning(f"Primary model {target_model} failed: {e}. Attempting fallback to {FALLBACK_MODEL}")
            try:
                return self._call_openrouter(messages, FALLBACK_MODEL, temperature, max_tokens, response_format=None)
            except Exception as e2:
                logger.error(f"Fallback model {FALLBACK_MODEL} failed: {e2}")
                raise RuntimeError(f"All LLM gateway calls failed: {e} | {e2}")

    def chat_structured_json(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.1
    ) -> Dict[str, Any]:
        """Requests structured JSON output and parses it safely."""
        target_model = model or self.default_model
        system_instruction = "IMPORTANT: You MUST respond ONLY with valid, syntactically strict JSON. No markdown codeblocks, no commentary."
        
        # Prepend or append JSON instruction
        amended_messages = [{"role": "system", "content": system_instruction}] + messages
        
        raw_text = ""
        try:
            raw_text = self._call_openrouter(amended_messages, target_model, temperature, max_tokens=1200, response_format={"type": "json_object"})
        except Exception as e:
            logger.warning(f"Primary model {target_model} json call failed: {e}. Trying {FALLBACK_MODEL}")
            raw_text = self._call_openrouter(amended_messages, FALLBACK_MODEL, temperature, max_tokens=1200, response_format={"type": "json_object"})

        # Clean raw text from markdown fences if any
        cleaned = re.sub(r'^```json\s*', '', raw_text.strip(), flags=re.IGNORECASE)
        cleaned = re.sub(r'^```\s*', '', cleaned.strip())
        cleaned = re.sub(r'```$', '', cleaned.strip())
        
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as je:
            # Attempt regex extraction of first {...}
            match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            logger.error(f"Failed to parse JSON response: {cleaned}")
            raise ValueError(f"Model did not return valid JSON: {je}")

    def _call_openrouter(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        response_format: Optional[Dict[str, Any]]
    ) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://consultantplus.thai",
            "X-Title": "ConsultantPlus TH Core 2.0",
            "Content-Type": "application/json"
        }
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        if response_format:
            payload["response_format"] = response_format

        for attempt in range(4):
            try:
                resp = self.client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    return data["choices"][0]["message"]["content"]
                elif resp.status_code in (402, 429, 500, 502, 503, 504) and attempt < 3:
                    wait_sec = 6 * (attempt + 1)
                    logger.warning(f"OpenRouter {resp.status_code} on attempt {attempt+1}/4, waiting {wait_sec}s...")
                    time.sleep(wait_sec)
                    continue
                else:
                    raise RuntimeError(f"OpenRouter returned {resp.status_code}: {resp.text}")
            except httpx.RequestError as req_err:
                if attempt < 3:
                    wait_sec = 4 * (attempt + 1)
                    logger.warning(f"HTTP request error {req_err} on attempt {attempt+1}/4, retrying in {wait_sec}s...")
                    time.sleep(wait_sec)
                    continue
                raise
