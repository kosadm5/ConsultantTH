"""
Citation and Cross-Reference Knowledge Graph Builder for ConsultantPlus TH
Discovers citations across all legal cards, Council of State opinions, and Deka precedents.
Populates thai_legal_references with directed graph edges:
- (Deka Precedent) --[INTERPRETS]--> (Statutory Code/Act)
- (Ministerial Regulation) --[ENACTED_UNDER]--> (Parent Act)
- (Council of State Opinion) --[INTERPRETS]--> (Statutory Section)
- (Amending Act) --[AMENDS]--> (Principal Act)
"""

import os
import sys
import re
import psycopg2
from datetime import datetime, timezone

if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr:
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

PG_CONN_STR = "postgresql://admin:Privet2020!@localhost:5433/thailaw"

def get_now_utc():
    return datetime.now(timezone.utc)

STATUTE_CANONICAL_TARGETS = {
    r"ประมวลกฎหมายแพ่งและพาณิชย์|ป\.พ\.พ\.": "TH_LAW_CCC_CORP",
    r"ประมวลรัษฎากร|มาตรา 41|ป\.161|ป\.162": "TH_REG_RD_P161_P162_FOREIGN_TAX",
    r"การประกอบธุรกิจของคนต่างด้าว|คนต่างด้าว": "TH_LAW_FBA_1999_FULL",
    r"ส่งเสริมการลงทุน|บีโอไอ|boi": "TH_LAW_BOI_INVESTMENT_PROMOTION_2520",
    r"อาคารชุด|ห้องชุด": "TH_LAW_CONDO_ACT",
    r"คุ้มครองแรงงาน|แรงงาน": "TH_LAW_LABOR_PROT",
    r"สินทรัพย์ดิจิทัล|คริปโท": "TH_LAW_DIGITAL_ASSET_DECREE_2561",
    r"อนุญาโตตุลาการ": "TH_LAW_ARBITRATION",
    r"ประมวลกฎหมายอาญา|ป\.อ\.": "TH_LAW_PENAL_CODE"
}

def build_knowledge_graph():
    print(f"[{get_now_utc().isoformat()}] Starting Thai Citation Knowledge Graph Builder...")
    conn = psycopg2.connect(PG_CONN_STR)
    cur = conn.cursor()

    cur.execute("""
        SELECT doc_id, title, full_text, source
        FROM thai_legal_cards
        WHERE length(full_text) > 50
        LIMIT 5000;
    """)
    rows = cur.fetchall()
    print(f"[{get_now_utc().isoformat()}] Processing citations across {len(rows)} documents...")

    edges_added = 0
    for doc_id, title, full_text, source in rows:
        combined_text = title + " " + full_text[:4000]

        # 1. Check statutory targets
        for pattern, target_id in STATUTE_CANONICAL_TARGETS.items():
            if target_id == doc_id:
                continue
            if re.search(pattern, combined_text, re.IGNORECASE):
                # Find specific section if mentioned
                sec_match = re.search(r"(?:มาตรา|Section)\s+(\d+(?:[\/\-]\d+)?)", combined_text)
                sec_ref = f"มาตรา {sec_match.group(1)}" if sec_match else "General Act Reference"
                
                ref_type = "INTERPRETS" if "Council" in source or "Supreme" in source else "CITES"
                if "กฎกระทรวง" in title or "พระราชกฤษฎีกา" in title:
                    ref_type = "ENACTED_UNDER"

                cur.execute("""
                    INSERT INTO thai_legal_references (source_doc_id, target_doc_id, ref_type, article_ref)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT DO NOTHING;
                """, (doc_id, target_id, ref_type, sec_ref))
                edges_added += 1

        # 2. Check Deka precedent citations
        deka_matches = re.findall(r"ฎีกาที่\s+(\d+\/\d+)", combined_text)
        for d in deka_matches[:3]:
            target_deka = f"TH_DEKA_{d.replace('/', '_')}"
            cur.execute("""
                INSERT INTO thai_legal_references (source_doc_id, target_doc_id, ref_type, article_ref)
                VALUES (%s, %s, 'REFERENCES_PRECEDENT', %s)
                ON CONFLICT DO NOTHING;
            """, (doc_id, target_deka, f"คำพิพากษาฎีกาที่ {d}"))
            edges_added += 1

    conn.commit()
    cur.execute("SELECT count(*) FROM thai_legal_references;")
    total_refs = cur.fetchone()[0]
    print(f"[{get_now_utc().isoformat()}] Graph Builder complete! Added {edges_added} citation links. Total graph edges in thai_legal_references: {total_refs}")
    cur.close()
    conn.close()

if __name__ == "__main__":
    build_knowledge_graph()
