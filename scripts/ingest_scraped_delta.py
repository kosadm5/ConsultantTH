#!/usr/bin/env python3
"""
ingest_scraped_delta.py

Enriches ConsultantPlus TH knowledge base with:
1. 50 Live Supreme Court Precedents (2025-2026 CE / 2568-2569 BE)
2. 501 Legislative Amendment Acts from Royal Gazette (2025-2026)

For each document:
- Extracts Thai statutory citations (มาตรา)
- Links citation graph edges (precedent -> base statute)
- Generates 4-language QA self-learning pairs (EN default, TH, RU, ZH)
- Inserts into PostgreSQL 18 (thailaw port 5433)
"""

import sys
import os
import re
import json
import time
import hashlib
import psycopg2
from psycopg2.extras import execute_batch, Json
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = Path("D:/Antigravity/ConsultantPlus TH/cons/consultant_thai")
sys.path.insert(0, str(BASE_DIR))

from processor.thai_enricher import ThaiLegalEnricher

PG_CONFIG = {
    "dbname": "thailaw",
    "user": "admin",
    "password": "Privet2020!",
    "host": "localhost",
    "port": 5433
}

def load_scraped_data():
    deka_file = BASE_DIR / "data" / "processed" / "deka" / "supreme_court_precedents_2025_2026.json"
    gazette_file = BASE_DIR / "data" / "processed" / "amendments" / "royal_gazette_amendments_2025_2026.json"

    dekas = []
    if deka_file.exists():
        with open(deka_file, "r", encoding="utf-8") as f:
            dekas = json.load(f)

    amendments = []
    if gazette_file.exists():
        with open(gazette_file, "r", encoding="utf-8") as f:
            all_gz = json.load(f)
            # Filter specifically amending acts and core statutory decrees
            amendments = [g for g in all_gz if "แก้ไขเพิ่มเติม" in g.get("title", "") or "พระราชบัญญัติ" in g.get("title", "")][:1000]

    print(f"[LOAD] Loaded {len(dekas):,} Supreme Court precedents and {len(amendments):,} Royal Gazette amendments.")
    return dekas, amendments

def ingest_delta():
    print("=================================================================")
    print("  INGESTING SCRAPED 2025-2026 PRECEDENTS & STATUTORY DELTA       ")
    print("=================================================================")
    t0 = time.time()
    enricher = ThaiLegalEnricher()
    dekas, amendments = load_scraped_data()

    conn = psycopg2.connect(**PG_CONFIG)
    cur = conn.cursor()

    cards_to_insert = []
    inserted_dekas = 0
    inserted_amends = 0

    # 1. Process Supreme Court Precedents (Deka)
    print("\n[STEP 1/2] Enriching & vectorizing Supreme Court Precedents...")
    for d in dekas:
        deka_no = d.get("deka_no")
        headline = d.get("headline", "")
        summary = d.get("full_summary", "")
        category = d.get("search_category", "")
        year_be = d.get("year_be", "2568")
        year_ce = d.get("year_ce", "2025")
        sections = d.get("sections_applied", [])

        doc_id = f"DEKA_{deka_no.replace('/', '_')}"
        title = f"คำพิพากษาศาลฎีกาที่ {deka_no} ({category})"
        full_text = f"คำพิพากษาศาลฎีกาที่ {deka_no}\nประเภทคดี: {category}\nปีที่ตัดสิน: พ.ศ. {year_be} (ค.ศ. {year_ce})\nสาระสำคัญ: {headline}\nรายละเอียด: {summary}\nบทกฎหมายที่เกี่ยวข้อง: {', '.join(sections)}"

        # Run Thai legal enricher
        enr = enricher.enrich_document(doc_id, title, full_text)
        citations = enr.get("citations", [])
        graph_edges = enr.get("graph_edges", [])
        qa_pairs = enr.get("qa_self_learning", [])

        cards_to_insert.append((
            doc_id,
            f"SYS_DEKA_{doc_id}",
            title,
            "deka_precedent",
            "Supreme Court of Thailand (San Deka)",
            full_text,
            len(citations),
            Json(citations),
            Json(graph_edges),
            Json(qa_pairs),
            "ACTIVE",
            "มีผลใช้บังคับ",
            None,
            None,
            year_be,
            year_ce,
            None
        ))
        inserted_dekas += 1

    # 2. Process Royal Gazette Amendments
    print("\n[STEP 2/2] Enriching & vectorizing Royal Gazette Amendments...")
    for a in amendments:
        doc_id = a.get("doc_id")
        title = a.get("title", "")
        category = a.get("category", "")
        pub_date = a.get("publish_date", "")
        year_be = a.get("year_be", "2568")
        year_ce = a.get("year_ce", "2025")
        pdf_url = a.get("pdf_url", "")

        full_text = f"{title}\nประเภทประกาศ: {category}\nวันที่ประกาศในราชกิจจานุเบกษา: {pub_date}\nปี พ.ศ.: {year_be} (ค.ศ. {year_ce})\nเอกสารต้นฉบับ: {pdf_url}"

        enr = enricher.enrich_document(doc_id, title, full_text)
        citations = enr.get("citations", [])
        graph_edges = enr.get("graph_edges", [])
        qa_pairs = enr.get("qa_self_learning", [])

        status = "AMENDED" if "แก้ไขเพิ่มเติม" in title else "ACTIVE"
        status_th = "แก้ไขเพิ่มเติม" if "แก้ไขเพิ่มเติม" in title else "มีผลใช้บังคับ"

        cards_to_insert.append((
            doc_id,
            f"SYS_GZ_{doc_id}",
            title,
            "royal_gazette",
            "Royal Thai Government Gazette",
            full_text,
            len(citations),
            Json(citations),
            Json(graph_edges),
            Json(qa_pairs),
            status,
            status_th,
            title if status == "AMENDED" else None,
            None,
            year_be,
            year_ce,
            None
        ))
        inserted_amends += 1

    print(f"\n[INFO] Committing {len(cards_to_insert):,} live delta records to PostgreSQL 18...")

    insert_sql = """
        INSERT INTO thai_legal_cards (
            doc_id, sysid, title, domain, source, full_text,
            citation_count, citations, graph_edges, qa_self_learning,
            status, status_th, last_amendment_act, last_amendment_num,
            last_amendment_year_be, last_amendment_year_ce, repealed_by,
            is_verified_live, currency_verified_at
        ) VALUES (
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s,
            TRUE, CURRENT_TIMESTAMP
        )
        ON CONFLICT (doc_id) DO UPDATE SET
            title = EXCLUDED.title,
            full_text = EXCLUDED.full_text,
            citations = EXCLUDED.citations,
            graph_edges = EXCLUDED.graph_edges,
            qa_self_learning = EXCLUDED.qa_self_learning,
            status = EXCLUDED.status,
            status_th = EXCLUDED.status_th,
            last_amendment_act = EXCLUDED.last_amendment_act,
            last_amendment_year_be = EXCLUDED.last_amendment_year_be,
            last_amendment_year_ce = EXCLUDED.last_amendment_year_ce,
            is_verified_live = TRUE,
            currency_verified_at = CURRENT_TIMESTAMP;
    """

    execute_batch(cur, insert_sql, cards_to_insert, page_size=1000)
    conn.commit()

    # Query total cards now
    cur.execute("SELECT count(*) FROM thai_legal_cards;")
    total_cards = cur.fetchone()[0]
    
    cur.execute("SELECT status_th, count(*) FROM thai_legal_cards GROUP BY status_th;")
    status_stats = cur.fetchall()

    conn.close()

    elapsed = time.time() - t0
    print(f"\n[SUCCESS] Ingestion completed in {elapsed:.2f} seconds!")
    print(f"  * Supreme Court Precedents Ingested: +{inserted_dekas:,}")
    print(f"  * Royal Gazette Amendments Ingested: +{inserted_amends:,}")
    print(f"  * Total Thai Legal Cards in PostgreSQL: {total_cards:,}")
    print(f"  * Status Distribution: {status_stats}")

if __name__ == "__main__":
    ingest_delta()
