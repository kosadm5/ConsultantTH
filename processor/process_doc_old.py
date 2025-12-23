#!/usr/bin/env python3
# processor/process_doc.py
import os, json, re, time
from pathlib import Path
from pypdf import PdfReader
from pdf2image import convert_from_path
import pytesseract
from pythainlp.tokenize import word_tokenize

RAW = os.getenv("RAW_DIR", "/app/data/raw")
OUT = os.getenv("PROCESSED_DIR", "/app/data/processed")
os.makedirs(OUT, exist_ok=True)

def pdf_to_text(fn):
    try:
        reader = PdfReader(fn)
        pages = []
        for p in reader.pages:
            t = p.extract_text() or ""
            pages.append(t)
        text = "\n".join(pages)
        if len(text.strip()) < 200:
            raise ValueError("Too little text, will OCR")
        return text
    except Exception:
        # OCR fallback
        try:
            images = convert_from_path(fn, dpi=300)
            texts = [pytesseract.image_to_string(img, lang="tha+eng") for img in images]
            return "\n".join(texts)
        except Exception as e:
            print("OCR failed", e)
            return ""

def clean_text(t):
    t = re.sub(r"\r", "\n", t)
    t = re.sub(r"\n{2,}", "\n\n", t)
    t = re.sub(r"[ \t]+", " ", t)
    return t.strip()

def chunk_text_thai(text, chunk_chars=1200, overlap=300):
    parts = []
    L = len(text)
    i = 0
    while i < L:
        end = min(i + chunk_chars, L)
        chunk = text[i:end]
        # try to snap to newline
        if end < L:
            nxt = text.find("\n", end, min(L, end+200))
            if nxt != -1:
                end = nxt
                chunk = text[i:end]
        parts.append(chunk.strip())
        i = end - overlap
        if i < 0: i = 0
    return parts

def process_meta(meta_path):
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    fn = meta.get("filename")
    if not fn or not Path(fn).exists():
        print("File missing:", fn)
        return
    raw_text = ""
    if fn.lower().endswith(".pdf"):
        raw_text = pdf_to_text(fn)
    else:
        with open(fn, "r", encoding="utf-8") as rf:
            raw_text = rf.read()
    clean = clean_text(raw_text)
    chunks = chunk_text_thai(clean)
    out = {
        "meta": meta,
        "raw_text_length": len(raw_text),
        "clean_text": clean[:200000],
        "chunks": [{"chunk_id": i, "text": c[:20000]} for i,c in enumerate(chunks)]
    }
    outfn = Path(OUT) / (Path(fn).stem + ".processed.json")
    with open(outfn, "w", encoding="utf-8") as fo:
        json.dump(out, fo, ensure_ascii=False)
    print("Processed:", fn, "->", outfn)

def main():
    meta_files = sorted(Path(RAW).glob("*.meta.json"))
    for m in meta_files:
        process_meta(str(m))
        
if __name__ == "__main__":
    process_meta("/app/data/raw/ocs_constitution_list.meta.json")
#if __name__ == "__main__":
#    main()