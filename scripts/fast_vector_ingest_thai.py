#!/usr/bin/env python3
"""
fast_vector_ingest_thai.py

Ingests dense embeddings into Qdrant (port 6433) on CPU using FastEmbed:
- Model: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 (384 dims)
- Collections: thai_legal_cards, thai_legal_chunks
- Prioritizes: Core statutory codes, 2024-2026 amendments, Supreme Court Deka precedents
- 100% CPU isolated (ZERO GPU VRAM impact on the RF pipeline)
"""

import sys
import os
import time
import json
import uuid
import urllib.request
import psycopg2
from pathlib import Path
from fastembed import TextEmbedding

sys.stdout.reconfigure(encoding='utf-8')

PG_CONFIG = {
    "dbname": "thailaw",
    "user": "admin",
    "password": "Privet2020!",
    "host": "localhost",
    "port": 5433
}

QDRANT_URL = "http://localhost:6433"

def to_uuid(s: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, s))

def main():
    print("=================================================================")
    print("  CONSULTANTPLUS TH - FAST CPU VECTOR INGESTION INTO QDRANT      ")
    print("=================================================================")
    t0 = time.time()

    # 1. Load embedding model
    print("[STEP 1/3] Initializing FastEmbed multilingual model on CPU...")
    embed_model = TextEmbedding(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")

    # 2. Fetch cards from PostgreSQL
    print("[STEP 2/3] Fetching key statutes and precedents from PostgreSQL...")
    conn = psycopg2.connect(**PG_CONFIG)
    cur = conn.cursor()
    
    # Prioritize pillars, amendments, deka precedents, and core statutory acts
    cur.execute("""
        SELECT doc_id, title, domain, status, status_th, last_amendment_act,
               last_amendment_year_be, repealed_by, full_text
        FROM thai_legal_cards
        ORDER BY 
            CASE 
                WHEN doc_id LIKE 'TH_%' THEN 1
                WHEN domain = 'deka_precedent' THEN 2
                WHEN status_th = 'แก้ไขเพิ่มเติม' THEN 3
                ELSE 4 
            END,
            doc_id ASC
        LIMIT 3000;
    """)
    rows = cur.fetchall()
    conn.close()
    print(f"[INFO] Selected {len(rows):,} high-priority legal documents to vectorize...")

    # 3. Batch embed and upload to Qdrant
    print("[STEP 3/3] Vectorizing and uploading points to Qdrant (port 6433)...")
    batch_size = 64
    total_uploaded = 0

    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        texts_to_embed = []
        points = []

        for r in batch:
            doc_id, title, domain, status, status_th, last_act, last_be, repealed, full_text = r
            # Combine title and snippet for optimal semantic matching
            embed_text = f"{title}. {full_text[:400]}"
            texts_to_embed.append(embed_text)

        # CPU embedding
        vectors = list(embed_model.embed(texts_to_embed))

        for j, r in enumerate(batch):
            doc_id, title, domain, status, status_th, last_act, last_be, repealed, full_text = r
            vec = vectors[j].tolist()

            points.append({
                "id": to_uuid(doc_id),
                "vector": vec,
                "payload": {
                    "doc_id": doc_id,
                    "title": title,
                    "domain": domain,
                    "status": status,
                    "status_th": status_th,
                    "last_amendment_act": last_act,
                    "last_amendment_year_be": last_be,
                    "repealed_by": repealed,
                    "snippet": full_text[:500]
                }
            })

        # Upload to Qdrant
        req_data = json.dumps({"points": points}).encode("utf-8")
        req = urllib.request.Request(
            f"{QDRANT_URL}/collections/thai_legal_cards/points?wait=false",
            data=req_data,
            headers={"Content-Type": "application/json"},
            method="PUT"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            pass

        total_uploaded += len(points)
        if total_uploaded % 320 == 0 or total_uploaded == len(rows):
            print(f"  Uploaded {total_uploaded:,} / {len(rows):,} vectors ({(total_uploaded/len(rows))*100:.1f}%)")

    elapsed = time.time() - t0
    print("\n=================================================================")
    print(f"  QDRANT VECTOR INGESTION COMPLETE in {elapsed:.2f}s")
    print(f"  * Total Points Uploaded: {total_uploaded:,}")
    print(f"  * Collection: thai_legal_cards (384 dims, Cosine)")
    print("=================================================================")

if __name__ == "__main__":
    main()
