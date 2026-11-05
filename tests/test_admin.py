import httpx
import pytest

from app import services as svc
from app.api import create_app
from app.auth import make_init_data
from app.parsers import ParsedQuestion

from .conftest import ADMIN_ID, TOKEN


def H(uid, act_as=None):
    h = {"X-Init-Data": make_init_data(TOKEN, {"id": uid, "first_name": "U"})}
    if act_as:
        h["X-Act-As"] = str(act_as)
    return h


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://t") as c:
        yield c


async def make_teacher(db, uid, name):
    u = await svc.get_or_create_user(db, uid)
    await svc.set_full_name(db, u, name)
    await svc.request_teacher(db, u, "ТашМИ, анатомия")
    return await svc.decide_teacher(db, uid, True)


async def make_student(db, uid, name):
    u = await svc.get_or_create_user(db, uid)
    await svc.set_full_name(db, u, name)
    return u


async def test_code_bruteforce_limited(db):
    st = await svc.get_or_create_user(db, 900)
    await svc.set_full_name(db, st, "Хакер Хакеров")
    for i in range(svc.JOIN_MAX_FAILS):
        with pytest.raises(svc.ServiceError) as e:
            await svc.join_by_code(db, st, f"{100000 + i}")
        assert e.value.status == 404
    with pytest.raises(svc.ServiceError) as e:
        await svc.join_by_code(db, st, "100099")
    assert e.value.status == 429


async def test_admin_panel_and_act_as(client, db):
    t = await make_teacher(db, 300, "Рахимова Нигора")
    student = await make_student(db, 301, "Студент Студентов")
    subj = await svc.create_subject(db, t, "Анатомия")
    test = await svc.create_test(db, t, subj.id, "Кости", [ParsedQuestion("Q?", ["a", "b"], 0)])
    await svc.get_or_create_user(db, ADMIN_ID)

    # учитель и студент не имеют доступа к админке и к чужим кабинетам
    assert (await client.get("/api/admin/teachers", headers=H(300))).status_code == 403
    assert (await client.get("/api/teacher/subjects", headers=H(301, act_as=300))).status_code == 403

    lst = (await client.get("/api/admin/teachers", headers=H(ADMIN_ID))).json()
    by_id = {r["id"]: r for r in lst}
    assert 301 not in by_id  # студент в списке преподавателей не появляется
    assert by_id[300]["tests"] == 1 and by_id[300]["role"] == "teacher"
    assert (await client.get("/api/admin/teachers?q=рахимова", headers=H(ADMIN_ID))).json()[0]["id"] == 300

    # войти можно только в кабинет преподавателя, не студента
    assert (await client.post("/api/admin/teachers/301/enter", headers=H(ADMIN_ID))).status_code == 404

    # заявка в преподаватели: видна админу сверху, одобрение работает
    applicant = await make_student(db, 302, "Заявка Заявкин")
    await svc.request_teacher(db, applicant, "ТашМИ")
    lst2 = (await client.get("/api/admin/teachers", headers=H(ADMIN_ID))).json()
    assert lst2[0]["id"] == 302 and lst2[0]["status"] == "pending"
    r = await client.post("/api/admin/teachers/302/decide", headers=H(ADMIN_ID), json={"approve": True})
    assert r.json()["role"] == "teacher"

    r = await client.post("/api/admin/teachers/300/pro", headers=H(ADMIN_ID), json={"days": 30})
    assert r.status_code == 200

    # вход в кабинет учителя
    assert (await client.post("/api/admin/teachers/300/enter", headers=H(ADMIN_ID))).status_code == 200
    me = (await client.get("/api/me", headers=H(ADMIN_ID, act_as=300))).json()
    assert me["acting_as"]["id"] == 300 and me["is_admin"] and me["is_teacher"]
    subjects = (await client.get("/api/teacher/subjects", headers=H(ADMIN_ID, act_as=300))).json()
    assert subjects[0]["tests"][0]["title"] == "Кости"
    r = await client.post(
        f"/api/teacher/tests/{test.id}/questions",
        headers=H(ADMIN_ID, act_as=300),
        json={"text": "Добавил админ?", "options": ["да", "нет"], "correct": 0},
    )
    assert r.status_code == 200
    sess = (
        await client.post(
            "/api/teacher/sessions", headers=H(ADMIN_ID, act_as=300), json={"test_id": test.id, "group_name": "101"}
        )
    ).json()
    # запуск принадлежит учителю, а не админу
    live = await client.get(f"/api/teacher/sessions/{sess['id']}/live", headers=H(300))
    assert live.status_code == 200

    # блокировка: учитель не может войти, админ может помочь
    await client.post("/api/admin/teachers/300/block", headers=H(ADMIN_ID), json={"blocked": True})
    assert (await client.get("/api/me", headers=H(300))).status_code == 403
    assert (await client.get("/api/me", headers=H(ADMIN_ID, act_as=300))).status_code == 200
    assert (await client.post("/api/admin/teachers/1/block", headers=H(ADMIN_ID), json={"blocked": True})).status_code == 400

    # снятие роли преподавателя: становится студентом, тесты и история сохраняются
    await client.post("/api/admin/teachers/300/block", headers=H(ADMIN_ID), json={"blocked": False})  # вернём доступ
    r = await client.post("/api/admin/teachers/300/remove", headers=H(ADMIN_ID))
    assert r.status_code == 200
    me300 = (await client.get("/api/me", headers=H(300))).json()
    assert me300["role"] == "student" and not me300["is_teacher"]
    lst3 = (await client.get("/api/admin/teachers", headers=H(ADMIN_ID))).json()
    assert 300 not in {r["id"] for r in lst3}  # больше не в списке преподавателей
    # тесты бывшего преподавателя на месте
    assert (await client.get(f"/api/teacher/tests/{test.id}", headers=H(300))).status_code == 200
    # у админа роль снять нельзя
    assert (await client.post(f"/api/admin/teachers/{ADMIN_ID}/remove", headers=H(ADMIN_ID))).status_code == 400

    log = (await client.get("/api/admin/log", headers=H(ADMIN_ID))).json()
    actions = [x["action"] for x in log]
    for a in ("одобрил заявку", "выдал Pro на 30 дн.", "вошёл в кабинет", "добавил вопрос", "запустил тест", "заблокировал", "снял роль преподавателя"):
        assert a in actions, (a, actions)
    assert all(x["target"] for x in log)
