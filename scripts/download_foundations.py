#!/usr/bin/env python3
"""
scripts/download_foundations.py
Downloads the freshest foundation datasets for ConsultantPlus TH from GitHub & Hugging Face.
"""

import os
import sys
import json
import urllib.request
import ssl
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
FOUNDATION_DIR = BASE_DIR / "data" / "raw" / "foundation"
FOUNDATION_DIR.mkdir(parents=True, exist_ok=True)

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def download_file(url: str, out_path: Path) -> bool:
    if out_path.exists() and out_path.stat().st_size > 1000:
        print(f"[ALREADY EXISTS] {out_path.name} ({out_path.stat().st_size:,} bytes)")
        return True
    print(f"[DOWNLOADING] {url} -> {out_path.name}...")
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, context=CTX, timeout=60) as resp, open(out_path, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
        print(f"[SUCCESS] {out_path.name} ({out_path.stat().st_size:,} bytes)")
        return True
    except Exception as e:
        print(f"[ERROR] Failed {url}: {e}")
        return False

def main():
    print("=== Downloading Thai Legal Foundations ===")
    
    # 1. PyThaiNLP Codified Laws (Criminal, Civil & Commercial)
    law_files = [
        ("https://github.com/PyThaiNLP/thai-law/releases/download/criminal-csv-v0.1/criminal-datasets.csv", "criminal-datasets.csv"),
        ("https://github.com/PyThaiNLP/thai-law/releases/download/civil-commercial-csv-v0.1/civil-and-commercial-datasets.csv", "civil-and-commercial-datasets.csv"),
        ("https://github.com/PyThaiNLP/thai-law/releases/download/communicable-diseases-csv-v0.1/communicable-diseases-datasets.csv", "communicable-diseases-datasets.csv"),
    ]
    
    for url, fn in law_files:
        download_file(url, FOUNDATION_DIR / fn)

    # 2. Hugging Face Ratchakitcha (Royal Gazette recent records & metadata)
    hf_base = "https://huggingface.co/datasets/teerapat86/soc-ratchakitcha/raw/main"
    gazette_files = [
        (f"{hf_base}/latest_update.json", "gazette_latest_update.json"),
        (f"{hf_base}/meta/2026/2026-01.jsonl", "gazette_2026_01.jsonl"),
        (f"{hf_base}/meta/2025/2025-12.jsonl", "gazette_2025_12.jsonl"),
        (f"{hf_base}/meta/2025/2025-11.jsonl", "gazette_2025_11.jsonl"),
        (f"{hf_base}/meta/2025/2025-10.jsonl", "gazette_2025_10.jsonl"),
    ]
    
    for url, fn in gazette_files:
        download_file(url, FOUNDATION_DIR / fn)

    print("\n=== Summary of Foundation Datasets ===")
    total_size = 0
    for f in sorted(FOUNDATION_DIR.glob("*")):
        if f.is_file():
            size = f.stat().st_size
            total_size += size
            print(f"  {f.name}: {size:,} bytes")
    print(f"Total foundation corpus: {total_size / (1024*1024):.2f} MB")

if __name__ == "__main__":
    main()
