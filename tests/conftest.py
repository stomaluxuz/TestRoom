import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db as dbmod  # noqa: E402
from app.config import settings  # noqa: E402

TOKEN = "123456:TEST-TOKEN"
ADMIN_ID = 1


@pytest.fixture(autouse=True)
async def fresh_db(tmp_path):
    settings.bot_token = TOKEN
    settings.admin_ids = {ADMIN_ID}
    settings.dev_auth = False
    settings.free_max_sessions_per_day = 1
    settings.free_max_students = 30
    settings.free_max_pres_per_week = 0  # по умолчанию без лимита в тестах; отдельный тест включает
    settings.tz_offset_hours = 5
    settings.anthropic_api_key = ""
    settings.voyage_api_key = ""  # RAG по умолчанию выключен в тестах (без сети)
    url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    settings.database_url = url
    settings.library_dir = str(tmp_path / "library")  # файлы библиотеки — во временную папку теста
    from app import services as svc
    svc.clear_caches()
    engine = dbmod.configure(url)
    await dbmod.init_db()
    async with dbmod.SessionLocal() as s:
        await svc.set_settings(s, {"welcome_bonus": 0})  # в тестах новый пользователь стартует с 0
    yield
    await engine.dispose()


@pytest.fixture
async def db():
    async with dbmod.SessionLocal() as s:
        yield s
