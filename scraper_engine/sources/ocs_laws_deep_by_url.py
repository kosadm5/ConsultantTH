import asyncio
import os
import json
import re
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, urljoin

import requests

from scraper_engine.base_client import BaseClient
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/data/raw"))
BASE = "https://searchlaw.ocs.go.th"

MAX_ITEMS = int(os.getenv("OCS_LAWS_DEEP_BY_URL_MAX_ITEMS", "50"))
START_IDX = int(os.getenv("OCS_LAWS_DEEP_BY_URL_START_IDX", "0"))

UI_PAUSE_MS = int(os.getenv("OCS_UI_PAUSE_MS", "1200"))
NAV_TIMEOUT_MS = int(os.getenv("OCS_NAV_TIMEOUT_MS", "60000"))

OCS_MAX_VERSIONS_PER_LAW = int(os.getenv("OCS_MAX_VERSIONS_PER_LAW", "10"))
OCS_MAX_PDFS_PER_PAGE = int(os.getenv("OCS_MAX_PDFS_PER_PAGE", "10"))
OCS_MAX_CLICKERS_PER_PAGE = int(os.getenv("OCS_MAX_CLICKERS_PER_PAGE", "25"))
OCS_MAX_HTML_ATTACHMENTS_PER_LAW = int(os.getenv("OCS_MAX_HTML_ATTACHMENTS_PER_LAW", "5"))

# Если PDF открывается в отдельной вкладке и expect_download не срабатывает,
# будем качать по прямому URL через requests (из контейнера).
REQUESTS_TIMEOUT = int(os.getenv("OCS_PDF_HTTP_TIMEOUT", "120"))
REQUESTS_UA = os.getenv("OCS_HTTP_UA", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36")


def _slugify(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^0-9A-Za-z_\u0E00-\u0E7F\-\.]+", "", s)  # thai ok
    return s[:120] if len(s) > 120 else s


async def wait_spinner(page, timeout: int = 20000):
    try:
        await page.wait_for_selector("div.ngx-spinner-overlay", state="detached", timeout=timeout)
    except PlaywrightTimeoutError:
        pass


class Source:
    name = "ocs_laws_deep_by_url"

    def _iter_meta_files(self):
        files = sorted(OUTPUT_DIR.glob("ocs_law_*.meta.json"), key=lambda p: p.name)
        # Берём сдвиг и ограничение
        files = files[START_IDX:START_IDX + MAX_ITEMS]
        return files

    async def _download_pdf_via_requests(self, url: str, out_path: Path) -> dict:
        headers = {"User-Agent": REQUESTS_UA}
        r = requests.get(url, headers=headers, timeout=REQUESTS_TIMEOUT, stream=True)
        r.raise_for_status()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 128):
                if chunk:
                    f.write(chunk)
        return {"method": "requests", "url": url, "status": r.status_code, "bytes": out_path.stat().st_size}

    async def _try_download_from_click(self, page, clickable, out_path: Path) -> dict:
        """
        Пытаемся скачать PDF по клику:
        1) expect_download()
        2) если открылось в новой вкладке — берём её URL и качаем requests'ом
        3) если навигация в той же вкладке на pdf — берём page.url и качаем
        """
        # 1) прямой download
        try:
            async with page.expect_download(timeout=8000) as dl_info:
                await clickable.click()
            dl = await dl_info.value
            await dl.save_as(out_path)
            return {"ok": True, "method": "playwright_download", "download_url": dl.url, "saved_as": str(out_path)}
        except Exception:
            pass

        # 2) новая вкладка
        context = page.context
        try:
            async with context.expect_page(timeout=8000) as newp_info:
                await clickable.click()
            pdf_page = await newp_info.value
            await pdf_page.wait_for_load_state("domcontentloaded", timeout=15000)
            pdf_url = pdf_page.url
            await pdf_page.close()

            # если это реально PDF
            if ".pdf" in pdf_url.lower() or "application/pdf" in pdf_url.lower():
                res = await self._download_pdf_via_requests(pdf_url, out_path)
                return {"ok": True, **res, "saved_as": str(out_path)}
            # всё равно пробуем скачать
            res = await self._download_pdf_via_requests(pdf_url, out_path)
            return {"ok": True, **res, "saved_as": str(out_path)}
        except Exception:
            pass

        # 3) навигация в той же вкладке
        try:
            before = page.url
            await clickable.click()
            await page.wait_for_timeout(1500)
            after = page.url
            if after != before and ("pdf" in after.lower()):
                res = await self._download_pdf_via_requests(after, out_path)
                # вернёмся назад
                try:
                    await page.go_back(wait_until="networkidle", timeout=15000)
                except Exception:
                    pass
                return {"ok": True, **res, "saved_as": str(out_path)}
        except Exception:
            pass

        return {"ok": False, "method": None, "error": "download_not_detected"}

    async def _collect_version_clickers(self, page):
        """
        Универсально собираем элементы, которые похожи на переключатели версии.
        Не делаем жёстких предположений о DOM.
        """
        # Часто таймлайн/список версий — набор кликабельных span/div/button рядом с иконкой "file"
        selectors = [
            "p-timeline *[role='button']",
            "p-timeline span.pointer",
            "p-timeline button",
            "p-timeline .p-timeline-event-content",
            "div[role='button']",
            "button",
            "span.pointer",
        ]
        clickers = []
        for sel in selectors:
            els = await page.query_selector_all(sel)
            for el in els:
                try:
                    bb = await el.bounding_box()
                    if not bb:
                        continue
                    # отсекаем совсем мелкие невидимые
                    if bb["width"] < 10 or bb["height"] < 10:
                        continue
                    # отсекаем элементы пагинации/шапки сайта по тексту
                    txt = ""
                    try:
                        txt = ((await el.inner_text()) or "").strip()
                    except Exception:
                        txt = ""
                    if txt in {"ถัดไป", "ก่อนหน้า", "Next", "Previous"}:
                        continue
                    clickers.append(el)
                except Exception:
                    continue

        # Дедуп по (x,y,w,h)
        uniq = []
        seen = set()
        for el in clickers:
            try:
                bb = await el.bounding_box()
                key = (round(bb["x"]), round(bb["y"]), round(bb["width"]), round(bb["height"]))
                if key in seen:
                    continue
                seen.add(key)
                uniq.append(el)
            except Exception:
                continue
        return uniq[:OCS_MAX_CLICKERS_PER_PAGE]  # чтобы не кликать 200 кнопок на странице

    async def fetch(self, client: BaseClient):
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        page = await client.new_page()

        meta_files = self._iter_meta_files()
        print(f"DEEP_BY_URL: meta_files={len(meta_files)} start={START_IDX} max={MAX_ITEMS}")

        all_reports = []

        for i, mp in enumerate(meta_files):
            meta = json.loads(mp.read_text(encoding="utf-8"))
            law_idx = meta.get("law_global_idx")
            full_url = meta.get("full_url") or meta.get("url")
            title = meta.get("title") or ""
            title_slug = _slugify(title) or f"law_{law_idx}"

            print(f"\nDEEP_BY_URL ITEM {i}/{len(meta_files)} law_idx={law_idx} title={title}")

            report = {
                "fetched_at": datetime.utcnow().isoformat() + "Z",
                "law_global_idx": law_idx,
                "title": title,
                "full_url": full_url,
                "versions": [],
                "pdf_downloads": [],
                "errors": [],
            }

            # open doc page
            try:
                await page.goto(full_url, timeout=NAV_TIMEOUT_MS)
                await page.wait_for_load_state("networkidle")
                await wait_spinner(page)
                await page.wait_for_timeout(UI_PAUSE_MS)
            except Exception as e:
                report["errors"].append({"stage": "goto", "error": str(e)})
                all_reports.append(report)
                continue

            # 1) save "base" html (as seen)
            try:
                html = await page.content()
                out_html = OUTPUT_DIR / f"ocs_law_doc_{law_idx}_base.html"
                out_html.write_text(html, encoding="utf-8")
                report["base_html"] = str(out_html)
            except Exception as e:
                report["errors"].append({"stage": "save_base_html", "error": str(e)})

            # 2) try to download all visible pdf icons (best effort)
            downloaded_pdf_urls = set()
            try:
                pdf_icons = await page.query_selector_all("i.fa-file-pdf")
                print(f"  PDF icons found: {len(pdf_icons)}")
                for k, icon in enumerate(pdf_icons[:OCS_MAX_PDFS_PER_PAGE]):  # ограничим, чтобы не уйти в вечность
                    out_pdf = OUTPUT_DIR / f"ocs_law_{law_idx}_{title_slug}_pdf_{k}.pdf"
                    res = await self._try_download_from_click(page, icon, out_pdf)
                    res["k"] = k
                    report["pdf_downloads"].append(res)
                    if res.get("ok"):
                        url = res.get("download_url") or res.get("url")
                        if url:
                            downloaded_pdf_urls.add(url)
            except Exception as e:
                report["errors"].append({"stage": "pdf_icons", "error": str(e)})

            # 2.1) try to download all visible a[href$=.pdf] links
            try:
                pdf_links = await page.query_selector_all("a")
                print(f"  PDF a[href] links found: {len(pdf_links)}")
                links_processed = 0
                for link in pdf_links:
                    if links_processed >= OCS_MAX_PDFS_PER_PAGE:
                        break
                    href = await link.get_attribute("href")
                    if not href or not href.lower().endswith(".pdf"):
                        continue
                    
                    full_pdf_url = urljoin(page.url, href)
                    if full_pdf_url in downloaded_pdf_urls:
                        continue
                    
                    try:
                        k = len(report["pdf_downloads"])
                        out_pdf = OUTPUT_DIR / f"ocs_law_{law_idx}_{title_slug}_pdf_{k}.pdf"
                        res = await self._download_pdf_via_requests(full_pdf_url, out_pdf)
                        res["k"] = k
                        report["pdf_downloads"].append({"ok": True, **res, "saved_as": str(out_pdf)})
                        downloaded_pdf_urls.add(full_pdf_url)
                        links_processed += 1
                    except Exception as e:
                        report["errors"].append({"stage": "pdf_links", "url": full_pdf_url, "error": str(e)})

            except Exception as e:
                report["errors"].append({"stage": "pdf_links_search", "error": str(e)})

            # 2.2) find and download html attachments
            try:
                report["html_attachments"] = []
                # не будем переходить по ссылкам, которые уже скачали как PDF или на саму себя
                visited_urls = downloaded_pdf_urls.copy()
                visited_urls.add(full_url)
                
                links = await page.query_selector_all("a")
                print(f"  HTML attachment links found: {len(links)}")
                
                attachments_processed = 0
                for link in links:
                    if attachments_processed >= OCS_MAX_HTML_ATTACHMENTS_PER_LAW:
                        break

                    href = await link.get_attribute("href")
                    if not href:
                        continue

                    # Пропускаем не-http ссылки и якоря
                    if href.startswith("#") or href.lower().startswith("javascript:"):
                        continue

                    try:
                        attachment_url = urljoin(page.url, href)
                        
                        # Проверяем, что ссылка с того же домена и еще не была посещена
                        if urlparse(attachment_url).netloc != urlparse(BASE).netloc:
                            continue
                        if attachment_url in visited_urls:
                            continue

                        visited_urls.add(attachment_url)
                        
                        # Открываем в новой вкладке, чтобы не потерять контекст
                        context = page.context
                        attachment_page = await context.new_page()
                        await attachment_page.goto(attachment_url, timeout=NAV_TIMEOUT_MS)
                        await wait_spinner(attachment_page)
                        
                        html_content = await attachment_page.content()
                        k = len(report["html_attachments"])
                        out_html_path = OUTPUT_DIR / f"ocs_law_{law_idx}_{title_slug}_attach_{k}.html"
                        out_html_path.write_text(html_content, encoding="utf-8")
                        
                        report["html_attachments"].append({
                            "k": k,
                            "url": attachment_url,
                            "saved_html": str(out_html_path),
                            "title": await attachment_page.title()
                        })
                        await attachment_page.close()
                        attachments_processed += 1

                    except Exception as e:
                        report["errors"].append({"stage": "html_attachment", "url": href, "error": str(e)})

            except Exception as e:
                report["errors"].append({"stage": "html_attachments_search", "error": str(e)})


            # 3) click through "version" clickers and save html after each click
            try:
                clickers = await self._collect_version_clickers(page)
                print(f"  Version-like clickers: {len(clickers)}")
                for v, el in enumerate(clickers):
                    if v >= OCS_MAX_VERSIONS_PER_LAW:  # разумный лимит на закон
                        break
                    try:
                        before_url = page.url
                        await el.click()
                        await page.wait_for_timeout(UI_PAUSE_MS)
                        await wait_spinner(page)
                        after_url = page.url

                        html_v = await page.content()
                        out_html_v = OUTPUT_DIR / f"ocs_law_doc_{law_idx}_v{v}.html"
                        out_html_v.write_text(html_v, encoding="utf-8")

                        report["versions"].append({
                            "v": v,
                            "before_url": before_url,
                            "after_url": after_url,
                            "saved_html": str(out_html_v),
                        })
                    except Exception as e:
                        report["errors"].append({"stage": "click_version", "v": v, "error": str(e)})
            except Exception as e:
                report["errors"].append({"stage": "collect_versions", "error": str(e)})

            # write per-law report
            out_report = OUTPUT_DIR / f"ocs_law_deep_by_url_{law_idx}.json"
            out_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            all_reports.append(report)

        # global summary
        summary = {
            "fetched_at": datetime.utcnow().isoformat() + "Z",
            "start_idx": START_IDX,
            "max_items": MAX_ITEMS,
            "count": len(all_reports),
            "items": [
                {"law_global_idx": r.get("law_global_idx"), "title": r.get("title"), "full_url": r.get("full_url")}
                for r in all_reports
            ],
        }
        (OUTPUT_DIR / "ocs_laws_deep_by_url_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        await page.close()
        print(f"DEEP_BY_URL DONE: {len(all_reports)} items")
        return all_reports


async def main():
    client = BaseClient()
    try:
        src = Source()
        await src.fetch(client)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
