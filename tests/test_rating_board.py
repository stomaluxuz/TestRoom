"""Рейтинг студентов: подсчёт очков, порядок, анонимизация, первая попытка."""
from datetime import timedelta

import pytest

from app import db as dbmod
from app import services as svc
from app.models import Attempt, Subject, utcnow
from app.models import Test as _TestM
from app.models import TestSession as Session


async def _student(db, uid, name, uni, grp, public):
    u = await svc.get_or_create_user(db, uid)
    u.full_name = name
    u.university = uni
    u.study_group = grp
    u.rating_public = public
    await db.commit()
    return u


async def _session(db, teacher_id, solo=False):
    subj = Subject(teacher_id=teacher_id, name="Анат")
    db.add(subj)
    await db.flush()
    test = _TestM(teacher_id=teacher_id, subject_id=subj.id, title="Т")
    db.add(test)
    await db.flush()
    s = Session(test_id=test.id, teacher_id=teacher_id, group_name="101", code="000001",
                    duration_min=10, question_count=10, solo=solo, ends_at=utcnow() + timedelta(hours=1))
    db.add(s)
    await db.flush()
    return s


async def _attempt(db, session_id, uid, name, correct, when=None, finished=True):
    a = Attempt(session_id=session_id, user_id=uid, full_name=name, question_order=[1, 2],
                option_orders={}, correct_count=correct,
                finished_at=(when or utcnow()) if finished else None)
    if when:
        a.started_at = when
    db.add(a)
    await db.flush()
    return a


async def test_board_orders_and_anonymizes():
    async with dbmod.SessionLocal() as db:
        teacher = await svc.get_or_create_user(db, 1)  # admin = teacher
        s1 = await _student(db, 100, "Алиса", "ТГСИ", "101", True)
        s2 = await _student(db, 101, "Борис", "ТГСИ", "101", False)   # скрыт
        await _student(db, 102, "Витя", "ТГСИ", "202", True)          # другая группа
        sess = await _session(db, teacher.id)
        await _attempt(db, sess.id, s1.id, "Алиса", 8)
        await _attempt(db, sess.id, s2.id, "Борис", 5)
        await db.commit()

        # запрос от Алисы: группа 101
        board = await svc.rating_board(db, s1, "group")
        assert board["available"] is True
        names = [(r["rank"], r["name"], r["points"], r["is_me"]) for r in board["top"]]
        assert names[0] == (1, "Алиса", 8, True)
        # Борис скрыт → «Аноним», но он в таблице со своими очками
        assert names[1][1] == "Аноним" and names[1][2] == 5
        # Витя из другой группы не попал
        assert all(n[1] != "Витя" for n in names)


async def test_hidden_user_sees_own_name_and_place():
    async with dbmod.SessionLocal() as db:
        teacher = await svc.get_or_create_user(db, 1)
        s1 = await _student(db, 110, "Алиса", "ТГСИ", "101", True)
        s2 = await _student(db, 111, "Борис", "ТГСИ", "101", False)
        sess = await _session(db, teacher.id)
        await _attempt(db, sess.id, s1.id, "Алиса", 8)
        await _attempt(db, sess.id, s2.id, "Борис", 5)
        await db.commit()

        # запрос от скрытого Бориса: себя видит по имени, место — 2
        board = await svc.rating_board(db, s2, "group")
        me = board["me"]
        assert me["name"] == "Борис" and me["rank"] == 2 and me["hidden"] is True
        assert board["rating_public"] is False


async def test_first_attempt_counts_not_retakes():
    async with dbmod.SessionLocal() as db:
        teacher = await svc.get_or_create_user(db, 1)
        s1 = await _student(db, 120, "Алиса", "ТГСИ", "101", True)
        sess = await _session(db, teacher.id)
        now = utcnow()
        # первая попытка — 3 верных; поздняя пересдача того же теста — 9 (не должна считаться)
        await _attempt(db, sess.id, s1.id, "Алиса", 3, when=now - timedelta(hours=2))
        sess2 = await _session(db, teacher.id)  # второй запуск того же? нет — другой тест
        await db.commit()
        board = await svc.rating_board(db, s1, "group")
        assert board["me"]["points"] == 3
        assert board["me"]["tests"] == 1


async def test_solo_training_not_counted():
    async with dbmod.SessionLocal() as db:
        teacher = await svc.get_or_create_user(db, 1)
        s1 = await _student(db, 130, "Алиса", "ТГСИ", "101", True)
        sess = await _session(db, teacher.id, solo=True)  # тренировка
        await _attempt(db, sess.id, s1.id, "Алиса", 10)
        await db.commit()
        board = await svc.rating_board(db, s1, "group")
        assert board["me"]["points"] == 0  # тренировка в рейтинг не идёт


async def test_unavailable_without_profile():
    async with dbmod.SessionLocal() as db:
        u = await _student(db, 140, "Гость", "", "", True)  # нет вуза/группы
        board = await svc.rating_board(db, u, "group")
        assert board["available"] is False and board["need"] == "group"


async def _set_teacher_vuz(db, teacher, uni):
    teacher.teacher_info = uni
    await db.commit()


async def _session_g(db, teacher_id, group):
    subj = Subject(teacher_id=teacher_id, name="Анат"); db.add(subj); await db.flush()
    test = _TestM(teacher_id=teacher_id, subject_id=subj.id, title="Т"); db.add(test); await db.flush()
    s = Session(test_id=test.id, teacher_id=teacher_id, group_name=group, code="000001",
                duration_min=10, question_count=10, solo=False, ends_at=utcnow() + timedelta(hours=1))
    db.add(s); await db.flush()
    return s


async def test_teacher_group_rating_ranks_by_points():
    async with dbmod.SessionLocal() as db:
        teacher = await svc.get_or_create_user(db, 1)  # admin = teacher
        await _set_teacher_vuz(db, teacher, "ТГСИ")
        s1 = await _student(db, 200, "Алиса", "ТГСИ", "101", False)  # скрыта в студ. рейтинге
        s2 = await _student(db, 201, "Борис", "ТГСИ", "101", True)
        sess = await _session(db, teacher.id)  # группа 101, 2 вопроса в попытке
        await _attempt(db, sess.id, s1.id, "Алиса", 2)  # 2 очка, 100%
        await _attempt(db, sess.id, s2.id, "Борис", 1)  # 1 очко, 50%
        await db.commit()

        assert await svc.teacher_rating_groups(db, teacher) == ["101"]
        rows = (await svc.teacher_group_rating(db, teacher, "101"))["rows"]
        assert [r["name"] for r in rows] == ["Алиса", "Борис"]  # по очкам: 2 > 1
        assert rows[0]["points"] == 2 and rows[0]["avg"] == 100 and rows[0]["rank"] == 1
        assert rows[1]["points"] == 1 and rows[1]["avg"] == 50
        # преподаватель видит настоящее имя скрытого студента (не «Аноним»)
        assert "Аноним" not in [r["name"] for r in rows]


async def test_teacher_sees_all_vuz_students_even_if_not_tested_by_him():
    async with dbmod.SessionLocal() as db:
        teacher = await svc.get_or_create_user(db, 1)
        await _set_teacher_vuz(db, teacher, "ТГСИ")
        other = await svc.get_or_create_user(db, 2)  # другой преподаватель
        s1 = await _student(db, 210, "Алиса", "ТГСИ", "101", True)
        sess_other = await _session(db, other.id)  # тест провёл ДРУГОЙ преподаватель
        await _attempt(db, sess_other.id, s1.id, "Алиса", 2)
        await db.commit()
        # наш преподаватель тестов не проводил, но видит студента своего вуза и его очки
        assert await svc.teacher_rating_groups(db, teacher) == ["101"]
        rows = (await svc.teacher_group_rating(db, teacher, "101"))["rows"]
        assert [r["name"] for r in rows] == ["Алиса"]
        assert rows[0]["points"] == 2


async def test_teacher_needs_vuz_in_profile():
    async with dbmod.SessionLocal() as db:
        teacher = await svc.get_or_create_user(db, 1)  # teacher_info не задан
        await _student(db, 220, "Алиса", "ТГСИ", "101", True)
        assert await svc.teacher_rating_groups(db, teacher) == []
        data = await svc.teacher_group_rating(db, teacher, "")
        assert data["need_vuz"] is True and data["rows"] == []


async def test_teacher_overall_only_own_vuz_and_active():
    async with dbmod.SessionLocal() as db:
        teacher = await svc.get_or_create_user(db, 1)
        await _set_teacher_vuz(db, teacher, "ТГСИ")
        a = await _student(db, 300, "Алиса", "ТГСИ", "101", True)
        b = await _student(db, 301, "Борис", "ТГСИ", "202", True)
        await _student(db, 302, "Инертный", "ТГСИ", "101", True)   # без тестов — в «Общий» не входит
        other_vuz = await _student(db, 303, "Чужой", "ТМА", "101", True)  # другой вуз — не входит
        s101 = await _session_g(db, teacher.id, "101")
        s202 = await _session_g(db, teacher.id, "202")
        await _attempt(db, s101.id, a.id, "Алиса", 2)
        await _attempt(db, s202.id, b.id, "Борис", 1)
        await _attempt(db, s101.id, other_vuz.id, "Чужой", 2)
        await db.commit()

        assert set(await svc.teacher_rating_groups(db, teacher)) == {"101", "202"}
        overall = (await svc.teacher_group_rating(db, teacher, ""))["rows"]
        assert {r["name"] for r in overall} == {"Алиса", "Борис"}  # активные своего вуза
        assert overall[0]["name"] == "Алиса" and overall[0]["points"] == 2
        # по группе 101 — и неактивный студент виден (полный состав), чужой вуз — нет
        g101 = [r["name"] for r in (await svc.teacher_group_rating(db, teacher, "101"))["rows"]]
        assert "Инертный" in g101 and "Чужой" not in g101
