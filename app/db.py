"""Подключение к базе данных."""
import os

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    is_sqlite = url.startswith("sqlite")
    # SQLite пишет только одним соединением за раз, поэтому по умолчанию держим
    # одно соединение: запросы встают в очередь, а не мешают друг другу.
    pool_size = int(os.getenv("DB_POOL_SIZE", "1" if is_sqlite else "20"))
    kwargs = {"pool_size": pool_size, "max_overflow": 0 if is_sqlite else 20, "pool_timeout": 60}
    if is_sqlite:
        kwargs["connect_args"] = {"timeout": 30}
    engine = create_async_engine(url, **kwargs)

    if is_sqlite:
        @event.listens_for(engine.sync_engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")  # чтение не блокирует запись
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return engine


engine = make_engine(settings.database_url)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def configure(url: str):
    """Переключить базу (используется в тестах)."""
    global engine, SessionLocal
    engine = make_engine(url)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return engine


def _migrate(conn):
    """Лёгкие миграции для уже существующих баз (create_all не меняет таблицы)."""
    from sqlalchemy import inspect, text

    insp = inspect(conn)
    cols = {c["name"] for c in insp.get_columns("users")}
    if "role" not in cols:
        conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(16) NOT NULL DEFAULT 'student'"))
        if "teacher_status" in cols:  # старые преподаватели (одобренные) → роль teacher
            conn.execute(text("UPDATE users SET role='teacher' WHERE teacher_status='approved'"))
    if "teacher_pending" not in cols:
        conn.execute(text("ALTER TABLE users ADD COLUMN teacher_pending BOOLEAN NOT NULL DEFAULT 0"))
    if "teacher_status" in cols:
        # Устаревшая колонка: она NOT NULL без умолчания на уровне БД и ломает
        # вставку новых пользователей (ORM её больше не заполняет). Удаляем.
        try:
            conn.execute(text("ALTER TABLE users DROP COLUMN teacher_status"))
        except Exception:
            # старый SQLite без DROP COLUMN — хотя бы разрешим NULL/зададим умолчание
            try:
                conn.execute(text("UPDATE users SET teacher_status='none' WHERE teacher_status IS NULL"))
            except Exception:
                pass
    if "teacher_kafedra" not in cols:
        conn.execute(text("ALTER TABLE users ADD COLUMN teacher_kafedra TEXT"))
    if "pres_count" not in cols:
        conn.execute(text("ALTER TABLE users ADD COLUMN pres_count INTEGER NOT NULL DEFAULT 0"))
    if "pres_total" not in cols:
        conn.execute(text("ALTER TABLE users ADD COLUMN pres_total INTEGER NOT NULL DEFAULT 0"))
    if "pres_date" not in cols:
        conn.execute(text("ALTER TABLE users ADD COLUMN pres_date DATE"))
    if "balance" not in cols:
        conn.execute(text("ALTER TABLE users ADD COLUMN balance INTEGER NOT NULL DEFAULT 0"))
    if "proplus_until" not in cols:
        conn.execute(text("ALTER TABLE users ADD COLUMN proplus_until DATETIME"))
    if "lang" not in cols:
        conn.execute(text("ALTER TABLE users ADD COLUMN lang VARCHAR(2) NOT NULL DEFAULT 'ru'"))
    if insp.has_table("library_docs"):
        dcols = {c["name"] for c in insp.get_columns("library_docs")}
        if "figures_status" not in dcols:
            conn.execute(text("ALTER TABLE library_docs ADD COLUMN figures_status VARCHAR(16)"))
        if "book_title" not in dcols:
            conn.execute(text("ALTER TABLE library_docs ADD COLUMN book_title TEXT"))
        if "has_cover" not in dcols:
            conn.execute(text("ALTER TABLE library_docs ADD COLUMN has_cover BOOLEAN NOT NULL DEFAULT 0"))
        if "ocr_status" not in dcols:
            conn.execute(text("ALTER TABLE library_docs ADD COLUMN ocr_status VARCHAR(16)"))
    scols = {c["name"] for c in insp.get_columns("sessions")}
    if "solo" not in scols:
        conn.execute(text("ALTER TABLE sessions ADD COLUMN solo BOOLEAN NOT NULL DEFAULT 0"))
    if "join_window_min" not in scols:
        # у старых сессий окна не было (0 — приём открыт весь тест)
        conn.execute(text("ALTER TABLE sessions ADD COLUMN join_window_min INTEGER NOT NULL DEFAULT 0"))
    if insp.has_table("quiz_players"):
        qcols = {c["name"] for c in insp.get_columns("quiz_players")}
        if "emoji" not in qcols:  # эмодзи-аватар игрока (как в Kahoot)
            conn.execute(text("ALTER TABLE quiz_players ADD COLUMN emoji VARCHAR(8) NOT NULL DEFAULT ''"))


def _sqlite_file(url: str) -> str | None:
    if not url.startswith("sqlite") or ":///" not in url:
        return None
    return url.split(":///", 1)[-1] or None


def seed_if_missing():
    """Первый запуск на новом хостинге (пустой том): развернуть базу из вшитого seed-файла.
    Если файл базы уже есть — ничего не трогаем, живые данные в безопасности."""
    import shutil
    from pathlib import Path

    seed = os.getenv("SEED_DB")  # сид включается ТОЛЬКО явным SEED_DB (на хостинге); в тестах его нет
    if not seed:
        return
    target = _sqlite_file(settings.database_url)
    if not target:
        return
    tp = Path(target)
    if tp.exists() and tp.stat().st_size > 0:
        return
    sp = Path(seed)
    if sp.exists() and sp.stat().st_size > 0:
        tp.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(sp, tp)


DEFAULT_LIBRARY_SUBJECTS = [
    "Терапевтическая стоматология",
    "Хирургическая стоматология",
    "Ортопедическая стоматология",
    "Ортодонтия",
    "Детская стоматология",
    "Пародонтология",
    "Анатомия",
    "Гистология",
    "Фармакология",
    "Пропедевтика",
]


async def _seed_library_subjects():
    """Засеять фиксированный список предметов библиотеки, если он пуст."""
    from sqlalchemy import func, select

    from .models import LibrarySubject

    async with SessionLocal() as db:
        n = await db.scalar(select(func.count()).select_from(LibrarySubject))
        if n:
            return
        for i, name in enumerate(DEFAULT_LIBRARY_SUBJECTS):
            db.add(LibrarySubject(name=name, position=i))
        await db.commit()


async def init_db():
    import os

    from . import models  # noqa: F401  регистрирует таблицы

    seed_if_missing()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate)
    await _seed_library_subjects()
    try:
        os.makedirs(settings.library_dir, exist_ok=True)  # папка для файлов библиотеки
    except OSError:
        pass


def get_sessionmaker():
    return SessionLocal
