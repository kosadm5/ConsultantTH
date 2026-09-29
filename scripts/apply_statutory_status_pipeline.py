#!/usr/bin/env python3
"""
apply_statutory_status_pipeline.py

Enriches PostgreSQL 18 (thailaw on port 5433) with precise Thai statutory validity:
- status_th: 'มีผลใช้บังคับ' (Active), 'แก้ไขเพิ่มเติม' (Amended), 'ถูกยกเลิก' (Repealed)
- last_amendment_act: Full Thai title of amending act
- last_amendment_num: e.g. 'ฉบับที่ 24'
- last_amendment_year_be: e.g. '2567'
- last_amendment_year_ce: e.g. '2024'
- repealed_by: Repealing act if applicable
- currency_verified_at: Current timestamp
"""

import sys
import os
import re
import time
import psycopg2
from psycopg2.extras import execute_batch
from pathlib import Path

# Ensure UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

PG_CONFIG = {
    "dbname": "thailaw",
    "user": "admin",
    "password": "Privet2020!",
    "host": "localhost",
    "port": 5433
}

def ensure_columns(conn):
    with conn.cursor() as cur:
        cur.execute("""
            ALTER TABLE thai_legal_cards
            ADD COLUMN IF NOT EXISTS status_th VARCHAR(50) DEFAULT 'มีผลใช้บังคับ',
            ADD COLUMN IF NOT EXISTS last_amendment_act TEXT,
            ADD COLUMN IF NOT EXISTS last_amendment_num VARCHAR(50),
            ADD COLUMN IF NOT EXISTS last_amendment_year_be VARCHAR(10),
            ADD COLUMN IF NOT EXISTS last_amendment_year_ce VARCHAR(10),
            ADD COLUMN IF NOT EXISTS repealed_by TEXT,
            ADD COLUMN IF NOT EXISTS currency_verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
        """)
        conn.commit()
    print("[SUCCESS] Statutory status and amendment columns verified in PostgreSQL.")

def process_amendment_lineage(conn):
    print("[INFO] Fetching all legal cards to analyze statutory status and amendment lineage...")
    with conn.cursor() as cur:
        cur.execute("SELECT doc_id, title, full_text FROM thai_legal_cards;")
        rows = cur.fetchall()

    print(f"[INFO] Analyzing {len(rows):,} legal cards...")
    
    # 1. Identify all amending acts ("แก้ไขเพิ่มเติม", "ฉบับที่")
    amendment_pattern = re.compile(r'แก้ไขเพิ่มเติม.*?(?:ฉบับที่\s*(\d+))?.*?พ\.ศ\.\s*(\d{4})', re.IGNORECASE)
    base_law_pattern = re.compile(r'^(พระราชบัญญัติ|ประมวลกฎหมาย|พระราชกำหนด|กฎกระทรวง)(.*?)(?:\(ฉบับที่|\s+พ\.ศ\.)', re.IGNORECASE)
    repeal_pattern = re.compile(r'(?:ให้ยกเลิก|ยกเลิกพระราชบัญญัติ|ถูกยกเลิกโดย)\s*([^\n\r]+)', re.IGNORECASE)

    # Index amending acts by base law name
    amendments_by_base = {}
    repeals = {}

    for doc_id, title, text in rows:
        title = title or ""
        text = text or ""
        
        # Check if this card itself is an amending act
        m_amend = amendment_pattern.search(title)
        if m_amend:
            # Extract base law name
            m_base = base_law_pattern.search(title)
            if m_base:
                base_name = (m_base.group(1) + m_base.group(2)).strip()
                edition = m_amend.group(1) or ""
                year_be = m_amend.group(2) or ""
                year_ce = str(int(year_be) - 543) if year_be.isdigit() else ""
                
                if base_name not in amendments_by_base:
                    amendments_by_base[base_name] = []
                amendments_by_base[base_name].append({
                    "title": title,
                    "edition": f"ฉบับที่ {edition}" if edition else "",
                    "year_be": year_be,
                    "year_ce": year_ce
                })

        # Check for repeal notices in text or title
        if "ถูกยกเลิก" in title or "ให้ยกเลิก" in text[:300]:
            m_rep = repeal_pattern.search(text[:600])
            repealing_act = m_rep.group(1).strip() if m_rep else "ยกเลิกโดยกฎหมายฉบับใหม่"
            repeals[doc_id] = repealing_act[:250]

    print(f"[INFO] Discovered {len(amendments_by_base):,} base laws with registered amendment series.")
    print(f"[INFO] Discovered {len(repeals):,} repealed statutes.")

    # 2. Prepare batch updates
    updates = []
    active_count = 0
    amended_count = 0
    repealed_count = 0

    for doc_id, title, text in rows:
        title = title or ""
        
        if doc_id in repeals:
            status_th = "ถูกยกเลิก"
            status = "REPEALED"
            repealed_by = repeals[doc_id]
            last_act = None
            last_num = None
            last_be = None
            last_ce = None
            repealed_count += 1
        else:
            # Check if this law has amendments
            m_base = base_law_pattern.search(title)
            base_name = (m_base.group(1) + m_base.group(2)).strip() if m_base else title.strip()
            
            if base_name in amendments_by_base:
                sorted_amends = sorted(
                    amendments_by_base[base_name],
                    key=lambda x: int(x["year_be"]) if x["year_be"].isdigit() else 0,
                    reverse=True
                )
                latest = sorted_amends[0]
                status_th = "แก้ไขเพิ่มเติม"
                status = "AMENDED"
                last_act = latest["title"]
                last_num = latest["edition"]
                last_be = latest["year_be"]
                last_ce = latest["year_ce"]
                repealed_by = None
                amended_count += 1
            else:
                status_th = "มีผลใช้บังคับ"
                status = "ACTIVE"
                last_act = None
                last_num = None
                last_be = None
                last_ce = None
                repealed_by = None
                active_count += 1

        updates.append((
            status,
            status_th,
            last_act,
            last_num,
            last_be,
            last_ce,
            repealed_by,
            doc_id
        ))

    print(f"[INFO] Updating database: {active_count:,} มีผลใช้บังคับ (ACTIVE), {amended_count:,} แก้ไขเพิ่มเติม (AMENDED), {repealed_count:,} ถูกยกเลิก (REPEALED)...")

    update_query = """
        UPDATE thai_legal_cards
        SET status = %s,
            status_th = %s,
            last_amendment_act = %s,
            last_amendment_num = %s,
            last_amendment_year_be = %s,
            last_amendment_year_ce = %s,
            repealed_by = %s,
            currency_verified_at = CURRENT_TIMESTAMP
        WHERE doc_id = %s;
    """

    with conn.cursor() as cur:
        execute_batch(cur, update_query, updates, page_size=2000)
        conn.commit()

    print(f"[SUCCESS] All {len(updates):,} Thai legal cards marked with precise statutory status!")
    return {
        "active": active_count,
        "amended": amended_count,
        "repealed": repealed_count
    }

def main():
    start_time = time.time()
    print("=================================================================")
    print("  CONSULTANTPLUS TH - STATUTORY STATUS & AMENDMENT PIPELINE      ")
    print("=================================================================")

    conn = psycopg2.connect(**PG_CONFIG)
    ensure_columns(conn)
    counts = process_amendment_lineage(conn)
    conn.close()

    elapsed = time.time() - start_time
    print(f"[COMPLETED] Pipeline finished in {elapsed:.2f} seconds.")
    print("Summary:")
    print(f"  * มีผลใช้บังคับ (ACTIVE): {counts['active']:,}")
    print(f"  * แก้ไขเพิ่มเติม (AMENDED): {counts['amended']:,}")
    print(f"  * ถูกยกเลิก (REPEALED): {counts['repealed']:,}")

if __name__ == "__main__":
    main()
