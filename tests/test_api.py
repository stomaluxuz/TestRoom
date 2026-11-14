import io
import time

import httpx
import pytest

from app.api import create_app
from app.auth import AuthError, make_init_data, validate_init_data
from app.config import settings
from app.parsers import template_docx

from .conftest import ADMIN_ID, TOKEN


def headers(uid, name=None):
    return {"X-Init-Data": make_init_data(TOKEN, {"id": uid, "first_name": name or "U", "username": f"u{uid}"})}


@pytest.fixture
async def client():
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def test_init_data_validation():
    data = make_init_data(TOKEN, {"id": 42})
    assert validate_init_data(data, TOKEN)["id"] == 42
    with pytest.raises(AuthError):
        validate_init_data(data, "999:OTHER")
    with pytest.raises(AuthError):
        validate_init_data(data.replace("42", "43"), TOKEN)  # подмена ID
    old = make_init_data(TOKEN, {"id": 42}, auth_date=int(time.time()) - 3 * 86400)
    with pytest.raises(AuthError):
        validate_init_data(old, TOKEN)
    with pytest.raises(AuthError):
        validate_init_data("", TOKEN)


async def test_unauthorized(client):
    r = await client.get("/api/me")
    assert r.status_code == 401
    r = await client.get("/api/me", headers={"X-Init-Data": "user=%7B%22id%22%3A1%7D&hash=bad"})
    assert r.status_code == 401
    # dev-вход выключен по умолчанию
    r = await client.get("/api/me", headers={"X-Dev-User": "1"})
    assert r.status_code == 401


async def test_ai_presentation_endpoint(client, monkeypatch):
    """Форма презентации: выбор книг только Pro+; без книг — очередь + списание."""
    from app import api as apimod
    from app import db as dbmod
    from app import services as svc

    calls = []

    async def fake_run(*a, **k):
        calls.append(a)

    monkeypatch.setattr(apimod, "_run_presentation", fake_run)

    H = headers(900)
    await client.post("/api/me/name", headers=H, json={"full_name": "Студент Один"})
    async with dbmod.SessionLocal() as db:
        u = await svc.get_or_create_user(db, 900)
        u.balance = 100000  # цена презентации 5000
        await db.commit()

    # обычный студент с выбором книг → только Pro+
    r = await client.post("/api/ai/presentation", headers=H, json={"topic": "Кариес", "book_ids": [1, 2]})
    assert r.status_code == 402

    # без книг — ставится в очередь, списано 5000
    r = await client.post("/api/ai/presentation", headers=H, json={"topic": "Кариес", "slides": 8})
    assert r.status_code == 200 and r.json().get("queued") is True
    assert len(calls) == 1
    async with dbmod.SessionLocal() as db:
        assert (await svc.get_or_create_user(db, 900)).balance == 95000


async def test_quiz_endpoints_flow(client, monkeypatch):
    """Живой куиз через HTTP: учитель создаёт (ИИ замокан), студент входит, играет, финал."""
    from app import ai as aimod
    from app.parsers import ParsedQuestion

    async def fake_gen(topic, count=10, lang="ru", **kw):
        return [
            ParsedQuestion("2+2?", ["3", "4", "5"], 1),
            ParsedQuestion("Небо?", ["Синее", "Зелёное"], 0),
        ]

    monkeypatch.setattr(aimod, "generate_test_questions", fake_gen)

    T = headers(ADMIN_ID)  # админ = преподаватель-ведущий
    r = await client.post("/api/quiz/create", headers=T, json={"topic": "Разное", "count": 5, "seconds": 20})
    assert r.status_code == 200
    game = r.json()
    assert len(game["pin"]) == 6 and game["total"] == 2

    # студент без ФИО не войдёт
    S = headers(950)
    assert (await client.post("/api/quiz/join", headers=S, json={"pin": game["pin"]})).status_code == 409
    await client.post("/api/me/name", headers=S, json={"full_name": "Игрок Один"})
    j = (await client.post("/api/quiz/join", headers=S, json={"pin": game["pin"]})).json()
    assert j["game_id"] == game["game_id"]

    gid, pid = game["game_id"], j["player_id"]
    # не ведущий не управляет
    assert (await client.post(f"/api/quiz/{gid}/next", headers=S)).status_code == 403

    # лобби → вопрос
    host = (await client.post(f"/api/quiz/{gid}/next", headers=T)).json()
    assert host["phase"] == "question"
    play = (await client.get(f"/api/quiz/{gid}/play?player_id={pid}", headers=S)).json()
    assert play["phase"] == "question" and "correct" not in play["question"]

    ans = (await client.post(f"/api/quiz/{gid}/answer?player_id={pid}", headers=S,
                             json={"q_index": 0, "option": 1})).json()
    assert ans["correct"] is True and ans["points"] >= 500

    host = (await client.post(f"/api/quiz/{gid}/next", headers=T)).json()  # reveal
    assert host["phase"] == "reveal" and host["correct"] == 1
    # до конца
    await client.post(f"/api/quiz/{gid}/next", headers=T)  # вопрос 1
    await client.post(f"/api/quiz/{gid}/next", headers=T)  # reveal 1
    end = (await client.post(f"/api/quiz/{gid}/next", headers=T)).json()  # ended
    assert end["phase"] == "ended" and end["podium"][0]["name"] == "Игрок Один"


async def test_support_forwards_to_admin(client, monkeypatch):
    """Кнопка поддержки: сообщение уходит админам в Telegram с данными пользователя."""
    from app import api as apimod

    sent = []

    class FakeBot:
        async def send_message(self, chat_id, text, parse_mode=None):
            sent.append((chat_id, text))

    monkeypatch.setattr(apimod.bot_ref, "bot", FakeBot())

    H = headers(960, name="Проблемный Юзер")
    await client.post("/api/me/name", headers=H, json={"full_name": "Проблемный Юзер"})
    # пустое сообщение — отказ
    assert (await client.post("/api/support", headers=H, json={"text": "  "})).status_code == 400
    r = await client.post("/api/support", headers=H, json={"text": "Не работает тест"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert sent and sent[0][0] == ADMIN_ID and "Не работает тест" in sent[0][1]
    assert "id 960" in sent[0][1]


async def test_lang_sync(client):
    """Язык из Mini App сохраняется в БД — общий с ботом."""
    H = headers(900)
    assert (await client.get("/api/me", headers=H)).json()["lang"] == "ru"  # по умолчанию
    r = await client.post("/api/me/lang", headers=H, json={"lang": "uz"})
    assert r.status_code == 200 and r.json()["lang"] == "uz"
    assert (await client.get("/api/me", headers=H)).json()["lang"] == "uz"  # сохранилось
    # некорректное значение → откат к ru
    r = await client.post("/api/me/lang", headers=H, json={"lang": "xx"})
    assert r.json()["lang"] == "ru"


async def test_static_and_health(client):
    assert (await client.get("/health")).json() == {"ok": True}
    r = await client.get("/")
    assert r.status_code == 200 and "TestRoom" in r.text
    assert (await client.get("/static/app.js")).status_code == 200


async def test_end_to_end(client):
    T = headers(ADMIN_ID)  # админ = преподаватель
    me = (await client.get("/api/me", headers=T)).json()
    assert me["is_teacher"] and me["is_admin"] and me["full_name"] is None
    assert (await client.post("/api/me/name", headers=T, json={"full_name": "Рахимова Нигора"})).status_code == 200

    # студент видит свои предметы, но не может создать комнату для группы
    S = headers(500)
    assert (await client.get("/api/teacher/subjects", headers=S)).status_code == 200
    r = await client.post("/api/teacher/sessions", headers=S, json={"test_id": 1, "group_name": "101"})
    assert r.status_code == 403

    subj = (await client.post("/api/teacher/subjects", headers=T, json={"name": "Анатомия"})).json()

    bad = b"1. A?\n+ a\n- b\n2. B?\n- a\n- b\n"
    r = await client.post(
        "/api/teacher/tests/upload",
        headers=T,
        data={"subject_id": subj["id"], "title": "Т1"},
        files={"file": ("t.txt", bad, "text/plain")},
    )
    body = r.json()
    assert body["saved"] is False and body["valid"] == 1 and body["errors"][0]["number"] == 2
    r = await client.post(
        "/api/teacher/tests/upload",
        headers=T,
        data={"subject_id": subj["id"], "title": "Т1", "save_valid": "true"},
        files={"file": ("t.txt", bad, "text/plain")},
    )
    assert r.json()["saved"] is True

    r = await client.post(
        "/api/teacher/tests/upload",
        headers=T,
        data={"subject_id": subj["id"], "title": "Кости"},
        files={"file": ("t.docx", template_docx(), "application/octet-stream")},
    )
    test_id = r.json()["test_id"]
    r = await client.post(
        f"/api/teacher/tests/{test_id}/questions",
        headers=T,
        json={"text": "Третий?", "options": ["да", "нет"], "correct": 0},
    )
    assert r.status_code == 200
    detail = (await client.get(f"/api/teacher/tests/{test_id}", headers=T)).json()
    assert len(detail["questions"]) == 3

    # переименование теста
    r = await client.patch(f"/api/teacher/tests/{test_id}", headers=T, json={"title": "Кости скелета 2"})
    assert r.status_code == 200 and r.json()["title"] == "Кости скелета 2"
    detail = (await client.get(f"/api/teacher/tests/{test_id}", headers=T)).json()
    assert detail["title"] == "Кости скелета 2"

    r = await client.post(
        "/api/teacher/sessions",
        headers=T,
        json={"test_id": test_id, "group_name": "101", "duration_min": 30, "question_count": 3},
    )
    sess = r.json()
    code = sess["code"]

    # студент без ФИО не может войти
    r = await client.post("/api/student/join", headers=S, json={"code": code})
    assert r.status_code == 409
    await client.post("/api/me/name", headers=S, json={"full_name": "Каримов Азиз"})
    st = (await client.post("/api/student/join", headers=S, json={"code": code})).json()
    assert st["status"] == "active" and st["total"] == 3
    # другой студент не может отвечать за него
    r = await client.get(f"/api/student/attempts/{st['attempt_id']}", headers=headers(501))
    assert r.status_code == 404

    st = (await client.post(f"/api/student/attempts/{st['attempt_id']}/leave", headers=S, json={"seconds": 4})).json()
    assert st["leaves"] == 1
    while st["status"] == "active":
        st = (
            await client.post(
                f"/api/student/attempts/{st['attempt_id']}/answer",
                headers=S,
                json={"question_id": st["question"]["id"], "option_index": 0},
            )
        ).json()
    assert st["status"] == "finished" and st["reason"] == "done"
    # карточка результата рендерится (503 = дошли до отправки, упёрлись лишь в отсутствие бота)
    r = await client.post(f"/api/student/attempts/{st['attempt_id']}/share", headers=S, json={})
    assert r.status_code == 503

    live = (await client.get(f"/api/teacher/sessions/{sess['id']}/live", headers=T)).json()
    assert live["finished_count"] == 1 and live["students"][0]["leaves"] == 1
    assert (await client.post(f"/api/teacher/sessions/{sess['id']}/finish", headers=T)).status_code == 200
    res = (await client.get(f"/api/teacher/sessions/{sess['id']}/results", headers=T)).json()
    assert res["ranking"][0]["name"] == "Каримов Азиз"
    r = await client.get(f"/api/teacher/sessions/{sess['id']}/export.xlsx", headers=T)
    assert r.status_code == 200 and r.content[:2] == b"PK"
    # без бота отправка в чат даёт понятную ошибку
    r = await client.post(f"/api/teacher/sessions/{sess['id']}/export", headers=T)
    assert r.status_code == 503
    hist = (await client.get("/api/student/history", headers=S)).json()
    assert hist[0]["finished"] is True


async def test_workplace_edit(client):
    T = headers(ADMIN_ID)  # админ = преподаватель
    await client.post("/api/me/name", headers=T, json={"full_name": "Учитель Профиль"})
    r = await client.post("/api/me/workplace", headers=T, json={"info": "  ТГСИ "})
    assert r.status_code == 200 and r.json()["teacher_info"] == "ТГСИ"
    me = (await client.get("/api/me", headers=T)).json()
    assert me["teacher_info"] == "ТГСИ"
    # студент не может менять место работы
    S = headers(800)
    await client.post("/api/me/name", headers=S, json={"full_name": "Студент Профиль"})
    assert (await client.post("/api/me/workplace", headers=S, json={"info": "Вуз"})).status_code == 403


async def test_delete_test_endpoint(client):
    T = headers(ADMIN_ID)
    await client.post("/api/me/name", headers=T, json={"full_name": "Учитель Тест"})
    subj = (await client.post("/api/teacher/subjects", headers=T, json={"name": "X"})).json()
    r = await client.post(
        "/api/teacher/tests/upload",
        headers=T,
        data={"subject_id": subj["id"], "title": "Удаляемый"},
        files={"file": ("t.docx", template_docx(), "application/octet-stream")},
    )
    test_id = r.json()["test_id"]
    assert (await client.delete(f"/api/teacher/tests/{test_id}", headers=T)).status_code == 200
    assert (await client.get(f"/api/teacher/tests/{test_id}", headers=T)).status_code == 404


async def test_upload_bad_file(client):
    T = headers(ADMIN_ID)
    await client.post("/api/me/name", headers=T, json={"full_name": "Учитель Тест"})
    subj = (await client.post("/api/teacher/subjects", headers=T, json={"name": "X"})).json()
    r = await client.post(
        "/api/teacher/tests/upload",
        headers=T,
        data={"subject_id": subj["id"], "title": "T"},
        files={"file": ("t.pdf", b"%PDF", "application/pdf")},
    )
    assert r.status_code == 400 and "docx" in r.json()["detail"]


async def test_dev_auth(client):
    settings.dev_auth = True
    r = await client.get("/api/me", headers={"X-Dev-User": "777"})
    assert r.status_code == 200 and r.json()["id"] == 777
