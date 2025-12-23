#!/usr/bin/env python3
"""
Test-run: download sample PDF, process, index and run a simple query.
Run this locally (not in compose) to validate pipeline step-by-step.
"""
import subprocess, os, time, requests, json

ROOT = os.path.dirname(os.path.dirname(__file__))
print("ROOT", ROOT)

# 1) Run scraper for sample PDF only (we call script but can set RG_SAMPLE_PDF)
os.environ['RG_SAMPLE_PDF'] = "https://ratchakitcha.soc.go.th/documents/95262.pdf"
os.environ['OUTPUT_DIR'] = os.path.join(ROOT, "data","raw")
os.makedirs(os.environ['OUTPUT_DIR'], exist_ok=True)
print("Running scraper (sample pdf)...")
subprocess.run(["python","scraper/rg_scraper.py"], check=True)

# 2) Process
os.environ['RAW_DIR'] = os.path.join(ROOT, "data","raw")
os.environ['PROCESSED_DIR'] = os.path.join(ROOT, "data","processed")
os.makedirs(os.environ['PROCESSED_DIR'], exist_ok=True)
print("Running processor...")
subprocess.run(["python","processor/process_doc.py"], check=True)

# 3) Index (note: Qdrant must be running locally on 6333)
print("Indexing to Qdrant (requires qdrant running)...")
subprocess.run(["python","indexer/index_to_qdrant.py"], check=True)

print("Test run complete. Now try query to backend if running.")
