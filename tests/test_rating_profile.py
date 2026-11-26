"""Профиль для рейтинга: вуз, номер группы и видимость в рейтинге."""
import httpx
import pytest

from app.api import create_app
from app.auth import make_init_data

from .conftest import TOKEN


def headers(uid, name=None):
    return {"X-Init-Data": make_init_data(TOKEN, {"id": uid, "first_name": name or "U", "username": f"u{uid}"})}


@pytest.fixture
async def client():
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_defaults(client):
    """Новый пользователь: вуз/группа пустые, в рейтинге скрыт по умолчанию (opt-in)."""
    me = (await client.get("/api/me", headers=headers(600))).json()
    assert me["university"] is None
    assert me["study_group"] is None
    assert me["rating_public"] is False


UNI = "Ташкентский государственный стоматологический институт (ТГСИ)"


async def test_set_university_and_group(client):
    S = headers(601)
    r = await client.post("/api/me/student-profile", headers=S, json={
        "university": UNI, "study_group": "  101  ",
    })
    assert r.status_code == 200
    me = (await client.get("/api/me", headers=S)).json()
    assert me["university"] == UNI
    assert me["study_group"] == "101"  # схлопнутые пробелы


async def test_university_must_be_from_list(client):
    """Произвольный (не из списка) вуз отклоняется — чтобы рейтинг не дробился."""
    S = headers(604)
    r = await client.post("/api/me/student-profile", headers=S, json={
        "university": "Мой домашний вуз", "study_group": "101",
    })
    assert r.status_code >= 400
    me = (await client.get("/api/me", headers=S)).json()
    assert me["university"] is None  # ничего не сохранилось


async def test_empty_clears_fields(client):
    S = headers(602)
    await client.post("/api/me/student-profile", headers=S, json={"university": UNI, "study_group": "5"})
    await client.post("/api/me/student-profile", headers=S, json={"university": "", "study_group": ""})
    me = (await client.get("/api/me", headers=S)).json()
    assert me["university"] is None and me["study_group"] is None


async def test_rating_visibility_toggle(client):
    S = headers(603)
    assert (await client.post("/api/me/rating", headers=S, json={"public": False})).json()["rating_public"] is False
    assert (await client.get("/api/me", headers=S)).json()["rating_public"] is False
    assert (await client.post("/api/me/rating", headers=S, json={"public": True})).json()["rating_public"] is True
    assert (await client.get("/api/me", headers=S)).json()["rating_public"] is True
