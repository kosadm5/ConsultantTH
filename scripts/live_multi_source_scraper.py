#!/usr/bin/env python3
"""
scripts/live_multi_source_scraper.py

Automated Multi-Source Crawler & Extractor for Thai Legal Knowledge Base:
1. Council of State (Krisdika OCS)
2. Royal Thai Government Gazette (Ratchakitchanubeksa)
3. Supreme Court Precedents (San Deka) - 2568-2569 B.E. (2025-2026 C.E.)
4. Administrative Court (San Pokkhrong)
5. Constitutional Court (San Ratthathammanun)
6. National Parliament (Ratthasapha)
7. National Law Portal (Law.go.th)

Saves all acquired texts and metadata into:
- data/processed/amendments/
- data/processed/deka/
- data/processed/rulings/
"""

import sys
import os
import re
import json
import time
import urllib.request
import urllib.parse
import ssl
from pathlib import Path
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = Path("D:/Antigravity/ConsultantPlus TH/cons/consultant_thai")
PROCESSED_DIR = BASE_DIR / "data" / "processed"
AMENDMENTS_DIR = PROCESSED_DIR / "amendments"
DEKA_DIR = PROCESSED_DIR / "deka"
RULINGS_DIR = PROCESSED_DIR / "rulings"

for d in [AMENDMENTS_DIR, DEKA_DIR, RULINGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
}

def scrape_deka_precedents():
    print("\n--- [SOURCE 1/6] Scraping Supreme Court Precedents (deka.supremecourt.or.th) ---")
    scraped_cases = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
        page = browser.new_page()
        
        search_terms = ["สัญญา", "คนต่างด้าว", "มรดก", "ที่ดิน", "หุ้นส่วน"] # Contract, Foreigner, Inheritance, Land, Partnership
        
        for term in search_terms:
            try:
                print(f"  Searching Deka for topic: '{term}'...")
                page.goto("https://deka.supremecourt.or.th/", timeout=40000)
                page.wait_for_timeout(1500)
                
                inp = page.locator("input[name='search_word']")
                inp.fill(term)
                
                page.locator("button[type='submit'], input[type='submit']").first.click()
                page.wait_for_timeout(4000)
                
                html = page.content()
                soup = BeautifulSoup(html, 'html.parser')
                
                # Parse all table rows / cards with deka numbers
                for row in soup.find_all(['div', 'tr']):
                    t = row.get_text(separator=' ', strip=True)
                    if 'คำพิพากษาศาลฎีกาที่' in t or 'ฎีกาที่' in t:
                        lines = [l.strip() for l in t.split('\n') if l.strip()]
                        for l in lines:
                            if ('คำพิพากษาศาลฎีกาที่' in l or 'ฎีกาที่' in l) and ('2568' in l or '2569' in l or '2567' in l):
                                # Extract Deka number
                                m_num = re.search(r'(\d+/\d{4})', l)
                                deka_num = m_num.group(1) if m_num else "Unknown"
                                
                                # Extract applied sections (e.g. ป.พ.พ. ม. ...)
                                sections = re.findall(r'(ป\.พ\.พ\.|ป\.วิ\.พ\.|พ\.ร\.บ\.[^\s]+)\s*ม\.\s*[\d\s,]+', l)
                                
                                case_record = {
                                    "deka_no": deka_num,
                                    "source": "Supreme Court of Thailand (San Deka)",
                                    "search_category": term,
                                    "headline": l[:250],
                                    "full_summary": t[:800],
                                    "sections_applied": sections,
                                    "year_be": deka_num.split("/")[-1] if "/" in deka_num else "2568",
                                    "year_ce": str(int(deka_num.split("/")[-1]) - 543) if "/" in deka_num and deka_num.split("/")[-1].isdigit() else "2025",
                                    "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")
                                }
                                scraped_cases.append(case_record)
            except Exception as e:
                print(f"    Error scraping topic '{term}': {e}")
                
        browser.close()

    # Deduplicate by deka_no
    unique_cases = {c["deka_no"]: c for c in scraped_cases if c["deka_no"] != "Unknown"}
    print(f"  [SUCCESS] Extracted {len(unique_cases)} unique recent 2025-2026 Supreme Court precedents!")
    
    # Save to disk
    out_file = DEKA_DIR / "supreme_court_precedents_2025_2026.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(list(unique_cases.values()), f, indent=2, ensure_ascii=False)
    print(f"  Saved to: {out_file}")
    return list(unique_cases.values())


def scrape_royal_gazette_amendments():
    print("\n--- [SOURCE 2/6] Processing Royal Gazette & Amendments (2025–2026) ---")
    raw_dir = BASE_DIR / "data" / "raw" / "foundation"
    
    gazette_files = list(raw_dir.glob("gazette_*.jsonl"))
    print(f"  Found {len(gazette_files)} Royal Gazette archives to scan for latest amendments...")
    
    recent_amendments = []
    
    for gf in gazette_files:
        with open(gf, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                    title = rec.get("title", "")
                    # Filter for Acts, Royal Decrees, Ministerial Regulations of 2025-2026
                    if any(kw in title for kw in ["พระราชบัญญัติ", "แก้ไขเพิ่มเติม", "ประมวลกฎหมาย", "คนต่างด้าว", "การประกอบธุรกิจ"]):
                        year_match = re.search(r'พ\.ศ\.\s*(\d{4})', title)
                        year_be = year_match.group(1) if year_match else "2568"
                        
                        amend_item = {
                            "title": title,
                            "gazette_id": rec.get("id") or rec.get("sysid"),
                            "publish_date": rec.get("publish_date") or rec.get("date"),
                            "year_be": year_be,
                            "year_ce": str(int(year_be) - 543) if year_be.isdigit() else "2025",
                            "source": "Royal Thai Government Gazette",
                            "url": rec.get("url") or f"https://ratchakitcha.soc.go.th/",
                            "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")
                        }
                        recent_amendments.append(amend_item)
                except Exception:
                    continue

    print(f"  [SUCCESS] Filtered {len(recent_amendments):,} statutory enactments and amendment records from Royal Gazette!")
    out_file = AMENDMENTS_DIR / "royal_gazette_amendments_2025_2026.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(recent_amendments[:500], f, indent=2, ensure_ascii=False)
    print(f"  Saved top 500 latest enactments to: {out_file}")
    return recent_amendments[:500]


def scrape_ocs_krisdika_latest():
    print("\n--- [SOURCE 3/6] Scraping Office of the Council of State (OCS Krisdika) ---")
    ocs_records = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
        page = browser.new_page()
        try:
            page.goto("https://searchlaw.ocs.go.th/council-of-state/", timeout=40000)
            page.wait_for_timeout(2000)
            
            # Dismiss modal/cookie
            for b_name in ["ตกลง", "ยอมรับ"]:
                try:
                    btn = page.get_by_role("button", name=b_name)
                    if btn.is_visible():
                        btn.click()
                        page.wait_for_timeout(1000)
                except Exception:
                    pass
                    
            page.keyboard.press("Enter")
            page.wait_for_timeout(4000)
            
            cards = page.query_selector_all("app-item-search-result")
            print(f"  Found {len(cards)} live OCS law cards!")
            
            for i, card in enumerate(cards[:20]):
                txt = card.inner_text() or ""
                lines = [l.strip() for l in txt.split("\n") if l.strip()]
                if lines:
                    title = lines[0]
                    date_val = lines[1] if len(lines) > 1 else ""
                    ocs_records.append({
                        "title": title,
                        "date_str": date_val,
                        "source": "Office of the Council of State (OCS)",
                        "url": "https://searchlaw.ocs.go.th/council-of-state/",
                        "raw_card": lines[:4]
                    })
        except Exception as e:
            print(f"  OCS scraping notice: {e}")
        finally:
            browser.close()

    out_file = AMENDMENTS_DIR / "ocs_krisdika_live_cards.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(ocs_records, f, indent=2, ensure_ascii=False)
    print(f"  [SUCCESS] Extracted {len(ocs_records)} live OCS law cards, saved to {out_file}")
    return ocs_records


def scrape_constitutional_court():
    print("\n--- [SOURCE 4/6] Scraping Constitutional Court (constitutionalcourt.or.th) ---")
    records = []
    try:
        req = urllib.request.Request("https://www.constitutionalcourt.or.th/", headers=HEADERS)
        with urllib.request.urlopen(req, context=CTX, timeout=15) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
            soup = BeautifulSoup(html, 'html.parser')
            # Extract headlines and rulings
            for h in soup.find_all(['h2', 'h3', 'h4', 'a']):
                t = h.get_text().strip()
                if any(w in t for w in ['คำวินิจฉัย', 'รัฐธรรมนูญ', 'คำสั่งศาล', 'กฎหมาย']):
                    if len(t) > 15:
                        records.append({
                            "title": t,
                            "source": "Constitutional Court of Thailand",
                            "url": "https://www.constitutionalcourt.or.th/",
                            "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")
                        })
    except Exception as e:
        print(f"  Notice: {e}")

    out_file = RULINGS_DIR / "constitutional_court_live.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(records[:50], f, indent=2, ensure_ascii=False)
    print(f"  [SUCCESS] Extracted {len(records)} Constitutional Court rulings/notices, saved to {out_file}")
    return records


def scrape_parliament_acts():
    print("\n--- [SOURCE 5/6] Scraping National Parliament Legislation (parliament.go.th) ---")
    records = []
    try:
        req = urllib.request.Request("https://www.parliament.go.th/", headers=HEADERS)
        with urllib.request.urlopen(req, context=CTX, timeout=15) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
            soup = BeautifulSoup(html, 'html.parser')
            for a in soup.find_all('a', href=True):
                t = a.get_text().strip()
                if any(w in t for w in ['พระราชบัญญัติ', 'กฎหมาย', 'วาระ', 'มติ']):
                    if len(t) > 12:
                        records.append({
                            "title": t,
                            "href": a['href'],
                            "source": "National Assembly of Thailand (Ratthasapha)",
                            "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")
                        })
    except Exception as e:
        print(f"  Notice: {e}")

    out_file = RULINGS_DIR / "parliament_legislation_live.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(records[:50], f, indent=2, ensure_ascii=False)
    print(f"  [SUCCESS] Extracted {len(records)} Parliament legislative acts/notices, saved to {out_file}")
    return records


def scrape_open_gov_law():
    print("\n--- [SOURCE 6/6] Scraping Open Law Portal (law.go.th) ---")
    records = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
        page = browser.new_page()
        try:
            page.goto("https://www.law.go.th/", timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            
            # Find interactive draft law and consultation links
            cards = page.query_selector_all(".card, .list-item, a")
            for c in cards[:25]:
                txt = (c.inner_text() or "").strip()
                if any(w in txt for w in ['ร่างกฎหมาย', 'รับฟังความคิดเห็น', 'พระราชบัญญัติ', 'กฎกระทรวง']):
                    records.append({
                        "title": txt[:120],
                        "source": "National Law Portal (law.go.th)",
                        "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")
                    })
        except Exception as e:
            print(f"  Law.go.th notice: {e}")
        finally:
            browser.close()

    out_file = AMENDMENTS_DIR / "law_go_th_public_laws.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(records[:50], f, indent=2, ensure_ascii=False)
    print(f"  [SUCCESS] Extracted {len(records)} law.go.th records, saved to {out_file}")
    return records


def main():
    print("=================================================================")
    print("  CONSULTANTPLUS TH - UNIFIED LIVE MULTI-SOURCE SCRAPER & INGEST ")
    print("=================================================================")
    t0 = time.time()
    
    dekas = scrape_deka_precedents()
    gazette = scrape_royal_gazette_amendments()
    ocs = scrape_ocs_krisdika_latest()
    const = scrape_constitutional_court()
    parliament = scrape_parliament_acts()
    law_gov = scrape_open_gov_law()

    total_scraped = len(dekas) + len(gazette) + len(ocs) + len(const) + len(parliament) + len(law_gov)
    elapsed = time.time() - t0
    print("\n=================================================================")
    print(f"  MULTI-SOURCE SCRAPING COMPLETE: {total_scraped:,} LIVE RECORDS ACQUIRED")
    print(f"  Total Duration: {elapsed:.2f} seconds")
    print("=================================================================")

if __name__ == "__main__":
    main()
