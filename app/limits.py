"""Очередь генераций и замер времени.

- gen_slot(): ограничивает число ОДНОВРЕМЕННЫХ генераций (презентация/тест), чтобы сервер
  (1 ГБ) не падал при наплыве. Лишние запросы ждут в очереди (settings.max_concurrent_gen).
- queued(): True, если прямо сейчас все слоты заняты (чтобы показать «вы в очереди»).
- timing(): контекст замера; пишет в лог, сколько заняла фаза (видно в journalctl).
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from .config import settings

log = logging.getLogger("testroom.gen")

_sem: asyncio.Semaphore | None = None
_loop = None


def _get() -> asyncio.Semaphore:
    """Семафор, привязанный к текущему циклу событий (пересоздаётся при смене loop — важно для тестов)."""
    global _sem, _loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if _sem is None or _loop is not loop:
        _sem = asyncio.Semaphore(max(1, settings.max_concurrent_gen))
        _loop = loop
    return _sem


def queued() -> bool:
    """Сейчас все слоты заняты → следующий запрос встанет в очередь."""
    return _get().locked()


def gen_slot() -> asyncio.Semaphore:
    """`async with gen_slot():` — занять слот генерации (ждёт, если занято)."""
    return _get()


@asynccontextmanager
async def timing(label: str):
    """`async with timing('photos'):` — логирует длительность фазы."""
    t0 = time.monotonic()
    try:
        yield
    finally:
        log.info("timing %s: %.1fs", label, time.monotonic() - t0)
