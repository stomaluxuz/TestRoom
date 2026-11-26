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
    """Новый пользователь: вуз/группа пустые, в рейтинге виден по умолчанию."""
    me = (await client.get("/api/me", headers=headers(600))).json()
    assert me["university"] is None
    assert me["study_group"] is None
    assert me["rating_public"] is True


async def test_set_university_and_group(client):
    S = headers(601)
    r = await client.post("/api/me/student-profile", headers=S, json={
        "university": "  Ташкентский   институт  ", "study_group": "  101  ",
    })
    assert r.status_code == 200
    me = (await client.get("/api/me", headers=S)).json()
    assert me["university"] == "Ташкентский институт"  # схлопнутые пробелы
    assert me["study_group"] == "101"


async def test_empty_clears_fields(client):
    S = headers(602)
    await client.post("/api/me/student-profile", headers=S, json={"university": "Вуз", "study_group": "5"})
    await client.post("/api/me/student-profile", headers=S, json={"university": "", "study_group": ""})
    me = (await client.get("/api/me", headers=S)).json()
    assert me["university"] is None and me["study_group"] is None


async def test_rating_visibility_toggle(client):
    S = headers(603)
    assert (await client.post("/api/me/rating", headers=S, json={"public": False})).json()["rating_public"] is False
    assert (await client.get("/api/me", headers=S)).json()["rating_public"] is False
    assert (await client.post("/api/me/rating", headers=S, json={"public": True})).json()["rating_public"] is True
    assert (await client.get("/api/me", headers=S)).json()["rating_public"] is True
