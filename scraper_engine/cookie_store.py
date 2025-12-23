# cookie_store.py
import os, json
from typing import Dict, Optional

REDIS_URL = os.getenv("REDIS_URL", "")
FILE = os.getenv("COOKIE_STORE_FILE", "/data/cookies/cookies.json")

try:
    if REDIS_URL:
        import redis
        rcli = redis.from_url(REDIS_URL)
    else:
        rcli = None
except Exception:
    rcli = None

def save(host: str, cookies: Dict[str, str]):
    if rcli:
        rcli.hset("scraper:cookies", host, json.dumps(cookies, ensure_ascii=False))
    else:
        data = {}
        if os.path.exists(FILE):
            try:
                with open(FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        data[host] = cookies
        os.makedirs(os.path.dirname(FILE), exist_ok=True)
        with open(FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

def load(host: str) -> Optional[Dict[str,str]]:
    if rcli:
        v = rcli.hget("scraper:cookies", host)
        if not v:
            return None
        try:
            return json.loads(v)
        except Exception:
            return None
    else:
        if not os.path.exists(FILE):
            return None
        try:
            with open(FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get(host)
        except Exception:
            return None
