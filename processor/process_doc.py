#!/usr/bin/env python3
# processor/process_doc.py

from bs4 import BeautifulSoup
from pathlib import Path
from pypdf import PdfReader
from pdf2image import convert_from_path
import pytesseract
import os
import json
import re

RAW = os.getenv("RAW_DIR", "/app/data/raw")
OUT = os.getenv("PROCESSED_DIR", "/app/data/processed")
os.makedirs(OUT, exist_ok=True)


def pdf_to_text(fn: str) -> str:
    """Чтение текста из PDF: сначала пробуем встроенный extract_text, потом OCR."""
    try:
        reader = PdfReader(fn)
        pages = []
        for p in reader.pages:
            t = p.extract_text() or ""
            pages.append(t)
        text = "\n".join(pages)
        # если текста слишком мало, пробуем OCR
        if len(text.strip()) < 200:
            raise ValueError("Too little text, will OCR")
        return text
    except Exception:
        try:
            images = convert_from_path(fn, dpi=300)
            texts = [
                pytesseract.image_to_string(img, lang="tha+eng") for img in images
            ]
            return "\n".join(texts)
        except Exception as e:
            print("OCR failed", e)
            return ""


def html_to_text(raw_html: str) -> str:
    """Простое извлечение текста из HTML c выкидыванием скриптов, стилей и навигации."""
    soup = BeautifulSoup(raw_html, "html.parser")

    # выкидываем техн. элементы
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "form"]):
        tag.decompose()

    # иногда полезно убрать пустые div'ы/спаны без текста
    for el in soup.find_all(["div", "span", "section"]):
        if not el.get_text(strip=True):
            el.decompose()

    text = soup.get_text(separator="\n")
    return text


def clean_text(text: str) -> str:
    """Очистка: убираем лишние пробелы, дубликаты пустых строк и т.п."""
    # нормализуем переводы строк
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # убираем хвостовые пробелы
    text = "\n".join(line.strip() for line in text.split("\n"))
    # убираем дубли пустых строк
    text = re.sub(r"\n{3,}", "\n\n", text)
    # убираем лишние пробелы внутри строки
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def chunk_text(text: str, max_chars: int = 1200, overlap: int = 200) -> list[str]:
    """
    Делим текст на чанки фиксированного размера, с небольшим overlap.
    Работает по абзацам, чтобы не рубить текст совсем уж наобум.
    """
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        if not current:
            current = para
            continue

        # если абзац помещается в текущий чанκ — добавляем
        if len(current) + 1 + len(para) <= max_chars:
            current = current + "\n" + para
        else:
            # сохраняем текущий чанκ
            chunks.append(current.strip())
            # делаем overlap по символам из конца предыдущего чанка
            if overlap > 0 and len(current) > overlap:
                tail = current[-overlap:]
                current = tail + "\n" + para
            else:
                current = para

    if current.strip():
        chunks.append(current.strip())

    # на случай, если документ очень короткий
    if not chunks and text.strip():
        chunks = [text.strip()]

    return chunks


def parse_structure(clean_text: str, meta: dict) -> list[dict]:
    """
    Черновой разбор структуры по строкам:
    - главы (หมวดที่ / หมวด ...)
    - статьи (มาตรา N)

    Обогащаем каждый блок базовой метаинформацией: название, дата, статус.
    """
    lines = [l.strip() for l in clean_text.split("\n") if l.strip()]
    blocks: list[dict] = []

    current_block: dict | None = None

    chapter_re = re.compile(r"^หมวด(ที่)?\s*\d+")
    article_re = re.compile(r"^มาตรา\s*\d+")

    law_title = meta.get("title")
    date_th = meta.get("date_th")
    date_en = meta.get("date_en")
    tags = meta.get("tags", [])

    # грубое определение статуса по слову "ยกเลิก"
    status = "active_or_unknown"
    text_for_status = " ".join(
        [str(law_title or ""), " ".join(tags or []), str(date_th or "")]
    )
    if "ยกเลิก" in text_for_status:
        status = "repealed"

    for line in lines:
        if chapter_re.match(line):
            # начинаем новый блок-главу
            if current_block:
                blocks.append(current_block)
            current_block = {
                "type": "chapter",
                "title": line,
                "text": "",
                "law_title": law_title,
                "date_th": date_th,
                "date_en": date_en,
                "status": status,
            }
        elif article_re.match(line):
            # начинаем новый блок-статью
            if current_block:
                blocks.append(current_block)
            current_block = {
                "type": "article",
                "title": line,
                "text": "",
                "law_title": law_title,
                "date_th": date_th,
                "date_en": date_en,
                "status": status,
            }
        else:
            if current_block:
                if current_block["text"]:
                    current_block["text"] += "\n" + line
                else:
                    current_block["text"] = line
            else:
                # текст до первого заголовка
                if blocks and blocks[-1]["type"] == "preamble":
                    blocks[-1]["text"] += "\n" + line
                else:
                    blocks.append(
                        {
                            "type": "preamble",
                            "title": "",
                            "text": line,
                            "law_title": law_title,
                            "date_th": date_th,
                            "date_en": date_en,
                            "status": status,
                        }
                    )

    if current_block:
        blocks.append(current_block)

    return blocks


def process_meta_file(meta_path: Path):
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    filename = meta.get("filename")
    if not filename:
        print("No filename in meta:", meta_path)
        return

    full_path = Path(filename)
    if not full_path.exists():
        # пробуем относительный путь от RAW
        full_path = Path(RAW) / Path(filename).name
        if not full_path.exists():
            print("File not found for meta:", meta_path, "->", full_path)
            return

    ext = full_path.suffix.lower()
    raw_text = ""

    if ext == ".pdf":
        print("Processing PDF:", full_path)
        raw_text = pdf_to_text(str(full_path))
    elif ext in (".html", ".htm"):
        print("Processing HTML:", full_path)
        raw_html = full_path.read_text(encoding="utf-8", errors="ignore")
        raw_text = html_to_text(raw_html)
    else:
        print("Processing as plain text:", full_path)
        raw_text = full_path.read_text(encoding="utf-8", errors="ignore")

    print("RAW_TEXT_LEN:", len(raw_text))

    clean = clean_text(raw_text)
    print("CLEAN_LEN:", len(clean))

    chunks_text = chunk_text(clean, max_chars=1200, overlap=200)
    print("CHUNKS:", len(chunks_text))

    # черновая структура глава/статья, обогащённая метаданными
    structure = parse_structure(clean, meta)

    chunks = []
    for idx, ch in enumerate(chunks_text):
        chunks.append(
            {
                "chunk_id": idx,
                "text": ch,
            }
        )

    doc = {
        "meta": meta,
        "chunks": chunks,
        "structure": structure,
    }

    out_name = Path(full_path.name).stem + ".processed.json"
    out_path = Path(OUT) / out_name
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)

    print("Processed:", full_path, "->", out_path)


def main():
    meta_files = sorted(Path(RAW).glob("*.meta.json"))
    print("FOUND META FILES:", [str(p) for p in meta_files])
    for meta_path in meta_files:
        print("PROCESSING META:", meta_path)
        process_meta_file(meta_path)


if __name__ == "__main__":
    main()
