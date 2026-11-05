"""Фоновая обработка иллюстраций из книг библиотеки (фича LIBRARY_FIGURES).

Зачем: вырезать картинки из PDF, подписать зрением и заэмбеддить — тяжело (1 vision-вызов
+ 1 эмбеддинг на КАЖДУЮ фигуру, большой учебник ~минуты). Делать это прямо при одобрении
книги нельзя — админ будет ждать, а бот тормозить. Поэтому:

- одобрение лишь ставит книге figures_status='pending' (мгновенно);
- режим `background` (по умолчанию): книга тут же кладётся в очередь, фоновый воркер режет её
  в фоне ПО ОДНОЙ ЗА РАЗ (чтобы 1 ГБ памяти сервера не перегружать);
- режим `night`: днём ничего не режем, раз в сутки в заданный час (LIBRARY_FIGURES_NIGHT_HOUR)
  все накопившиеся pending-книги ставятся в ту же очередь.

Воркер открывает свою сессию БД (не держит соединение во время vision), статус по итогу:
done / error. Очередь и воркер привязаны к текущему циклу событий (как в limits.py — важно
для тестов, где loop пересоздаётся).
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import logging

from .config import settings

log = logging.getLogger("testroom.figjobs")

_queue: asyncio.Queue[int] | None = None
_worker: asyncio.Task | None = None
_loop = None


def _ensure(loop_check: bool = True):
    """Очередь+воркер для текущего цикла событий (пересоздаёт при смене loop)."""
    global _queue, _worker, _loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if _queue is None or (loop_check and _loop is not loop):
        _queue = asyncio.Queue()
        _worker = None
        _loop = loop
    if _worker is None or _worker.done():
        _worker = asyncio.create_task(_run_worker(), name="figjobs")
    return _queue


def start() -> None:
    """Поднять воркер на текущем цикле (вызывается при старте приложения, если фича включена)."""
    if settings.library_figures_enabled:
        _ensure()


def enqueue(doc_id: int) -> None:
    """Поставить книгу в очередь на извлечение фигур (режим background)."""
    if not settings.library_figures_enabled:
        return
    _ensure().put_nowait(doc_id)


async def _process_one(doc_id: int) -> None:
    from . import db as dbmod
    from . import services as svc
    from .models import LibraryDoc

    async with dbmod.SessionLocal() as db:
        doc = await db.get(LibraryDoc, doc_id)
        if doc is None or doc.status != "approved":
            return
        status = "done"
        n = 0
        try:
            n = await svc.index_doc_figures(db, doc)  # тяжёлая работа; соединение БД не держит
        except Exception:
            log.exception("figjobs: ошибка извлечения фигур doc=%s", doc_id)
            status = "error"
        doc = await db.get(LibraryDoc, doc_id)
        if doc is not None:
            doc.figures_status = status
            await db.commit()
        log.info("figjobs: doc=%s фигур=%s статус=%s", doc_id, n, status)


async def _run_worker() -> None:
    q = _queue
    assert q is not None
    while True:
        doc_id = await q.get()
        try:
            await _process_one(doc_id)
        except Exception:
            log.exception("figjobs: воркер упал на doc=%s", doc_id)
        finally:
            q.task_done()


async def enqueue_pending() -> int:
    """Поставить в очередь все книги со статусом pending (возобновление после рестарта / ночь)."""
    if not settings.library_figures_enabled:
        return 0
    from . import db as dbmod
    from . import services as svc

    async with dbmod.SessionLocal() as db:
        ids = await svc.pending_figure_doc_ids(db)
    for i in ids:
        enqueue(i)
    return len(ids)


def _seconds_until_hour(hour: int) -> float:
    now = _dt.datetime.now()
    target = now.replace(hour=hour % 24, minute=0, second=0, microsecond=0)
    if target <= now:
        target += _dt.timedelta(days=1)
    return (target - now).total_seconds()


async def night_loop() -> None:
    """Режим night: раз в сутки в заданный час ставит накопившиеся pending-книги в очередь.
    В других режимах просыпается, ничего не делает и спит дальше (безвредно)."""
    while True:
        await asyncio.sleep(_seconds_until_hour(settings.library_figures_night_hour))
        if not settings.library_figures_enabled or settings.library_figures_mode != "night":
            continue
        try:
            n = await enqueue_pending()
            if n:
                log.info("figjobs(ночь): поставлено книг в очередь=%s", n)
        except Exception:
            log.exception("figjobs(ночь): ошибка")
