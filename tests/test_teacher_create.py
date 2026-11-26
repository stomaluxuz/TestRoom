"""Удобное создание тестов преподавателем: генерация ИИ и пустой тест для ручного ввода."""
import httpx
import pytest

from app.api import create_app
from app.auth import make_init_data
from app.config import settings
from app.parsers import ParsedQuestion

from .conftest import ADMIN_ID, TOKEN


def headers(uid, name=None):
    return {"X-Init-Data": make_init_data(TOKEN, {"id": uid, "first_name": name or "U", "username": f"u{uid}"})}


@pytest.fixture
async def client():
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_ai_generate_creates_filled_test(client, monkeypatch):
    """ИИ генерит вопросы по теме → тест сохраняется с этими вопросами."""
    from app import ai

    captured = {}

    async def fake_gen(topic, count=10, lang="ru", context="", strict=False, difficulty="medium"):
        captured.update(topic=topic, count=count, lang=lang, difficulty=difficulty)
        return [
            ParsedQuestion(text=f"Вопрос {i}", options=["а", "б", "в", "г"], correct=0)
            for i in range(count)
        ]

    monkeypatch.setattr(ai, "generate_test_questions", fake_gen)

    T = headers(ADMIN_ID)
    subj = (await client.post("/api/teacher/subjects", headers=T, json={"name": "Гистология"})).json()
    r = await client.post("/api/teacher/tests/generate", headers=T, json={
        "subject_id": subj["id"], "topic": "Эпителий", "count": 3,
        "difficulty": "hard", "lang": "uz",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 3
    assert captured == {"topic": "Эпителий", "count": 3, "lang": "uz", "difficulty": "hard"}

    detail = (await client.get(f"/api/teacher/tests/{body['test_id']}", headers=T)).json()
    assert detail["title"] == "Эпителий"
    assert len(detail["questions"]) == 3


async def test_empty_test_then_manual_fill(client):
    """Пустой тест создаётся без вопросов, затем вопрос добавляется вручную."""
    T = headers(ADMIN_ID)
    subj = (await client.post("/api/teacher/subjects", headers=T, json={"name": "Биохимия"})).json()
    r = await client.post("/api/teacher/tests/empty", headers=T, json={
        "subject_id": subj["id"], "title": "Ферменты",
    })
    assert r.status_code == 200, r.text
    test_id = r.json()["test_id"]

    detail = (await client.get(f"/api/teacher/tests/{test_id}", headers=T)).json()
    assert detail["title"] == "Ферменты"
    assert detail["questions"] == []

    # добавляем вопрос вручную в редакторе
    q = {"text": "Что такое фермент?", "options": ["белок-катализатор", "сахар", "жир", "соль"], "correct": 0}
    assert (await client.post(f"/api/teacher/tests/{test_id}/questions", headers=T, json=q)).status_code == 200
    detail = (await client.get(f"/api/teacher/tests/{test_id}", headers=T)).json()
    assert len(detail["questions"]) == 1


async def test_generate_requires_teacher(client, monkeypatch):
    """Студент не может генерить тесты."""
    from app import ai

    async def fake_gen(*a, **k):
        return [ParsedQuestion(text="x", options=["a", "b"], correct=0)]

    monkeypatch.setattr(ai, "generate_test_questions", fake_gen)
    S = headers(777)
    r = await client.post("/api/teacher/tests/generate", headers=S, json={
        "subject_id": 1, "topic": "Тема", "count": 2,
    })
    assert r.status_code == 403
