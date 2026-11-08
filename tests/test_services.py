from datetime import timedelta

import pytest

from app import services as svc
from app.models import Attempt, utcnow
from app.models import TestSession as Sess
from app.parsers import ParsedQuestion

from .conftest import ADMIN_ID


def qs(n=10):
    return [ParsedQuestion(f"Вопрос {i}?", [f"верно {i}", f"нет {i}", f"мимо {i}"], 0) for i in range(n)]


async def make_teacher(db, uid=100, name="Рахимова Нигора"):
    u = await svc.get_or_create_user(db, uid)
    await svc.set_full_name(db, u, name)
    await svc.request_teacher(db, u, "ТашМИ, анатомия")
    return await svc.decide_teacher(db, uid, True)


async def make_student(db, uid, name=None):
    u = await svc.get_or_create_user(db, uid)
    await svc.set_full_name(db, u, name or f"Студент {uid}")
    return u


async def make_test(db, teacher, n=10):
    subj = await svc.create_subject(db, teacher, "Анатомия")
    return await svc.create_test(db, teacher, subj.id, "Кости скелета", qs(n))


def correct_index(state, db_question_text):
    # правильный вариант всегда начинается с «верно»
    return next(i for i, o in enumerate(state["question"]["options"]) if o.startswith("верно"))


async def test_roles_and_permissions(db):
    student = await make_student(db, 5)
    assert not student.is_teacher
    # студент может вести свои тесты...
    subj = await svc.create_subject(db, student, "Своя тема")
    test = await svc.create_test(db, student, subj.id, "Тренировка", qs(3))
    # ...но не может создать комнату с кодом для группы
    with pytest.raises(svc.ServiceError) as e:
        await svc.start_session(db, student, test.id, "101", 30, 3)
    assert e.value.status == 403
    # и не может сам назначить себя преподавателем — только заявка + одобрение
    with pytest.raises(svc.ServiceError) as e:
        await svc.set_role(db, student, "teacher")
    assert e.value.status == 403
    await svc.request_teacher(db, student, "вуз")
    assert student.teacher_pending and not student.is_teacher
    await svc.decide_teacher(db, 5, True)
    assert student.is_teacher
    s = await svc.start_session(db, student, test.id, "101", 30, 3)
    assert len(s.code) == 6
    # обратно в студенты — сразу, без одобрения
    await svc.set_role(db, student, "student")
    assert not student.is_teacher
    admin = await svc.get_or_create_user(db, ADMIN_ID)
    assert admin.is_teacher  # админ сразу преподаватель


async def test_no_review_while_group_test_running(db):
    """Защита от списывания: пока тест идёт для группы, закончивший студент не видит
    разбор (ни правильных ответов, ни галочек) — только после завершения теста для всех."""
    t = await make_teacher(db)
    test = await make_test(db, t, 3)
    s = await svc.start_session(db, t, test.id, "101", 30, 3)  # show_answers=False по умолчанию
    st = await make_student(db, 701)
    a = await svc.join_by_code(db, st, s.code)
    state = await svc.attempt_state(db, st, a.id)
    while state["status"] == "active":
        q = state["question"]
        state = await svc.submit_answer(db, st, a.id, q["id"], correct_index(state, q["text"]))
    assert state["status"] == "finished"
    # тест ещё идёт для группы → разбора нет, помечено answers_later
    assert state["review"] == [] and state["answers_later"] is True
    # учитель завершает тест для всех → разбор с правильными ответами открывается
    await svc.finish_session_by_teacher(db, t, s.id)
    after = await svc.attempt_state(db, st, a.id)
    assert len(after["review"]) == 3 and after["answers_later"] is False
    assert after["review"][0]["correct"] is not None


async def test_show_answers_reveals_immediately(db):
    """Если учитель включил «показывать сразу» — разбор доступен сразу (его осознанный выбор)."""
    t = await make_teacher(db)
    test = await make_test(db, t, 2)
    s = await svc.start_session(db, t, test.id, "101", 30, 2, show_answers=True)
    st = await make_student(db, 702)
    a = await svc.join_by_code(db, st, s.code)
    state = await svc.attempt_state(db, st, a.id)
    while state["status"] == "active":
        q = state["question"]
        state = await svc.submit_answer(db, st, a.id, q["id"], correct_index(state, q["text"]))
    assert state["answers_later"] is False and len(state["review"]) == 2


async def test_join_window_closes(db):
    """Код действует join_window_min минут: после окна новый студент войти не может,
    а уже вошедший продолжает спокойно."""
    t = await make_teacher(db)
    test = await make_test(db, t, 3)
    s = await svc.start_session(db, t, test.id, "101", 30, 3, join_window_min=3)
    early = await make_student(db, 801)
    a = await svc.join_by_code(db, early, s.code)  # успел войти
    assert a is not None
    # «перематываем» старт на 5 минут назад → окно (3 мин) закрылось
    s.started_at = s.started_at - timedelta(minutes=5)
    await db.commit()
    late = await make_student(db, 802)
    with pytest.raises(svc.ServiceError) as e:
        await svc.join_by_code(db, late, s.code)
    assert e.value.status == 403 and "истекло" in e.value.message
    # уже вошедший продолжает без проблем
    again = await svc.join_by_code(db, early, s.code)
    assert again.id == a.id


async def test_join_window_zero_means_open(db):
    """join_window_min=0 — приём открыт весь тест (как раньше)."""
    t = await make_teacher(db)
    test = await make_test(db, t, 3)
    s = await svc.start_session(db, t, test.id, "101", 30, 3, join_window_min=0)
    s.started_at = s.started_at - timedelta(minutes=20)
    await db.commit()
    late = await make_student(db, 803)
    a = await svc.join_by_code(db, late, s.code)  # войти всё ещё можно
    assert a is not None


async def test_remove_teacher_clears_pro(db):
    """Снятие статуса преподавателя убирает и Pro; есть и отдельное снятие Pro."""
    t = await make_teacher(db, uid=820)
    await svc.give_pro(db, 820, 30)
    assert (await svc.get_or_create_user(db, 820)).is_pro
    # снятие статуса → роль student и Pro снят
    await svc.remove_teacher(db, 820)
    u = await svc.get_or_create_user(db, 820)
    assert u.role == "student" and not u.is_pro and u.plan == "free"
    # отдельное снятие Pro
    t2 = await make_teacher(db, uid=821)
    await svc.give_pro(db, 821, 30)
    await svc.remove_pro(db, 821)
    u2 = await svc.get_or_create_user(db, 821)
    assert not u2.is_pro and u2.role == "teacher"  # роль осталась, снят только Pro


async def test_solo_practice(db):
    student = await make_student(db, 7)
    subj = await svc.create_subject(db, student, "Своя")
    test = await svc.create_test(db, student, subj.id, "Трен", qs(4))
    a = await svc.start_solo_session(db, student, test.id, question_count=3)
    assert a.total == 3
    state = await svc.attempt_state(db, student, a.id)
    assert state["status"] == "active"
    for _ in range(3):
        q = state["question"]
        state = await svc.submit_answer(db, student, a.id, q["id"], correct_index(state, q["text"]))
    assert state["status"] == "finished" and state["correct"] == 3
    assert state["review"] and len(state["review"]) == 3  # разбор на тренировке доступен сразу
    # тренировка не попадает в историю запусков преподавателя
    await svc.request_teacher(db, student, "вуз")
    await svc.decide_teacher(db, 7, True)
    assert await svc.teacher_sessions(db, student) == []


async def test_solo_learning_feedback(db):
    student = await make_student(db, 8)
    subj = await svc.create_subject(db, student, "Своя")
    test = await svc.create_test(db, student, subj.id, "Трен", qs(3))
    a = await svc.start_solo_session(db, student, test.id)
    state = await svc.attempt_state(db, student, a.id)
    q = state["question"]
    ci = next(i for i, o in enumerate(q["options"]) if o.startswith("верно"))
    st = await svc.submit_answer(db, student, a.id, q["id"], ci)  # верный ответ
    assert st["feedback"]["is_correct"] is True
    assert st["feedback"]["correct_index"] == ci
    q2 = st["question"]
    wrong = next(i for i, o in enumerate(q2["options"]) if not o.startswith("верно"))
    st2 = await svc.submit_answer(db, student, a.id, q2["id"], wrong)  # неверный ответ
    assert st2["feedback"]["is_correct"] is False
    assert st2["feedback"]["correct_index"] == next(i for i, o in enumerate(q2["options"]) if o.startswith("верно"))


async def test_full_session_flow(db):
    t = await make_teacher(db)
    test = await make_test(db, t, 10)
    s = await svc.start_session(db, t, test.id, "101", 30, 5, max_leaves=3)
    assert len(s.code) == 6 and s.question_count == 5

    st = await make_student(db, 200)
    a = await svc.join_by_code(db, st, s.code)
    assert a.total == 5 and len(set(a.question_order)) == 5

    # повторный вход — та же попытка
    a2 = await svc.join_by_code(db, st, s.code)
    assert a2.id == a.id

    state = await svc.attempt_state(db, st, a.id)
    assert state["status"] == "active"
    assert "correct" not in state["question"]  # правильный ответ не уходит клиенту
    answered_correct = 0
    for i in range(5):
        q = state["question"]
        idx = correct_index(state, q["text"]) if i % 2 == 0 else (correct_index(state, q["text"]) + 1) % 3
        answered_correct += i % 2 == 0
        state = await svc.submit_answer(db, st, a.id, q["id"], idx)
        assert "feedback" not in state  # групповой тест (экзамен) — без разбора по ходу
    assert state["status"] == "finished"
    assert state["correct"] == answered_correct == 3
    assert state["reason"] == "done"

    live = await svc.session_live(db, t, s.id)
    assert live["joined"] == 1 and live["finished_count"] == 1
    res = await svc.session_results(db, t, s.id)
    assert res["ranking"][0]["correct"] == 3
    assert res["avg_percent"] == 60
    assert res["hardest"] and res["hardest"][0]["correct_percent"] == 0

    name, data = await svc.export_xlsx(db, t, s.id)
    assert name.endswith(".xlsx") and data[:2] == b"PK"

    hist = await svc.teacher_sessions(db, t)
    assert hist[0]["students"] == 1 and hist[0]["avg_percent"] == 60


async def test_options_are_shuffled_per_student(db):
    t = await make_teacher(db)
    test = await make_test(db, t, 30)
    s = await svc.start_session(db, t, test.id, "101", 30, 30)
    orders = set()
    for uid in range(300, 306):
        st = await make_student(db, uid)
        a = await svc.join_by_code(db, st, s.code)
        orders.add(tuple(a.question_order))
    assert len(orders) > 1


async def test_double_submit_and_old_question(db):
    t = await make_teacher(db)
    test = await make_test(db, t, 3)
    s = await svc.start_session(db, t, test.id, "101", 30, 3)
    st = await make_student(db, 201)
    a = await svc.join_by_code(db, st, s.code)
    state = await svc.attempt_state(db, st, a.id)
    q1 = state["question"]["id"]
    s1 = await svc.submit_answer(db, st, a.id, q1, 0)
    s2 = await svc.submit_answer(db, st, a.id, q1, 0)  # повтор того же ответа
    assert s1["answered"] == s2["answered"] == 1
    with pytest.raises(svc.ServiceError):
        await svc.submit_answer(db, st, a.id, s2["question"]["id"], 99)


async def test_cannot_use_others_attempt(db):
    t = await make_teacher(db)
    test = await make_test(db, t, 3)
    s = await svc.start_session(db, t, test.id, "101", 30, 3)
    st1 = await make_student(db, 202)
    st2 = await make_student(db, 203)
    a = await svc.join_by_code(db, st1, s.code)
    with pytest.raises(svc.ServiceError) as e:
        await svc.attempt_state(db, st2, a.id)
    assert e.value.status == 404
    other_teacher = await make_teacher(db, 101, "Другой Учитель")
    with pytest.raises(svc.ServiceError):
        await svc.session_live(db, other_teacher, s.id)


async def test_time_expiry(db):
    t = await make_teacher(db)
    test = await make_test(db, t, 5)
    s = await svc.start_session(db, t, test.id, "101", 30, 5)
    st = await make_student(db, 204)
    a = await svc.join_by_code(db, st, s.code)
    state = await svc.attempt_state(db, st, a.id)
    await svc.submit_answer(db, st, a.id, state["question"]["id"], 0)

    sess = await db.get(Sess, s.id)
    sess.ends_at = utcnow() - timedelta(seconds=1)
    await db.commit()
    svc.invalidate_session(s.id)  # время изменили прямо в базе, минуя сервис

    state = await svc.attempt_state(db, st, a.id)
    assert state["status"] == "finished" and state["reason"] == "time"
    late = await make_student(db, 205)
    with pytest.raises(svc.ServiceError):
        await svc.join_by_code(db, late, s.code)
    closed = await svc.close_expired_sessions(db)
    assert closed == [s.id]
    assert (await svc.close_expired_sessions(db)) == []


async def test_background_close_finishes_open_attempts(db):
    t = await make_teacher(db)
    test = await make_test(db, t, 5)
    s = await svc.start_session(db, t, test.id, "101", 30, 5)
    st = await make_student(db, 206)
    a = await svc.join_by_code(db, st, s.code)
    sess = await db.get(Sess, s.id)
    sess.ends_at = utcnow() - timedelta(seconds=1)
    await db.commit()
    await svc.close_expired_sessions(db)
    await db.refresh(await db.get(Attempt, a.id))
    att = await db.get(Attempt, a.id)
    assert att.finished_at is not None and att.finish_reason == "time"


async def test_leaves_limit(db):
    t = await make_teacher(db)
    test = await make_test(db, t, 5)
    s = await svc.start_session(db, t, test.id, "101", 30, 5, max_leaves=2)
    st = await make_student(db, 207)
    a = await svc.join_by_code(db, st, s.code)
    state = await svc.report_leave(db, st, a.id, 12)
    assert state["status"] == "active" and state["leaves"] == 1
    state = await svc.report_leave(db, st, a.id, 5)
    assert state["status"] == "finished" and state["reason"] == "leaves"
    live = await svc.session_live(db, t, s.id)
    assert live["students"][0]["leave_seconds"] == 17


async def test_max_students_and_free_limit(db):
    svc.settings.free_max_sessions_per_day = 0  # этот тест про лимит студентов, не про запуски/день
    t = await make_teacher(db)
    test = await make_test(db, t, 3)
    s = await svc.start_session(db, t, test.id, "101", 30, 3, max_students=2)
    for uid in (210, 211):
        await svc.join_by_code(db, await make_student(db, uid), s.code)
    with pytest.raises(svc.ServiceError) as e:
        await svc.join_by_code(db, await make_student(db, 212), s.code)
    assert e.value.status == 403
    # бесплатный тариф: ограничение 30 студентов подставляется само
    s2 = await svc.start_session(db, t, test.id, "102", 30, 3, max_students=0)
    assert s2.max_students == 30
    await svc.give_pro(db, t.id, 30)
    s3 = await svc.start_session(db, t, test.id, "103", 30, 3, max_students=0)
    assert s3.max_students == 0


async def test_unlimited_tests_and_archive(db):
    t = await make_teacher(db)
    subj = await svc.create_subject(db, t, "Предмет")
    # тестов можно загружать сколько угодно (лимита на число тестов больше нет)
    tests = [await svc.create_test(db, t, subj.id, f"Т{i}", qs(2)) for i in range(6)]
    assert len(tests) == 6
    # архивный тест нельзя запустить, но из архива возвращается свободно
    await svc.set_archived(db, t, tests[0].id, True)
    with pytest.raises(svc.ServiceError):
        await svc.start_session(db, t, tests[0].id, "101", 30, 2)
    await svc.set_archived(db, t, tests[0].id, False)
    assert not (await svc.get_test(db, t, tests[0].id))["archived"]


async def test_daily_session_limit(db):
    t = await make_teacher(db)
    test = await make_test(db, t, 3)
    s1 = await svc.start_session(db, t, test.id, "101", 30, 3)
    assert len(s1.code) == 6
    # второй запуск в тот же день на бесплатном тарифе запрещён
    with pytest.raises(svc.ServiceError) as e:
        await svc.start_session(db, t, test.id, "102", 30, 3)
    assert e.value.status == 402
    # тренировка (соло) не считается запуском и доступна даже после исчерпания лимита
    a = await svc.start_solo_session(db, t, test.id, question_count=2)
    assert a.total == 2
    # Pro снимает ограничение на запуски
    await svc.give_pro(db, t.id, 30)
    s2 = await svc.start_session(db, t, test.id, "103", 30, 3)
    assert len(s2.code) == 6


async def test_teacher_finish_and_kick(db):
    t = await make_teacher(db)
    test = await make_test(db, t, 5)
    s = await svc.start_session(db, t, test.id, "101", 30, 5)
    st1, st2 = await make_student(db, 220), await make_student(db, 221)
    a1 = await svc.join_by_code(db, st1, s.code)
    await svc.join_by_code(db, st2, s.code)
    await svc.kick_student(db, t, s.id, a1.id)
    state = await svc.attempt_state(db, st1, a1.id)
    assert state["reason"] == "kicked"
    await svc.finish_session_by_teacher(db, t, s.id)
    res = await svc.session_results(db, t, s.id)
    assert not res["active"]
    assert len(res["ranking"]) == 1  # удалённый не считается
    assert res["ranking"][0]["reason"] == "тест завершён учителем"


async def test_question_edit_keeps_history(db):
    t = await make_teacher(db)
    test = await make_test(db, t, 2)
    s = await svc.start_session(db, t, test.id, "101", 30, 2)
    st = await make_student(db, 230)
    a = await svc.join_by_code(db, st, s.code)
    state = await svc.attempt_state(db, st, a.id)
    qid = state["question"]["id"]
    await svc.submit_answer(db, st, a.id, qid, 0)
    new_q = await svc.update_question(db, t, qid, "Новый текст", ["a", "b"], 1)
    assert new_q.id != qid  # вопрос уже использовался — создана новая версия
    data = await svc.get_test(db, t, test.id)
    assert len(data["questions"]) == 2
    assert any(q["text"] == "Новый текст" for q in data["questions"])
    res = await svc.session_results(db, t, s.id)
    assert res["ranking"]  # старая статистика цела


async def test_validation(db):
    st = await svc.get_or_create_user(db, 240)
    with pytest.raises(svc.ServiceError):
        await svc.join_by_code(db, st, "123456")  # нет ФИО
    with pytest.raises(svc.ServiceError):
        await svc.set_full_name(db, st, "  a ")
    await svc.set_full_name(db, st, "  Иванов   Иван ")
    assert st.full_name == "Иванов Иван"
    with pytest.raises(svc.ServiceError):
        await svc.join_by_code(db, st, "12")
    with pytest.raises(svc.ServiceError) as e:
        await svc.join_by_code(db, st, "999999")
    assert e.value.status == 404


async def test_rename_test(db):
    t = await make_teacher(db)
    test = await make_test(db, t, 3)
    await svc.rename_test(db, t, test.id, "  Новое   имя ")
    data = await svc.get_test(db, t, test.id)
    assert data["title"] == "Новое имя"
    with pytest.raises(svc.ServiceError):
        await svc.rename_test(db, t, test.id, "   ")
    other = await make_teacher(db, 101, "Другой Учитель")
    with pytest.raises(svc.ServiceError) as e:
        await svc.rename_test(db, other, test.id, "чужой")  # не свой тест
    assert e.value.status == 404


async def test_delete_test(db):
    t = await make_teacher(db)
    test = await make_test(db, t, 3)
    s = await svc.start_session(db, t, test.id, "101", 30, 3)
    st = await make_student(db, 250)
    a = await svc.join_by_code(db, st, s.code)
    state = await svc.attempt_state(db, st, a.id)
    await svc.submit_answer(db, st, a.id, state["question"]["id"], 0)

    # чужой удалить не может
    other = await make_teacher(db, 102, "Чужой")
    with pytest.raises(svc.ServiceError) as e:
        await svc.delete_test(db, other, test.id)
    assert e.value.status == 404

    await svc.delete_test(db, t, test.id)
    with pytest.raises(svc.ServiceError):
        await svc.get_test(db, t, test.id)  # теста больше нет
    # запуск, попытка и ответы удалены вместе с тестом
    assert await db.get(Sess, s.id) is None
    assert await db.get(Attempt, a.id) is None
    assert await svc.teacher_sessions(db, t) == []


async def test_presentation_counter_no_limit(db):
    # Лимита по дням больше нет — презентации считаются, но reserve не бросает ошибку.
    u = await make_student(db, 12)
    for _ in range(3):
        await svc.reserve_presentation(db, u)
    assert u.pres_total == 3


async def test_charge_feature_student(db):
    u = await make_student(db, 13)
    u.balance = 12000
    await db.commit()
    # цена по умолчанию 5000; списывается с баланса
    charged = await svc.charge_feature(db, u, "presentation")
    assert charged == 5000 and u.balance == 7000
    charged = await svc.charge_feature(db, u, "test")
    assert charged == 5000 and u.balance == 2000
    # не хватает на третью — ошибка 402, баланс не меняется
    with pytest.raises(svc.ServiceError) as e:
        await svc.charge_feature(db, u, "presentation")
    assert e.value.status == 402 and u.balance == 2000


async def test_charge_feature_free_for_teachers_and_admin(db):
    t = await make_teacher(db, 420, "Препод Платный")
    assert await svc.charge_feature(db, t, "presentation") == 0
    assert t.balance == 0  # с преподавателя ничего не списали
    admin = await svc.get_or_create_user(db, ADMIN_ID)
    assert await svc.charge_feature(db, admin, "test") == 0


async def test_charge_refund(db):
    u = await make_student(db, 14)
    u.balance = 5000
    await db.commit()
    charged = await svc.charge_feature(db, u, "test")
    assert u.balance == 0
    await svc.refund(db, u, charged)  # генерация не удалась — вернули
    assert u.balance == 5000


async def test_topup_flow(db):
    u = await make_student(db, 15)
    t = await svc.create_topup(db, u.id, 25000)
    assert t.status == "pending"
    # отклонение не зачисляет
    t2, _ = await svc.decide_topup(db, t.id, False, ADMIN_ID)
    assert t2.status == "rejected" and (u.balance or 0) == 0
    # повторно обработать нельзя
    with pytest.raises(svc.ServiceError) as e:
        await svc.decide_topup(db, t.id, True, ADMIN_ID)
    assert e.value.status == 409
    # подтверждение зачисляет на баланс
    t3 = await svc.create_topup(db, u.id, 25000)
    _, user = await svc.decide_topup(db, t3.id, True, ADMIN_ID)
    assert user.balance == 25000


async def test_settings_get_set(db):
    cfg = await svc.get_settings(db)
    assert cfg["price_presentation"] == "5000"  # значение по умолчанию
    await svc.set_settings(db, {"price_presentation": 8000, "card_number": "0000111122223333"})
    assert await svc.get_price(db, "presentation") == 8000
    cfg = await svc.get_settings(db)
    assert cfg["card_number"] == "0000111122223333"
    assert cfg["price_test"] == "5000"  # нетронутое осталось по умолчанию


async def test_users_by_audience(db):
    t = await make_teacher(db, 700, "Препод Р")
    s1 = await make_student(db, 701)
    s2 = await make_student(db, 702)
    await svc.set_blocked(db, s2.id, True)  # заблокированные не получают рассылку
    teachers = await svc.users_by_audience(db, "teachers")
    students = await svc.users_by_audience(db, "students")
    everyone = await svc.users_by_audience(db, "all")
    assert t.id in teachers and s1.id not in teachers
    assert s1.id in students and t.id not in students
    assert s2.id not in students and s2.id not in everyone  # заблокированный исключён
    assert t.id in everyone and s1.id in everyone


async def test_library_subjects_seeded(db):
    subs = await svc.list_library_subjects(db)
    assert len(subs) >= 5  # засеяны дефолтные предметы
    assert "Анатомия" in [s["name"] for s in subs]


async def test_library_upload_moderation_flow(db):
    t = await make_teacher(db, 800, "Препод Биб")
    sid = (await svc.list_library_subjects(db))[0]["id"]
    doc = await svc.add_library_doc(
        db, t, sid, "Кариес — лекция", "lecture.txt", "text/plain",
        "Кариес это разрушение твёрдых тканей зуба.".encode(),
    )
    assert doc.status == "pending"
    assert await svc.list_library_docs(db, status="approved") == []  # не виден до одобрения
    await svc.decide_library_doc(db, doc.id, True, ADMIN_ID)
    approved = await svc.list_library_docs(db, status="approved")
    assert len(approved) == 1 and approved[0]["title"] == "Кариес — лекция"
    assert len(await svc.list_library_docs(db, q="разрушение")) == 1  # поиск по тексту
    assert await svc.list_library_docs(db, q="гистология_неттакого") == []
    full = await svc.get_library_doc(db, doc.id)
    assert "Кариес" in full["text"]
    name, data = await svc.library_doc_file(db, doc.id)
    assert name == "lecture.txt" and data


async def test_library_only_teacher_uploads(db):
    s = await make_student(db, 801)
    sid = (await svc.list_library_subjects(db))[0]["id"]
    with pytest.raises(svc.ServiceError) as e:
        await svc.add_library_doc(db, s, sid, "T", "a.txt", "text/plain", b"hi")
    assert e.value.status == 403


async def test_library_subject_crud(db):
    s = await svc.add_library_subject(db, "История Узбекистана")
    assert s.id
    with pytest.raises(svc.ServiceError):
        await svc.add_library_subject(db, "история узбекистана")  # дубль без учёта регистра
    await svc.rename_library_subject(db, s.id, "История")
    assert any(x["name"] == "История" for x in await svc.list_library_subjects(db))
    await svc.delete_library_subject(db, s.id)
    assert not any(x["id"] == s.id for x in await svc.list_library_subjects(db))


async def test_grant_balance(db):
    s1 = await make_student(db, 710)
    s2 = await make_student(db, 711)
    s1.balance = 2000
    await db.commit()
    t = await make_teacher(db, 712, "Препод Г")
    ids = await svc.grant_balance(db, "students", 5000)
    assert set(ids) == {s1.id, s2.id}
    await db.refresh(s1); await db.refresh(s2); await db.refresh(t)
    assert s1.balance == 7000  # прибавилось к существующему
    assert s2.balance == 5000
    assert t.balance == 0  # преподавателю не начислили


async def test_delete_subject(db):
    t = await make_teacher(db)
    subj = await svc.create_subject(db, t, "Удаляемый предмет")
    test = await svc.create_test(db, t, subj.id, "Т1", qs(2))
    s = await svc.start_session(db, t, test.id, "101", 30, 2)
    await svc.join_by_code(db, await make_student(db, 260), s.code)
    await svc.delete_subject(db, t, subj.id)
    assert subj.id not in [x["id"] for x in await svc.list_subjects(db, t)]
    with pytest.raises(svc.ServiceError):
        await svc.get_test(db, t, test.id)  # тесты предмета тоже удалены
    other = await make_teacher(db, 101, "Чужой")
    subj2 = await svc.create_subject(db, other, "Чужой предмет")
    with pytest.raises(svc.ServiceError) as e:
        await svc.delete_subject(db, t, subj2.id)  # чужой удалить нельзя
    assert e.value.status == 404


async def test_set_teacher_info(db):
    t = await make_teacher(db, 410, "Препод Два")
    await svc.set_teacher_info(db, t, "  Новый  Вуз ")
    assert t.teacher_info == "Новый Вуз"
    with pytest.raises(svc.ServiceError):
        await svc.set_teacher_info(db, t, "   ")  # пусто нельзя
    student = await make_student(db, 411)
    with pytest.raises(svc.ServiceError) as e:
        await svc.set_teacher_info(db, student, "Вуз")  # не преподаватель
    assert e.value.status == 403


async def test_remove_teacher(db):
    t = await make_teacher(db, 400, "Бывший Препод")
    test = await make_test(db, t, 2)
    await svc.remove_teacher(db, 400)
    assert t.role == "student" and not t.is_teacher and not t.teacher_pending
    # тесты сохранены — можно вернуть вместе с историей
    data = await svc.get_test(db, t, test.id)
    assert len(data["questions"]) == 2
    # вернуть роль новой заявкой
    await svc.request_teacher(db, t, "вуз")
    await svc.decide_teacher(db, 400, True)
    assert t.is_teacher
    # у админа роль снять нельзя
    await svc.get_or_create_user(db, ADMIN_ID)
    with pytest.raises(svc.ServiceError):
        await svc.remove_teacher(db, ADMIN_ID)


async def test_pro_plus_grant_and_gate(db):
    u = await make_student(db, 900)
    # по умолчанию не Pro+ и платит за генерацию
    assert u.is_pro_plus is False
    assert svc.is_free_user(u) is False
    with pytest.raises(svc.ServiceError):
        svc.require_pro_plus(u)
    # выдаём Pro+ → активен, безлимит, гейт проходит
    u = await svc.give_pro_plus(db, u.id, 30)
    assert u.is_pro_plus is True
    assert svc.is_free_user(u) is True
    svc.require_pro_plus(u)  # не бросает
    # снятие
    u = await svc.remove_pro_plus(db, u.id)
    assert u.is_pro_plus is False
    with pytest.raises(svc.ServiceError):
        svc.require_pro_plus(u)


async def test_ai_chat_requires_pro_plus(db):
    u = await make_student(db, 910)
    with pytest.raises(svc.ServiceError):
        await svc.ai_chat(db, u, [{"role": "user", "content": "привет"}])


async def test_ai_chat_pro_plus_flow(db, monkeypatch):
    from app import ai as ai_mod
    u = await make_student(db, 911)
    await svc.give_pro_plus(db, u.id, 30)

    async def fake_chat(messages, lang="ru", context=""):
        return "Это ответ ассистента."

    monkeypatch.setattr(ai_mod, "chat_answer", fake_chat)
    r = await svc.ai_chat(db, u, [{"role": "user", "content": "что такое кариес"}], "ru")
    assert r["answer"] == "Это ответ ассистента."
    assert "sources" in r and "found" in r


async def test_ai_chat_tools_path(db, monkeypatch):
    from app import ai as ai_mod
    u = await make_student(db, 912)
    await svc.give_pro_plus(db, u.id, 30)
    captured = {}

    async def fake_tools(messages, lang, context, execute):
        captured["execute"] = execute
        return "сделал и отправил в бот"

    monkeypatch.setattr(ai_mod, "chat_with_tools", fake_tools)
    sent = []

    async def send_file(fn, data, cap):
        sent.append(fn)

    r = await svc.ai_chat(db, u, [{"role": "user", "content": "сделай презентацию"}], "ru", send_file=send_file)
    assert r["answer"] == "сделал и отправил в бот"
    # документ-инструмент работает и зовёт send_file
    out = await captured["execute"]("create_document", {"title": "Тест", "content": "Привет мир"})
    assert "отправлен" in out and sent


async def test_admin_stats(db):
    t = await make_teacher(db)
    await make_test(db, t, 2)
    s = await svc.admin_stats(db)
    assert s["teachers"] == 1 and s["tests"] == 1


async def test_admin_stats_today_fields(db):
    u = await make_student(db, 720)
    await svc.reserve_presentation(db, u)
    top = await svc.create_topup(db, u.id, 3000)
    await svc.decide_topup(db, top.id, True, ADMIN_ID)
    s = await svc.admin_stats(db)
    # на главном экране показываем «сегодня»: пользователь, презентация и доход за сегодня
    assert s["users_today"] >= 1
    assert s["presentations_today"] == 1
    assert s["revenue_today"] == 3000


async def test_admin_daily_stats_users_and_presentations(db):
    # сегодня добавились два пользователя и сделали две презентации
    u1 = await make_student(db, 701)
    await make_student(db, 702)
    await svc.reserve_presentation(db, u1)
    await svc.reserve_presentation(db, u1)

    users = await svc.admin_daily_stats(db, "users", days=7)
    assert len(users["series"]) == 7
    assert users["series"][-1]["date"] == svc._local_today().isoformat()  # последний день — сегодня
    assert users["today"] == 2 and users["total"] == 2

    pres = await svc.admin_daily_stats(db, "presentations", days=7)
    assert pres["today"] == 2 and pres["total"] == 2
    assert pres["all_time"] == 2  # общий счётчик за всё время

    # откат при неудачной генерации убирает факт из статистики
    await svc.release_presentation(db, u1)
    pres2 = await svc.admin_daily_stats(db, "presentations", days=7)
    assert pres2["today"] == 1


async def test_admin_daily_stats_revenue(db):
    u = await make_student(db, 710)
    top = await svc.create_topup(db, u.id, 5000)
    # пока заявка в ожидании — дохода нет
    rev0 = await svc.admin_daily_stats(db, "revenue", days=7)
    assert rev0["today"] == 0
    # после подтверждения сумма попадает в сегодняшний день
    await svc.decide_topup(db, top.id, True, ADMIN_ID)
    rev = await svc.admin_daily_stats(db, "revenue", days=7)
    assert rev["today"] == 5000 and rev["total"] == 5000


async def test_admin_daily_stats_tests_and_sessions(db):
    t = await make_teacher(db)
    test = await make_test(db, t, 3)
    await svc.start_session(db, t, test.id, "101", 30, 3)

    tests = await svc.admin_daily_stats(db, "tests", days=7)
    assert tests["today"] == 1 and tests["total"] == 1

    sess = await svc.admin_daily_stats(db, "sessions", days=7)
    assert sess["today"] == 1 and sess["total"] == 1

    s = await svc.admin_stats(db)
    assert s["tests_today"] == 1 and s["sessions_today"] == 1


async def test_admin_daily_stats_bad_metric(db):
    with pytest.raises(svc.ServiceError):
        await svc.admin_daily_stats(db, "nope")
