"""Фоновое распознавание сканов (OCR) книг библиотеки.

Зачем в фоне: OCR тяжёлый (рендер страниц + tesseract, большой учебник — минуты). Делать при
одобрении нельзя — админ будет ждать, бот затормозит. Поэтому одобрение лишь ставит книге
ocr_status='pending', а этот воркер распознаёт их ПО ОДНОЙ ЗА РАЗ (чтобы маленький сервер не
перегружать), открывая свою сессию БД и НЕ держа соединение во время OCR (см. services.ocr_doc).

Паттерн повторяет app/figjobs.py (очередь+воркер привязаны к текущему циклу событий — важно
для тестов, где loop пересоздаётся)."""
from __future__ import annotations

import asyncio
import logging

from .config import settings

log = logging.getLogger("testroom.ocrjobs")

_queue: asyncio.Queue[int] | None = None
_worker: asyncio.Task | None = None
_loop = None


def _enabled() -> bool:
    if not settings.ocr_enabled:
        return False
    from . import ocr as ocrmod
    return ocrmod.tesseract_available()


def _ensure():
    global _queue, _worker, _loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if _queue is None or _loop is not loop:
        _queue = asyncio.Queue()
        _worker = None
        _loop = loop
    if _worker is None or _worker.done():
        _worker = asyncio.create_task(_run_worker(), name="ocrjobs")
    return _queue


def start() -> None:
    if _enabled():
        _ensure()


def enqueue(doc_id: int) -> None:
    if not _enabled():
        return
    _ensure().put_nowait(doc_id)


async def enqueue_pending() -> int:
    """Поставить в очередь все книги, ждущие OCR (возобновление после рестарта)."""
    if not _enabled():
        return 0
    from . import db as dbmod
    from . import services as svc

    async with dbmod.SessionLocal() as db:
        await svc.backfill_ocr(db)  # пометить старые сканы (одноразово на книгу)
        ids = await svc.pending_ocr_doc_ids(db)
    for i in ids:
        enqueue(i)
    return len(ids)


async def _process_one(doc_id: int) -> None:
    from . import db as dbmod
    from . import services as svc

    async with dbmod.SessionLocal() as db:
        try:
            n = await svc.ocr_doc(db, doc_id)  # тяжёлый OCR; соединение БД не держит
            log.info("ocrjobs: doc=%s распознано символов=%s", doc_id, n)
        except Exception:
            log.exception("ocrjobs: ошибка OCR doc=%s", doc_id)
            # пометить error, чтобы не крутить бесконечно
            try:
                from .models import LibraryDoc
                d = await db.get(LibraryDoc, doc_id)
                if d is not None and d.ocr_status == "pending":
                    d.ocr_status = "error"
                    await db.commit()
            except Exception:
                pass


async def _run_worker() -> None:
    q = _queue
    assert q is not None
    while True:
        doc_id = await q.get()
        try:
            await _process_one(doc_id)
        except Exception:
            log.exception("ocrjobs: воркер упал на doc=%s", doc_id)
        finally:
            q.task_done()
        # пауза между книгами — не забивать процессор при массовом бэкофилле сканов
        if settings.ocr_book_pause > 0:
            await asyncio.sleep(settings.ocr_book_pause)
