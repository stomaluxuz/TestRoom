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
