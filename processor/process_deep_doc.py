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


def extract_links(raw_html: str, base_url: str) -> list[dict]:
    """Извлекает все ссылки из HTML, которые ведут на тот же домен."""
    links = []
    soup = BeautifulSoup(raw_html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        
        full_url = urljoin(base_url, href)
        if urlparse(full_url).netloc == urlparse(base_url).netloc:
            links.append({
                "text": a.get_text(strip=True),
                "url": full_url
            })
    return links


def process_deep_report(report_path: Path):
    """
    Обрабатывает JSON-отчет от ocs_laws_deep_by_url скрапера,
    консолидирует все найденные тексты и извлекает связи.
    """
    report = json.loads(report_path.read_text(encoding="utf-8"))
    law_idx = report.get("law_global_idx")
    base_url = report.get("full_url")
    
    print(f"Processing deep report for law_idx: {law_idx}")

    all_texts = []
    all_links = []
    source_files = []

    # 1. Базовый HTML
    if report.get("base_html"):
        p = Path(RAW) / Path(report["base_html"]).name
        if p.exists():
            source_files.append(str(p))
            html = p.read_text(encoding="utf-8")
            all_texts.append(html_to_text(html))
            all_links.extend(extract_links(html, base_url))

    # 2. Версии HTML
    for v in report.get("versions", []):
        if v.get("saved_html"):
            p = Path(RAW) / Path(v["saved_html"]).name
            if p.exists():
                source_files.append(str(p))
                html = p.read_text(encoding="utf-8")
                all_texts.append(f"\n--- VERSION {v['v']} ---\n{html_to_text(html)}")
                all_links.extend(extract_links(html, base_url))

    # 3. HTML вложения
    for a in report.get("html_attachments", []):
        if a.get("saved_html"):
            p = Path(RAW) / Path(a["saved_html"]).name
            if p.exists():
                source_files.append(str(p))
                html = p.read_text(encoding="utf-8")
                all_texts.append(f"\n--- ATTACHMENT {a['k']}: {a['title']} ---\n{html_to_text(html)}")
                all_links.extend(extract_links(html, base_url))

    # 4. PDF вложения
    for pdf_info in report.get("pdf_downloads", []):
        if pdf_info.get("ok") and pdf_info.get("saved_as"):
            p = Path(RAW) / Path(pdf_info["saved_as"]).name
            if p.exists():
                source_files.append(str(p))
                all_texts.append(f"\n--- PDF ATTACHMENT {pdf_info['k']} ---\n{pdf_to_text(str(p))}")

    # Дедупликация ссылок
    unique_links = []
    seen_urls = set()
    for link in all_links:
        if link["url"] not in seen_urls:
            unique_links.append(link)
            seen_urls.add(link["url"])

    # Сборка и обработка единого текста
    consolidated_text = "\n".join(all_texts)
    clean = clean_text(consolidated_text)
    chunks_text = chunk_text(clean, max_chars=1200, overlap=200)
    structure = parse_structure(clean, report)

    chunks = []
    for idx, ch in enumerate(chunks_text):
        chunks.append({
            "chunk_id": idx,
            "text": ch,
        })

    # Собираем финальный документ
    doc = {
        "meta": report, # Вся метаинформация из отчета скрапера
        "source_files": source_files,
        "links": unique_links,
        "structure": structure,
        "chunks": chunks,
        "consolidated_text_len": len(clean),
    }

    out_name = f"deep_law_{law_idx}.processed.json"
    out_path = Path(OUT) / out_name
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)

    print("Processed deep report:", report_path, "->", out_path)


def main():
    report_files = sorted(Path(RAW).glob("ocs_law_deep_by_url_*.json"))
    print("FOUND DEEP REPORTS:", [str(p) for p in report_files])
    for report_path in report_files:
        print("PROCESSING DEEP REPORT:", report_path)
        try:
            process_deep_report(report_path)
        except Exception as e:
            print(f"!!! FAILED to process {report_path}: {e}")


if __name__ == "__main__":
    main()
