"""OCR сканированных PDF: распознаём текст из страниц-картинок, чтобы сканы учебников
тоже попадали в поиск по библиотеке (RAG).

Движок — системный Tesseract (офлайн, бесплатно), языки rus/uzb/uzb_cyrl/eng. Если бинарь
или pytesseract недоступны — tesseract_available() вернёт False, и фича тихо выключается.
Работа тяжёлая и БЛОКИРУЮЩАЯ (рендер страниц + OCR) — вызывать только в отдельном потоке
(asyncio.to_thread) из фонового воркера, НЕ на event loop.
"""
from __future__ import annotations

import shutil

from .config import settings


def tesseract_available() -> bool:
    """Есть ли на сервере tesseract и pytesseract. Если нет — OCR пропускаем без ошибок."""
    if not shutil.which("tesseract"):
        return False
    try:
        import pytesseract  # noqa: F401
    except Exception:
        return False
    return True


def pdf_page_count(path: str) -> int:
    """Число страниц в PDF (0 при ошибке/не-PDF). Дёшево — только метаданные."""
    try:
        import pymupdf
        with pymupdf.open(path) as doc:
            return doc.page_count
    except Exception:
        return 0


def looks_scanned(extracted_text: str, page_count: int) -> bool:
    """Похоже ли, что PDF — скан (мало текста на страницу)."""
    if page_count <= 0:
        return False
    chars = len((extracted_text or "").strip())
    return (chars / page_count) < max(1, settings.ocr_min_chars_per_page)


def ocr_pdf(path: str, langs: str | None = None, dpi: int | None = None,
            max_pages: int | None = None, page_pause: float | None = None) -> str:
    """Распознать текст из PDF постранично. СИНХРОННАЯ тяжёлая функция — только в потоке.

    Рендерим каждую страницу в картинку (pymupdf) и распознаём (tesseract). Страницы
    обрабатываем по одной (не держим все картинки в памяти — важно для маленького сервера).
    page_pause — пауза между страницами, чтобы OCR отдавал процессор боту (не тормозил его)."""
    import io
    import time

    import pymupdf
    import pytesseract
    from PIL import Image

    langs = langs or settings.ocr_langs
    dpi = dpi or settings.ocr_dpi
    max_pages = max_pages or settings.ocr_max_pages
    page_pause = settings.ocr_page_pause if page_pause is None else page_pause

    parts: list[str] = []
    doc = pymupdf.open(path)
    try:
        total = min(len(doc), max_pages)
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            try:
                pix = page.get_pixmap(dpi=dpi)
                with Image.open(io.BytesIO(pix.tobytes("png"))) as im:
                    txt = pytesseract.image_to_string(im, lang=langs)
                if txt and txt.strip():
                    parts.append(txt.strip())
            except Exception:
                # одна сбойная страница не должна рушить весь OCR
                continue
            # отдать процессор боту между страницами (троттлинг на маленьком сервере)
            if page_pause > 0 and i + 1 < total:
                time.sleep(page_pause)
    finally:
        doc.close()
    return "\n\n".join(parts).strip()
