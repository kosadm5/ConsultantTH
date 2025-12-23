#!/usr/bin/env python3
# backend/app.py
from fastapi import FastAPI
import httpx
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
import os

app = FastAPI()

QDRANT = os.getenv("QDRANT_URL", "http://thai-qdrant:6333")
COL = os.getenv("QDRANT_COLLECTION", "thai_law")
EMBED_MODEL = os.getenv("EMBED_MODEL", "VISAI-AI/nitibench-ccl-human-finetuned-bge-m3")
INDEXER_URL = os.getenv("INDEXER_URL", "http://thai-indexer:8001/index")

embed_model = SentenceTransformer(EMBED_MODEL)
qclient = QdrantClient(url=QDRANT)

class Query(BaseModel):
    query: str
    top_k: int = 8

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/query")
def query(q: Query):
    vec = embed_model.encode(q.query).tolist()
    res = qclient.query_points(
        collection_name=COL,
        query=vec,
        limit=q.top_k,
    )
    hits = res.points

    contexts = [h.payload.get("text", "") for h in hits]
    sources = [
        {"url": h.payload.get("source_url"), "chunk_id": h.payload.get("chunk_id")}
        for h in hits
    ]

    return {"answer": "\n\n".join(contexts[:3]), "sources": sources}

class IndexRequest(BaseModel):
    filenames: list[str] | None = None

@app.post("/admin/index")
async def admin_index(req: IndexRequest):
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(INDEXER_URL, json=req.dict())
    return resp.json()