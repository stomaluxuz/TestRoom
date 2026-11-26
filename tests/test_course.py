from app import course as coursemod
from app import services as svc

from .conftest import ADMIN_ID


async def test_course_build_and_progress(db, monkeypatch):
    """Силлабус → темы → ИИ генерит теорию+тест по каждой → прогресс студента."""
    from app import ai as aimod
    from app import services as svcmod
    from app.parsers import ParsedQuestion

    async def fake_theory(topic, course_title="", lang="ru", context=""):
        return f"Конспект по теме {topic}. Главное: ..."

    async def fake_qs(topic, count=10, lang="ru", context="", **kw):
        return [ParsedQuestion(f"{topic} — вопрос {i}?", ["верно", "нет", "мимо"], 0) for i in range(3)]

    async def fake_ctx(db, query, **kw):
        return {"context": "", "sources": [], "found": False}

    monkeypatch.setattr(aimod, "generate_theory", fake_theory)
    monkeypatch.setattr(aimod, "generate_test_questions", fake_qs)
    monkeypatch.setattr(svcmod, "library_context", fake_ctx)

    admin = await svc.get_or_create_user(db, ADMIN_ID)
    course = await coursemod.create_course(db, admin, "Анатомия", "3 курс", "ru", ["Череп", "Позвоночник"])
    cid = course.id
    assert course.status == "building"

    await coursemod.build_course(cid)  # фоновая сборка — синхронно в тесте
    db.expire_all()  # сброс кэша сессии (в реале у каждого запроса своя сессия)
    admin = await svc.get_or_create_user(db, ADMIN_ID)  # свежий объект после expire_all

    detail = await coursemod.course_detail(db, admin, cid)
    assert detail["status"] == "ready" and len(detail["topics"]) == 2
    assert all(t["status"] == "done" and t["has_test"] for t in detail["topics"])

    tid = detail["topics"][0]["id"]
    td = await coursemod.topic_detail(db, admin, tid)
    assert "Конспект" in td["theory"] and len(td["questions"]) == 3

    await coursemod.mark_read(db, admin, tid)
    r = await coursemod.submit_topic_test(db, admin, tid, 2, 3)
    assert r["best_correct"] == 2 and r["best_total"] == 3
    # лучший результат не ухудшается более слабой попыткой
    r2 = await coursemod.submit_topic_test(db, admin, tid, 1, 3)
    assert r2["best_correct"] == 2

    td2 = await coursemod.topic_detail(db, admin, tid)
    assert td2["read"] is True and td2["best_correct"] == 2

    # курс виден в списке для студентов (ready + published)
    assert any(c["id"] == cid for c in await coursemod.list_courses(db))


async def test_create_course_needs_topics(db):
    admin = await svc.get_or_create_user(db, ADMIN_ID)
    try:
        await coursemod.create_course(db, admin, "Пустой", "", "ru", [])
        assert False, "ожидалась ошибка"
    except svc.ServiceError as e:
        assert e.status == 400
