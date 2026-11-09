"""Ежедневный бэкап базы: целостная копия SQLite и отправка файлом админам."""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import settings

log = logging.getLogger("backup")


def _tz() -> timezone:
    return timezone(timedelta(hours=settings.tz_offset_hours))


def _db_path() -> Path | None:
    """Путь к файлу SQLite из database_url (sqlite+aiosqlite:///./testbot.db)."""
    url = settings.database_url
    if "sqlite" not in url:
        return None  # не SQLite (например, Postgres) — этот бэкап не применим
    tail = url.split(":///", 1)[-1] if ":///" in url else ""
    if not tail:
        return None
    return Path(tail).resolve()


def make_backup() -> tuple[str, bytes] | None:
    """Целостная копия базы через SQLite backup API (корректно учитывает WAL).
    Сжимаем в gzip — иначе большая база не влезает в лимит Telegram (50 МБ)."""
    import gzip

    src = _db_path()
    if src is None or not src.exists():
        return None
    with tempfile.TemporaryDirectory() as tmp:
        dst = Path(tmp) / "backup.db"
        source = sqlite3.connect(str(src))
        try:
            dest = sqlite3.connect(str(dst))
            try:
                source.backup(dest)
                try:
                    dest.execute("VACUUM")  # убрать «пустые» страницы от удалений → файл меньше
                except Exception:
                    pass
            finally:
                dest.close()
        finally:
            source.close()
        raw = dst.read_bytes()
    data = gzip.compress(raw, compresslevel=6)  # БД (текст + индексы) жмётся в разы
    stamp = datetime.now(_tz())
    return f"testbot-backup-{stamp:%Y-%m-%d}.db.gz", data


async def send_backup(bot) -> int:
    """Создаёт бэкап и отправляет всем админам. Возвращает число успешных отправок."""
    res = await asyncio.to_thread(make_backup)
    if not res:
        log.warning("Бэкап не создан: файл базы не найден.")
        return 0
    name, data = res
    from aiogram.types import BufferedInputFile

    mb = len(data) / (1024 * 1024)
    caption = (
        f"🗄 Резервная копия базы (gzip)\n{name} · {mb:.1f} МБ\n"
        "Распаковать: gunzip (или любой архиватор) → получите .db"
    )
    sent = 0
    for admin in settings.admin_ids:
        try:
            await bot.send_document(admin, BufferedInputFile(data, filename=name), caption=caption)
            sent += 1
        except Exception:
            log.exception("Не удалось отправить бэкап админу %s", admin)
    if not sent:
        log.warning("Бэкап не отправлен ни одному админу (возможно, всё ещё >50 МБ: %.1f МБ)", mb)
    return sent


def _seconds_until(hour: int) -> float:
    now = datetime.now(_tz())
    target = now.replace(hour=hour % 24, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def backup_loop(bot):
    """Раз в сутки в заданный час отправляет бэкап админам."""
    if not settings.backup_enabled or not settings.admin_ids:
        return
    while True:
        await asyncio.sleep(_seconds_until(settings.backup_hour))
        try:
            n = await send_backup(bot)
            log.info("Ежедневный бэкап отправлен (%s админам).", n)
        except Exception:
            log.exception("Ошибка ежедневного бэкапа")
        await asyncio.sleep(60)  # не сработать дважды в тот же час
