#!/usr/bin/env python3

# indexer/index_to_qdrant.py

import os
import json
import uuid
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.http.models import VectorParams, Distance, PointStruct
from sentence_transformers import SentenceTransformer

QDRANT_URL = os.getenv("QDRANT_URL", "http://thai-qdrant:6333")
COL = os.getenv("QDRANT_COLLECTION", "thai_law")
EMBED_MODEL = os.getenv(
    "EMBED_MODEL", "VISAI-AI/nitibench-ccl-human-finetuned-bge-m3"
)
PROCESSED = os.getenv("PROCESSED_DIR", "/app/data/processed")

client = QdrantClient(url=QDRANT_URL)

# 1. Создаём коллекцию, если её ещё нет (без recreate_collection)
if COL not in [c.name for c in client.get_collections().collections]:
    client.recreate_collection(
        collection_name=COL,
        vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
    )

model = SentenceTransformer(EMBED_MODEL)

for fn in Path(PROCESSED).glob("*.processed.json"):
    with open(fn, "r", encoding="utf-8") as f:
        doc = json.load(f)

    meta = doc.get("meta", {})
    chunks = doc.get("chunks", [])

    doc_id = Path(fn).stem  # например, ocs_law_1.processed
    vecs = []
    payloads = []
    ids = []

    for c in chunks:
        txt = c.get("text", "")
        if not txt.strip():
            continue

        vec = model.encode(txt)
        vecs.append(vec.tolist())

        chunk_id = c.get("chunk_id")
        # детерминированный ID: doc_id + chunk_id
        point_uuid = uuid.uuid5(
            uuid.NAMESPACE_URL, f"{doc_id}:{chunk_id}"
        )
        ids.append(str(point_uuid))

        payloads.append(
            {
                "source_url": meta.get("url"),
                "doc_id": doc_id,
                "chunk_id": chunk_id,
                "text": txt[:4000],
                "fetched_at": meta.get("fetched_at"),
            }
        )

    if vecs:
        points = [
            PointStruct(id=i, vector=v, payload=p)
            for i, v, p in zip(ids, vecs, payloads)
        ]
        client.upsert(collection_name=COL, points=points)
        print("Indexed", fn)
