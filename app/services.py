"""Бизнес-логика: учителя, тесты, запуски с кодом, прохождение, статистика."""
from __future__ import annotations

import asyncio
import io
import random
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Integer, delete, func, insert, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from .config import settings
from .models import (
    AppSetting,
    Answer,
    Attempt,
    LibraryChunk,
    LibraryDoc,
    LibraryFigure,
    LibrarySubject,
    Question,
    Subject,
    Test,
    TestSession,
    TopUp,
    User,
    utcnow,
)
from .parsers import ParsedQuestion


class ServiceError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


# ---------------------------------------------------------------- пользователи

async def get_or_create_user(db: AsyncSession, user_id: int, username: str | None = None) -> User:
    user = await db.get(User, user_id)
    if user is None:
        bonus = await _welcome_bonus(db)  # приветственный бонус новому пользователю
        user = User(id=user_id, username=username, balance=bonus)
        db.add(user)
        try:
            await db.commit()
        except IntegrityError:  # параллельный запрос уже создал
            await db.rollback()
            user = await db.get(User, user_id)
    elif username and user.username != username:
        user.username = username
        await db.commit()
    if user_id in settings.admin_ids and user.role != "teacher":
        user.role = "teacher"  # админ всегда преподаватель
        await db.commit()
    return user


def clean_full_name(name: str) -> str:
    name = " ".join((name or "").split())
    if len(name) < 3 or len(name) > 120:
        raise ServiceError("Введите ФИО полностью (от 3 до 120 символов).")
    if not any(ch.isalpha() for ch in name):
        raise ServiceError("ФИО должно содержать буквы.")
    return name


async def set_full_name(db: AsyncSession, user: User, name: str) -> User:
    user.full_name = clean_full_name(name)
    await db.commit()
    return user


async def set_teacher_info(db: AsyncSession, user: User, info: str, kafedra: str | None = None) -> User:
    """Преподаватель сам меняет своё место работы (вуз) и кафедру."""
    if not user.is_teacher:
        raise ServiceError("Менять место работы может только преподаватель.", 403)
    info = " ".join((info or "").split())
    if not info:
        raise ServiceError("Укажите место работы (вуз).")
    user.teacher_info = info[:500]
    if kafedra is not None:
        user.teacher_kafedra = " ".join(kafedra.split())[:300] or None
    await db.commit()
    return user


async def set_role(db: AsyncSession, user: User, role: str) -> User:
    """Сменить роль. Студентом становятся сразу; преподавателем — только через одобрение."""
    if role not in ("student", "teacher"):
        raise ServiceError("Неизвестная роль.")
    if not user.full_name:
        raise ServiceError("Сначала укажите ФИО.", 409)
    if role == "teacher":
        if user.id not in settings.admin_ids:
            raise ServiceError("Преподавателем можно стать только после одобрения — отправьте заявку.", 403)
        user.role = "teacher"
        user.teacher_pending = False
    else:
        user.role = "student"  # стать студентом можно в любой момент, без одобрения
        user.teacher_pending = False
    await db.commit()
    return user


async def request_teacher(db: AsyncSession, user: User, info: str = "", kafedra: str = "") -> User:
    """Заявка на роль преподавателя. Админ одобряется автоматически."""
    if not user.full_name:
        raise ServiceError("Сначала укажите ФИО.", 409)
    if user.role == "teacher":
        raise ServiceError("Вы уже преподаватель.")
    if user.id in settings.admin_ids:
        user.role = "teacher"
        user.teacher_pending = False
        await db.commit()
        return user
    info = " ".join((info or "").split())
    if info:
        user.teacher_info = info[:500]
    kafedra = " ".join((kafedra or "").split())
    if kafedra:
        user.teacher_kafedra = kafedra[:300]
    user.teacher_pending = True
    await db.commit()
    return user


async def decide_teacher(db: AsyncSession, user_id: int, approve: bool) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise ServiceError("Пользователь не найден.", 404)
    if approve:
        user.role = "teacher"
    user.teacher_pending = False  # отклонение просто снимает заявку, роль остаётся student
    await db.commit()
    return user


async def give_pro(db: AsyncSession, user_id: int, days: int) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise ServiceError("Пользователь не найден.", 404)
    base = user.pro_until if user.is_pro else utcnow()
    user.plan = "pro"
    user.pro_until = base + timedelta(days=days)
    await db.commit()
    return user


def require_teacher(user: User):
    if not user.is_teacher:
        raise ServiceError("Создавать комнаты для группы могут только преподаватели.", 403)


def require_active(user: User):
    """Любой незаблокированный пользователь может вести свои тесты (и студент тоже)."""
    if user.blocked:
        raise ServiceError("Доступ заблокирован.", 403)


def _local_today():
    return (utcnow() + timedelta(hours=settings.tz_offset_hours)).date()


async def reserve_presentation(db: AsyncSession, user: User):
    """Счётчик презентаций (для статистики). Оплата/бесплатность решается отдельно
    (см. charge_feature): преподаватели — бесплатно, студенты — списанием с баланса."""
    today = _local_today()
    if user.pres_date != today:
        user.pres_date = today
        user.pres_count = 0
    user.pres_count += 1
    user.pres_total = (user.pres_total or 0) + 1
    await db.commit()


async def release_presentation(db: AsyncSession, user: User):
    """Вернуть слот, если генерация не удалась (общий счётчик тоже откатываем)."""
    changed = False
    if user.pres_count > 0 and user.pres_date == _local_today():
        user.pres_count -= 1
        changed = True
    if user.pres_total and user.pres_total > 0:
        user.pres_total -= 1
        changed = True
    if changed:
        await db.commit()


# ---------------------------------------------------------------- деньги: настройки, баланс, оплата

# Значения по умолчанию для настроек, которые админ меняет в панели (цены — в сумах).
DEFAULT_SETTINGS: dict[str, str] = {
    "price_presentation": "5000",
    "price_test": "5000",
    "card_number": "9860167802934742",
    "card_holder": "ABDULBOSIT ABDURAZOKOV",
    "topup_amounts": "10000,25000,50000",
    "welcome_bonus": "5000",  # сколько сум начисляется новому пользователю при первом входе
}


async def _welcome_bonus(db: AsyncSession) -> int:
    try:
        return max(0, int(float((await get_settings(db)).get("welcome_bonus", "0"))))
    except (TypeError, ValueError):
        return 0


async def get_settings(db: AsyncSession) -> dict[str, str]:
    """Текущие настройки оплаты (с подстановкой значений по умолчанию)."""
    rows = (await db.scalars(select(AppSetting))).all()
    stored = {r.key: r.value for r in rows}
    return {k: stored.get(k, default) for k, default in DEFAULT_SETTINGS.items()}


async def set_settings(db: AsyncSession, values: dict) -> dict[str, str]:
    """Сохранить изменённые настройки (только известные ключи)."""
    for key, raw in values.items():
        if key not in DEFAULT_SETTINGS or raw is None:
            continue
        value = str(raw).strip()
        obj = await db.get(AppSetting, key)
        if obj is None:
            db.add(AppSetting(key=key, value=value))
        else:
            obj.value = value
    await db.commit()
    return await get_settings(db)


def _price(cfg: dict[str, str], kind: str) -> int:
    try:
        return max(0, int(float(cfg.get(f"price_{kind}", "0"))))
    except (TypeError, ValueError):
        return 0


async def get_price(db: AsyncSession, kind: str) -> int:
    """Цена фичи для студента в сумах (kind: presentation | test)."""
    return _price(await get_settings(db), kind)


def is_free_user(user: User) -> bool:
    """Кто пользуется бесплатно: преподаватели, админы и Pro. Платят только студенты."""
    return user.is_teacher or user.id in settings.admin_ids or user.is_pro


async def charge_feature(db: AsyncSession, user: User, kind: str) -> int:
    """Списать стоимость фичи со студента. Возвращает списанную сумму (0 — бесплатно).
    Бросает ServiceError(402), если на балансе не хватает средств."""
    if is_free_user(user):
        return 0
    price = await get_price(db, kind)
    if price <= 0:
        return 0
    balance = user.balance or 0
    if balance < price:
        what = "презентацию" if kind == "presentation" else "тест"
        raise ServiceError(
            f"Недостаточно средств: за {what} нужно {price:,} сум, на балансе {balance:,} сум. "
            "Пополните баланс кнопкой «💳 Пополнить баланс».".replace(",", " "),
            402,
        )
    user.balance = balance - price
    await db.commit()
    return price


async def refund(db: AsyncSession, user: User, amount: int):
    """Вернуть списанную сумму на баланс (если генерация не удалась)."""
    if amount and amount > 0:
        user.balance = (user.balance or 0) + amount
        await db.commit()


async def create_topup(db: AsyncSession, user_id: int, amount: int) -> TopUp:
    """Создать заявку на пополнение (ждёт подтверждения админом)."""
    amount = int(amount)
    if amount <= 0 or amount > 100_000_000:
        raise ServiceError("Неверная сумма пополнения.")
    t = TopUp(user_id=user_id, amount=amount)
    db.add(t)
    await db.commit()
    return t


async def admin_topups(db: AsyncSession, status: str = "pending", limit: int = 100) -> list[dict]:
    """Список заявок на пополнение для админ-панели (по умолчанию — ожидающие)."""
    q = select(TopUp).order_by(TopUp.created_at.desc()).limit(limit)
    if status in ("pending", "approved", "rejected"):
        q = q.where(TopUp.status == status)
    rows = (await db.scalars(q)).all()
    names = {}
    ids = {r.user_id for r in rows}
    if ids:
        names = dict(
            (await db.execute(select(User.id, User.full_name).where(User.id.in_(ids)))).all()
        )
    return [
        {
            "id": r.id,
            "user_id": r.user_id,
            "name": names.get(r.user_id) or str(r.user_id),
            "amount": r.amount,
            "status": r.status,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


async def decide_topup(db: AsyncSession, topup_id: int, approve: bool, admin_id: int) -> tuple[TopUp, User | None]:
    """Подтвердить/отклонить пополнение. При подтверждении зачисляет сумму на баланс.
    Повторная обработка той же заявки запрещена (защита от двойного зачисления)."""
    t = await db.get(TopUp, topup_id)
    if t is None:
        raise ServiceError("Заявка не найдена.", 404)
    if t.status != "pending":
        raise ServiceError("Заявка уже обработана.", 409)
    t.status = "approved" if approve else "rejected"
    t.decided_at = utcnow()
    t.decided_by = admin_id
    user = await db.get(User, t.user_id)
    if approve and user is not None:
        user.balance = (user.balance or 0) + t.amount
    await db.commit()
    return t, user


# ---------------------------------------------------------------- предметы и тесты

async def create_subject(db: AsyncSession, teacher: User, name: str) -> Subject:
    require_active(teacher)
    name = " ".join((name or "").split())
    if not name or len(name) > 200:
        raise ServiceError("Введите название предмета.")
    subj = Subject(teacher_id=teacher.id, name=name)
    db.add(subj)
    await db.commit()
    return subj


async def get_or_create_subject(db: AsyncSession, teacher: User, name: str) -> Subject:
    require_active(teacher)
    name = " ".join((name or "").split())[:200] or "Без названия"
    existing = await db.scalar(
        select(Subject).where(Subject.teacher_id == teacher.id, Subject.name == name)
    )
    return existing or await create_subject(db, teacher, name)


async def list_subjects(db: AsyncSession, teacher: User) -> list[dict]:
    require_active(teacher)
    subjects = (
        await db.scalars(select(Subject).where(Subject.teacher_id == teacher.id).order_by(Subject.name))
    ).all()
    counts = dict(
        (
            await db.execute(
                select(Question.test_id, func.count())
                .join(Test, Test.id == Question.test_id)
                .where(Test.teacher_id == teacher.id, Question.active.is_(True))
                .group_by(Question.test_id)
            )
        ).all()
    )
    tests = (
        await db.scalars(select(Test).where(Test.teacher_id == teacher.id).order_by(Test.created_at.desc()))
    ).all()
    out = []
    for s in subjects:
        out.append(
            {
                "id": s.id,
                "name": s.name,
                "tests": [
                    {
                        "id": t.id,
                        "title": t.title,
                        "archived": t.archived,
                        "questions": counts.get(t.id, 0),
                    }
                    for t in tests
                    if t.subject_id == s.id
                ],
            }
        )
    return out


async def _own_test(db: AsyncSession, teacher: User, test_id: int) -> Test:
    require_active(teacher)
    test = await db.get(Test, test_id)
    if test is None or test.teacher_id != teacher.id:
        raise ServiceError("Тест не найден.", 404)
    return test


async def create_test(
    db: AsyncSession, teacher: User, subject_id: int, title: str, questions: list[ParsedQuestion]
) -> Test:
    require_active(teacher)
    subj = await db.get(Subject, subject_id)
    if subj is None or subj.teacher_id != teacher.id:
        raise ServiceError("Предмет не найден.", 404)
    title = " ".join((title or "").split())
    if not title:
        raise ServiceError("Введите название теста.")
    if not questions:
        raise ServiceError("В тесте нет ни одного правильно оформленного вопроса.")
    test = Test(teacher_id=teacher.id, subject_id=subj.id, title=title[:300])
    db.add(test)
    await db.flush()
    for i, q in enumerate(questions):
        db.add(Question(test_id=test.id, position=i, text=q.text, options=q.options, correct=q.correct))
    await db.commit()
    return test


async def get_test(db: AsyncSession, teacher: User, test_id: int) -> dict:
    test = await _own_test(db, teacher, test_id)
    qs = (
        await db.scalars(
            select(Question).where(Question.test_id == test.id, Question.active.is_(True)).order_by(Question.position)
        )
    ).all()
    subj = await db.get(Subject, test.subject_id)
    return {
        "id": test.id,
        "title": test.title,
        "subject": subj.name if subj else "",
        "subject_id": test.subject_id,
        "archived": test.archived,
        "questions": [
            {"id": q.id, "text": q.text, "options": q.options, "correct": q.correct} for q in qs
        ],
    }


def _validate_question(text: str, options: list[str], correct: int) -> tuple[str, list[str], int]:
    text = (text or "").strip()
    options = [(o or "").strip() for o in (options or [])]
    if not text:
        raise ServiceError("Введите текст вопроса.")
    if len(options) < 2 or any(not o for o in options):
        raise ServiceError("Нужно минимум 2 непустых варианта.")
    if len(options) > 10:
        raise ServiceError("Максимум 10 вариантов.")
    if not isinstance(correct, int) or not 0 <= correct < len(options):
        raise ServiceError("Отметьте правильный ответ.")
    return text, options, correct


async def add_question(db: AsyncSession, teacher: User, test_id: int, text, options, correct) -> Question:
    test = await _own_test(db, teacher, test_id)
    text, options, correct = _validate_question(text, options, correct)
    pos = await db.scalar(select(func.coalesce(func.max(Question.position), -1)).where(Question.test_id == test.id))
    q = Question(test_id=test.id, position=pos + 1, text=text, options=options, correct=correct)
    db.add(q)
    await db.commit()
    return q


async def update_question(db: AsyncSession, teacher: User, question_id: int, text, options, correct) -> Question:
    q = await db.get(Question, question_id)
    if q is None or not q.active:
        raise ServiceError("Вопрос не найден.", 404)
    await _own_test(db, teacher, q.test_id)
    text, options, correct = _validate_question(text, options, correct)
    # Вопрос никогда не меняется на месте: создаётся новая версия, а старая скрывается.
    # Так старая статистика и уже идущие тесты остаются корректными,
    # а кэш вопросов во всех процессах сервера не устаревает.
    q.active = False
    new_q = Question(test_id=q.test_id, position=q.position, text=text, options=options, correct=correct)
    db.add(new_q)
    await db.commit()
    return new_q


async def delete_question(db: AsyncSession, teacher: User, question_id: int):
    q = await db.get(Question, question_id)
    if q is None or not q.active:
        raise ServiceError("Вопрос не найден.", 404)
    await _own_test(db, teacher, q.test_id)
    q.active = False
    await db.commit()


async def delete_subject(db: AsyncSession, teacher: User, subject_id: int):
    """Удаляет предмет вместе со всеми его тестами (и их запусками/результатами)."""
    require_active(teacher)
    subj = await db.get(Subject, subject_id)
    if subj is None or subj.teacher_id != teacher.id:
        raise ServiceError("Предмет не найден.", 404)
    test_ids = list(
        (await db.scalars(select(Test.id).where(Test.subject_id == subject_id))).all()
    )
    for tid in test_ids:
        await delete_test(db, teacher, tid)  # каскад: вопросы, запуски, попытки, ответы
    await db.execute(delete(Subject).where(Subject.id == subject_id))
    await db.commit()


async def set_archived(db: AsyncSession, teacher: User, test_id: int, archived: bool) -> Test:
    test = await _own_test(db, teacher, test_id)
    test.archived = archived
    await db.commit()
    return test


async def rename_test(db: AsyncSession, teacher: User, test_id: int, title: str) -> Test:
    test = await _own_test(db, teacher, test_id)
    title = " ".join((title or "").split())
    if not title:
        raise ServiceError("Введите название теста.")
    test.title = title[:300]
    await db.commit()
    return test


async def delete_test(db: AsyncSession, teacher: User, test_id: int):
    """Полностью удаляет тест владельца со всеми вопросами, запусками и результатами."""
    test = await _own_test(db, teacher, test_id)
    tid = test.id
    # Порядок удаления соблюдает внешние ключи: ответы → попытки → запуски → вопросы → тест.
    sess_ids = list((await db.scalars(select(TestSession.id).where(TestSession.test_id == tid))).all())
    if sess_ids:
        att_ids = list((await db.scalars(select(Attempt.id).where(Attempt.session_id.in_(sess_ids)))).all())
        if att_ids:
            await db.execute(delete(Answer).where(Answer.attempt_id.in_(att_ids)))
            await db.execute(delete(Attempt).where(Attempt.id.in_(att_ids)))
        await db.execute(delete(TestSession).where(TestSession.id.in_(sess_ids)))
        for sid in sess_ids:
            invalidate_session(sid)
    q_ids = list((await db.scalars(select(Question.id).where(Question.test_id == tid))).all())
    if q_ids:
        await db.execute(delete(Question).where(Question.test_id == tid))
        for qid in q_ids:
            invalidate_question(qid)
    await db.execute(delete(Test).where(Test.id == tid))
    await db.commit()


# ---------------------------------------------------------------- запуск теста

async def _check_daily_session_limit(db: AsyncSession, teacher: User):
    """Бесплатный тариф: не больше N запусков теста (для группы) за местный день."""
    if teacher.is_pro or teacher.id in settings.admin_ids:
        return
    limit = settings.free_max_sessions_per_day
    if limit <= 0:
        return
    off = timedelta(hours=settings.tz_offset_hours)
    local_midnight = (utcnow() + off).replace(hour=0, minute=0, second=0, microsecond=0)
    day_start = local_midnight - off  # начало местных суток в UTC
    started_today = await db.scalar(
        select(func.count()).select_from(TestSession).where(
            TestSession.teacher_id == teacher.id,
            TestSession.solo.is_(False),
            TestSession.started_at >= day_start,
        )
    )
    if started_today >= limit:
        raise ServiceError(
            f"В бесплатной версии можно запустить только {limit} тест в день. "
            "Следующий запуск будет доступен завтра — или подключите Pro, чтобы запускать без ограничений.",
            402,
        )


async def _generate_code(db: AsyncSession) -> str:
    for _ in range(50):
        code = f"{secrets.randbelow(900000) + 100000}"
        busy = await db.scalar(
            select(func.count()).select_from(TestSession).where(
                TestSession.code == code, TestSession.finished.is_(False)
            )
        )
        if not busy:
            return code
    raise ServiceError("Не удалось создать код, попробуйте ещё раз.", 500)


async def start_session(
    db: AsyncSession,
    teacher: User,
    test_id: int,
    group_name: str,
    duration_min: int,
    question_count: int,
    max_leaves: int = 3,
    max_students: int = 0,
    show_answers: bool = False,
    join_window_min: int = 3,
) -> TestSession:
    require_teacher(teacher)  # комнату с кодом для группы запускает только преподаватель
    test = await _own_test(db, teacher, test_id)
    if test.archived:
        raise ServiceError("Тест в архиве. Верните его из архива, чтобы запустить.")
    await _check_daily_session_limit(db, teacher)  # бесплатно — 1 запуск в день
    group_name = " ".join((group_name or "").split())
    if not group_name:
        raise ServiceError("Укажите группу.")
    if not 1 <= duration_min <= 240:
        raise ServiceError("Время теста: от 1 до 240 минут.")
    available = await db.scalar(
        select(func.count()).select_from(Question).where(Question.test_id == test.id, Question.active.is_(True))
    )
    if available == 0:
        raise ServiceError("В тесте нет вопросов.")
    if question_count <= 0 or question_count > available:
        question_count = available
    if max_leaves < 0:
        max_leaves = 0
    limit = 0 if (teacher.is_pro or teacher.id in settings.admin_ids) else settings.free_max_students
    if limit and (max_students <= 0 or max_students > limit):
        max_students = limit
    now = utcnow()
    s = TestSession(
        test_id=test.id,
        teacher_id=teacher.id,
        group_name=group_name[:100],
        code=await _generate_code(db),
        duration_min=duration_min,
        question_count=question_count,
        max_leaves=max_leaves,
        max_students=max(0, max_students),
        show_answers=show_answers,
        join_window_min=max(0, int(join_window_min or 0)),
        started_at=now,
        ends_at=now + timedelta(minutes=duration_min),
    )
    db.add(s)
    await db.commit()
    return s


async def start_solo_session(
    db: AsyncSession, user: User, test_id: int, question_count: int = 0, duration_min: int = 30
) -> Attempt:
    """Тренировка «только для себя»: студент решает свой тест в одиночку, без кода для группы."""
    require_active(user)
    test = await _own_test(db, user, test_id)
    if test.archived:
        raise ServiceError("Тест в архиве. Верните его из архива, чтобы решать.")
    if not 1 <= duration_min <= 240:
        duration_min = 30
    available = await db.scalar(
        select(func.count()).select_from(Question).where(Question.test_id == test.id, Question.active.is_(True))
    )
    if available == 0:
        raise ServiceError("В тесте нет вопросов.")
    if question_count <= 0 or question_count > available:
        question_count = available
    now = utcnow()
    s = TestSession(
        test_id=test.id,
        teacher_id=user.id,
        group_name="Тренировка",
        code=await _generate_code(db),
        duration_min=duration_min,
        question_count=question_count,
        max_leaves=0,
        max_students=1,
        show_answers=True,  # на тренировке разбор всегда доступен
        solo=True,
        started_at=now,
        ends_at=now + timedelta(minutes=duration_min),
    )
    db.add(s)
    await db.commit()
    return await join_by_code(db, user, s.code)  # сразу входим в свою тренировку


async def _own_session(db: AsyncSession, teacher: User, session_id: int) -> TestSession:
    require_teacher(teacher)
    s = await db.get(TestSession, session_id)
    if s is None or s.teacher_id != teacher.id:
        raise ServiceError("Запуск не найден.", 404)
    return s


def session_open(s: TestSession) -> bool:
    return not s.finished and s.ends_at > utcnow()


async def finish_session(db: AsyncSession, s: TestSession, reason: str = "time"):
    """Закрыть запуск и все незавершённые попытки."""
    now = utcnow()
    if not s.finished:
        s.finished = True
        s.finished_at = min(now, s.ends_at) if reason == "time" else now
        if reason == "teacher":
            s.ends_at = min(s.ends_at, now)
    invalidate_session(s.id)
    await db.execute(
        update(Attempt)
        .where(Attempt.session_id == s.id, Attempt.finished_at.is_(None))
        .values(finished_at=s.finished_at, finish_reason=reason)
    )
    await db.commit()
    invalidate_session(s.id)


async def finish_session_by_teacher(db: AsyncSession, teacher: User, session_id: int):
    s = await _own_session(db, teacher, session_id)
    if not s.finished:
        await finish_session(db, s, reason="teacher")
    return s


async def close_expired_sessions(db: AsyncSession) -> list[int]:
    """Вызывается фоновой задачей. Возвращает id закрытых запусков."""
    expired = (
        await db.scalars(
            select(TestSession).where(TestSession.finished.is_(False), TestSession.ends_at <= utcnow())
        )
    ).all()
    for s in expired:
        await finish_session(db, s, reason="time")
    return [s.id for s in expired]


# ---------------------------------------------------------------- студент

# Защита от подбора кода: не больше JOIN_MAX_FAILS неверных кодов за JOIN_WINDOW секунд
JOIN_MAX_FAILS = 10
JOIN_WINDOW = 600
_join_fails: dict[int, list[float]] = {}


def _check_join_limit(user_id: int):
    now = time.monotonic()
    fails = [t for t in _join_fails.get(user_id, []) if now - t < JOIN_WINDOW]
    _join_fails[user_id] = fails
    if len(fails) >= JOIN_MAX_FAILS:
        wait = int(JOIN_WINDOW - (now - fails[0])) // 60 + 1
        raise ServiceError(f"Слишком много неверных кодов. Попробуйте через {wait} мин.", 429)


def _join_failed(user_id: int):
    _join_fails.setdefault(user_id, []).append(time.monotonic())
    if len(_join_fails) > 100_000:  # не даём словарю расти бесконечно
        _join_fails.clear()


async def join_by_code(db: AsyncSession, user: User, code: str) -> Attempt:
    if user.blocked:
        raise ServiceError("Доступ заблокирован.", 403)
    if not user.full_name:
        raise ServiceError("Сначала укажите ФИО.", 409)
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(code) != 6:
        raise ServiceError("Код состоит из 6 цифр.")
    _check_join_limit(user.id)
    s = await db.scalar(
        select(TestSession).where(TestSession.code == code, TestSession.finished.is_(False))
    )
    if s is None or s.ends_at <= utcnow():
        _join_failed(user.id)
        raise ServiceError("Тест с таким кодом не найден или уже закрыт.", 404)

    existing = await db.scalar(
        select(Attempt).where(Attempt.session_id == s.id, Attempt.user_id == user.id)
    )
    if existing:
        return existing  # повторный вход — продолжаем ту же попытку

    # Защита от списывания «по очереди»: новый студент может войти только в течение
    # join_window_min минут после старта. Уже вошедшие (existing выше) продолжают спокойно.
    if s.join_window_min and utcnow() > s.started_at + timedelta(minutes=s.join_window_min):
        _join_failed(user.id)
        raise ServiceError(
            "⏰ Время входа истекло — вы не успели войти в тест. Обратитесь к преподавателю.", 403
        )

    if s.max_students:
        joined = await db.scalar(select(func.count()).select_from(Attempt).where(Attempt.session_id == s.id))
        if joined >= s.max_students:
            raise ServiceError("В тесте уже максимальное число участников. Обратитесь к преподавателю.", 403)

    qids = list(
        (
            await db.scalars(
                select(Question.id).where(Question.test_id == s.test_id, Question.active.is_(True))
            )
        ).all()
    )
    questions = (await db.scalars(select(Question).where(Question.id.in_(qids)))).all()
    rng = random.SystemRandom()
    rng.shuffle(qids)
    qids = qids[: s.question_count]
    n_opts = {q.id: len(q.options) for q in questions}
    option_orders = {}
    for qid in qids:
        perm = list(range(n_opts[qid]))
        rng.shuffle(perm)
        option_orders[str(qid)] = perm
    a = Attempt(
        session_id=s.id,
        user_id=user.id,
        full_name=user.full_name,
        question_order=qids,
        option_orders=option_orders,
    )
    db.add(a)
    try:
        await db.commit()
    except IntegrityError:  # двойное нажатие
        await db.rollback()
        a = await db.scalar(select(Attempt).where(Attempt.session_id == s.id, Attempt.user_id == user.id))
    return a


@dataclass
class SessionMeta:
    """Редко меняющиеся данные запуска. Кэшируются, чтобы не ходить в базу на каждый ответ."""

    id: int
    test_id: int
    group: str
    test_title: str
    subject: str
    ends_at: datetime
    finished: bool
    max_leaves: int
    show_answers: bool
    solo: bool
    loaded: float

    @property
    def open(self) -> bool:
        return not self.finished and self.ends_at > utcnow()


SESSION_TTL = 5.0  # секунд; при завершении запуска кэш сбрасывается сразу
_SESSION_CACHE: dict[int, SessionMeta] = {}
_QUESTION_CACHE: dict[int, tuple[str, list, int]] = {}
_QUESTION_CACHE_MAX = 300_000


def invalidate_session(session_id: int):
    _SESSION_CACHE.pop(session_id, None)


def invalidate_question(question_id: int):
    _QUESTION_CACHE.pop(question_id, None)


def clear_caches():
    _SESSION_CACHE.clear()
    _QUESTION_CACHE.clear()
    _join_fails.clear()
    invalidate_vec_cache()  # сбросить кэш векторов RAG (важно между тестами с разными БД)
    invalidate_fig_cache()


async def _session_meta(db: AsyncSession, session_id: int) -> SessionMeta:
    m = _SESSION_CACHE.get(session_id)
    if m is not None and time.monotonic() - m.loaded < SESSION_TTL:
        return m
    s, title, subject = (
        await db.execute(
            select(TestSession, Test.title, Subject.name)
            .join(Test, Test.id == TestSession.test_id)
            .join(Subject, Subject.id == Test.subject_id)
            .where(TestSession.id == session_id)
        )
    ).one()
    m = SessionMeta(
        id=s.id,
        test_id=s.test_id,
        group=s.group_name,
        test_title=title,
        subject=subject,
        ends_at=s.ends_at,
        finished=s.finished,
        max_leaves=s.max_leaves,
        show_answers=s.show_answers,
        solo=s.solo,
        loaded=time.monotonic(),
    )
    _SESSION_CACHE[session_id] = m
    return m


async def _questions(db: AsyncSession, ids: list[int]) -> dict[int, tuple[str, list, int]]:
    missing = [i for i in ids if i not in _QUESTION_CACHE]
    if missing:
        if len(_QUESTION_CACHE) > _QUESTION_CACHE_MAX:
            _QUESTION_CACHE.clear()
        rows = await db.execute(
            select(Question.id, Question.text, Question.options, Question.correct).where(Question.id.in_(missing))
        )
        for qid, text, options, correct in rows:
            _QUESTION_CACHE[qid] = (text, options, correct)
    return {i: _QUESTION_CACHE[i] for i in ids}


def _uid(user) -> int:
    return user if isinstance(user, int) else user.id


async def _own_attempt(db: AsyncSession, user, attempt_id: int) -> tuple[Attempt, SessionMeta]:
    a = await db.get(Attempt, attempt_id)
    if a is None or a.user_id != _uid(user):
        raise ServiceError("Попытка не найдена.", 404)
    m = await _session_meta(db, a.session_id)
    if not a.is_finished and not m.open:
        # время вышло, а фоновая задача ещё не успела закрыть запуск
        a.finished_at = min(utcnow(), m.ends_at)
        a.finish_reason = "time"
        await db.commit()
    return a, m


async def attempt_state(db: AsyncSession, user, attempt_id: int) -> dict:
    a, m = await _own_attempt(db, user, attempt_id)
    return await _state(db, a, m)


async def _state(db: AsyncSession, a: Attempt, m: SessionMeta) -> dict:
    base = {
        "attempt_id": a.id,
        "test_title": m.test_title,
        "subject": m.subject,
        "group": m.group,
        "total": a.total,
        "answered": a.current_index,
        "leaves": a.leaves,
        "max_leaves": m.max_leaves,
        "solo": m.solo,
    }
    if a.is_finished:
        # Защита от списывания: пока тест ИДЁТ для группы, студенту показываем ТОЛЬКО счёт,
        # без разбора (ни правильных ответов, ни отметок верно/неверно) — иначе первый
        # закончивший вычисляет ключ по своим галочкам и диктует остальным.
        # Разбор с правильными ответами открываем, когда тест завершён для всех (session_done),
        # или если учитель включил «показывать сразу», или на тренировке (solo).
        session_done = not m.open or m.solo
        reveal = session_done or m.show_answers
        base.update(
            status="finished",
            correct=a.correct_count,
            reason=a.finish_reason,
            duration_sec=int((a.finished_at - a.started_at).total_seconds()),
            review=(await _review(db, a, True)) if reveal else [],
            answers_later=not reveal,
        )
        return base
    qid = a.question_order[a.current_index]
    text, options, _ = (await _questions(db, [qid]))[qid]
    perm = a.option_orders[str(qid)]
    base.update(
        status="active",
        seconds_left=max(0, int((m.ends_at - utcnow()).total_seconds())),
        question={
            "id": qid,
            "number": a.current_index + 1,
            "text": text,
            "options": [options[i] for i in perm],
        },
    )
    return base


async def _review(db: AsyncSession, a: Attempt, reveal: bool = True) -> list[dict]:
    """Ответы студента. reveal=False — показываем только его выбор (верно/неверно),
    без правильного ответа (пока тест ещё идёт для остальных)."""
    qs = await _questions(db, a.question_order)
    ans = {x.question_id: x for x in (await db.scalars(select(Answer).where(Answer.attempt_id == a.id))).all()}
    out = []
    for qid in a.question_order:
        text, options, correct = qs[qid]
        given = ans.get(qid)
        out.append(
            {
                "text": text,
                "correct": options[correct] if reveal else None,
                "chosen": options[given.chosen] if given else None,
                "is_correct": bool(given and given.is_correct),
            }
        )
    return out


async def submit_answer(db: AsyncSession, user, attempt_id: int, question_id: int, option_index: int) -> dict:
    a, m = await _own_attempt(db, user, attempt_id)
    if a.is_finished:
        return await _state(db, a, m)
    idx = a.current_index
    current_qid = a.question_order[idx]
    if question_id != current_qid:
        # ответ на старый вопрос (двойное нажатие, плохая сеть) — просто вернуть текущее состояние
        return await _state(db, a, m)
    perm = a.option_orders[str(current_qid)]
    if not 0 <= option_index < len(perm):
        raise ServiceError("Неверный вариант ответа.")
    _, _, right = (await _questions(db, [current_qid]))[current_qid]
    original = perm[option_index]
    correct = original == right
    last = idx + 1 >= a.total
    now = utcnow()

    values = {"current_index": idx + 1, "correct_count": a.correct_count + (1 if correct else 0)}
    if last:
        values.update(finished_at=now, finish_reason="done")
    # Указатель двигается, только если он всё ещё на этом вопросе —
    # защита от гонки при одновременных запросах.
    res = await db.execute(
        update(Attempt)
        .where(Attempt.id == a.id, Attempt.current_index == idx, Attempt.finished_at.is_(None))
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if res.rowcount == 1:
        await db.execute(
            insert(Answer).values(
                attempt_id=a.id, question_id=current_qid, chosen=original, is_correct=correct, answered_at=now
            )
        )
        await db.commit()
        for k, v in values.items():
            set_committed_value(a, k, v)
        state = await _state(db, a, m)
        if m.solo:  # режим обучения: сразу сообщаем, верно ли и какой вариант правильный
            state["feedback"] = {
                "is_correct": correct,
                "correct_index": perm.index(right),  # позиция правильного в показанном студенту порядке
                "chosen_index": option_index,
            }
        return state
    await db.rollback()
    await db.refresh(a)
    return await _state(db, a, m)


async def report_leave(db: AsyncSession, user, attempt_id: int, seconds: int) -> dict:
    a, m = await _own_attempt(db, user, attempt_id)
    if a.is_finished:
        return await _state(db, a, m)
    seconds = max(0, min(int(seconds or 0), 24 * 3600))
    a.leaves += 1
    a.leave_seconds += seconds
    if m.max_leaves and a.leaves >= m.max_leaves:
        a.finished_at = utcnow()
        a.finish_reason = "leaves"
    await db.commit()
    return await _state(db, a, m)


async def student_history(db: AsyncSession, user: User) -> list[dict]:
    rows = (
        await db.execute(
            select(Attempt, TestSession, Test)
            .join(TestSession, TestSession.id == Attempt.session_id)
            .join(Test, Test.id == TestSession.test_id)
            .where(Attempt.user_id == user.id)
            .order_by(Attempt.started_at.desc())
            .limit(50)
        )
    ).all()
    return [
        {
            "attempt_id": a.id,
            "test_title": t.title,
            "date": a.started_at.isoformat(),
            "correct": a.correct_count,
            "total": a.total,
            "finished": a.is_finished or s.finished or s.ends_at <= utcnow(),
        }
        for a, s, t in rows
    ]


# ---------------------------------------------------------------- учитель: статистика

async def active_session(db: AsyncSession, teacher: User) -> dict | None:
    s = await db.scalar(
        select(TestSession)
        .where(
            TestSession.teacher_id == teacher.id,
            TestSession.finished.is_(False),
            TestSession.ends_at > utcnow(),
            TestSession.solo.is_(False),
        )
        .order_by(TestSession.started_at.desc())
    )
    if not s:
        return None
    test = await db.get(Test, s.test_id)
    return {
        "id": s.id,
        "code": s.code,
        "group": s.group_name,
        "test_title": test.title,
        "seconds_left": int((s.ends_at - utcnow()).total_seconds()),
    }


async def teacher_sessions(db: AsyncSession, teacher: User, limit: int = 100) -> list[dict]:
    require_teacher(teacher)
    rows = (
        await db.execute(
            select(TestSession, Test)
            .join(Test, Test.id == TestSession.test_id)
            .where(TestSession.teacher_id == teacher.id, TestSession.solo.is_(False))
            .order_by(TestSession.started_at.desc())
            .limit(limit)
        )
    ).all()
    ids = [s.id for s, _ in rows]
    percents: dict[int, list[float]] = {}
    if ids:
        for sid, correct, order, reason in (
            await db.execute(
                select(Attempt.session_id, Attempt.correct_count, Attempt.question_order, Attempt.finish_reason).where(
                    Attempt.session_id.in_(ids)
                )
            )
        ).all():
            if reason == "kicked" or not order:
                continue
            percents.setdefault(sid, []).append(correct * 100.0 / len(order))
    out = []
    for s, t in rows:
        p = percents.get(s.id, [])
        n, avg = len(p), (sum(p) / len(p) if p else None)
        out.append(
            {
                "id": s.id,
                "test_title": t.title,
                "group": s.group_name,
                "code": s.code,
                "started_at": s.started_at.isoformat(),
                "active": session_open(s),
                "students": n,
                "avg_percent": round(avg) if avg is not None else None,
            }
        )
    return out


def _fmt_reason(r: str | None) -> str:
    return {
        "done": "закончил",
        "time": "время вышло",
        "leaves": "закрыт: сворачивал",
        "kicked": "удалён учителем",
        "teacher": "тест завершён учителем",
    }.get(r or "", "")


async def session_live(db: AsyncSession, teacher: User, session_id: int) -> dict:
    s = await _own_session(db, teacher, session_id)
    test = await db.get(Test, s.test_id)
    attempts = (
        await db.scalars(select(Attempt).where(Attempt.session_id == s.id).order_by(Attempt.started_at))
    ).all()
    open_ = session_open(s)
    join_left = 0
    if s.join_window_min and open_:
        join_left = max(0, int((s.started_at + timedelta(minutes=s.join_window_min) - utcnow()).total_seconds()))
    return {
        "id": s.id,
        "code": s.code,
        "group": s.group_name,
        "test_title": test.title,
        "active": open_,
        "seconds_left": max(0, int((s.ends_at - utcnow()).total_seconds())) if open_ else 0,
        "join_window_min": s.join_window_min,
        "join_seconds_left": join_left,  # сколько ещё можно войти по коду (0 — приём закрыт)
        "duration_min": s.duration_min,
        "question_count": s.question_count,
        "max_students": s.max_students,
        "max_leaves": s.max_leaves,
        "joined": len(attempts),
        "finished_count": sum(1 for a in attempts if a.is_finished),
        "students": [
            {
                "attempt_id": a.id,
                "name": a.full_name,
                "answered": a.current_index,
                "total": a.total,
                "correct": a.correct_count,
                "leaves": a.leaves,
                "leave_seconds": a.leave_seconds,
                "finished": a.is_finished,
                "reason": _fmt_reason(a.finish_reason),
            }
            for a in attempts
        ],
    }


async def kick_student(db: AsyncSession, teacher: User, session_id: int, attempt_id: int):
    s = await _own_session(db, teacher, session_id)
    a = await db.get(Attempt, attempt_id)
    if a is None or a.session_id != s.id:
        raise ServiceError("Студент не найден.", 404)
    if not a.is_finished:
        a.finished_at = utcnow()
    a.finish_reason = "kicked"
    await db.commit()


async def session_results(db: AsyncSession, teacher: User, session_id: int) -> dict:
    s = await _own_session(db, teacher, session_id)
    live = await session_live(db, teacher, session_id)
    attempts = (await db.scalars(select(Attempt).where(Attempt.session_id == s.id))).all()
    counted = [a for a in attempts if a.finish_reason != "kicked"]
    ranking = sorted(
        (
            {
                "name": a.full_name,
                "correct": a.correct_count,
                "total": a.total,
                "percent": round(a.correct_count * 100 / a.total) if a.total else 0,
                "duration_sec": int(((a.finished_at or utcnow()) - a.started_at).total_seconds()),
                "leaves": a.leaves,
                "reason": _fmt_reason(a.finish_reason),
                "suspicious": a.leaves > 0 or a.finish_reason == "leaves",
            }
            for a in counted
        ),
        key=lambda r: (-r["correct"], r["duration_sec"]),
    )
    stats_rows = (
        await db.execute(
            select(Answer.question_id, func.count(), func.sum(Answer.is_correct.cast(Integer)))
            .join(Attempt, Attempt.id == Answer.attempt_id)
            .where(
                Attempt.session_id == s.id,
                or_(Attempt.finish_reason.is_(None), Attempt.finish_reason != "kicked"),
            )
            .group_by(Answer.question_id)
        )
    ).all()
    qmap = {}
    if stats_rows:
        qmap = {
            q.id: q
            for q in (
                await db.scalars(select(Question).where(Question.id.in_([r[0] for r in stats_rows])))
            ).all()
        }
    hardest = sorted(
        (
            {
                "text": qmap[qid].text,
                "answers": n,
                "correct_percent": round((ok or 0) * 100 / n),
                "right_answer": qmap[qid].options[qmap[qid].correct],
            }
            for qid, n, ok in stats_rows
            if n
        ),
        key=lambda r: (r["correct_percent"], -r["answers"]),
    )[:10]
    avg = round(sum(r["percent"] for r in ranking) / len(ranking)) if ranking else None
    return {**live, "ranking": ranking, "hardest": hardest, "avg_percent": avg}


async def export_xlsx(db: AsyncSession, teacher: User, session_id: int) -> tuple[str, bytes]:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    r = await session_results(db, teacher, session_id)
    wb = Workbook()
    ws = wb.active
    ws.title = "Результаты"
    ws.append([f"{r['test_title']} — группа {r['group']}"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([])
    ws.append(["№", "ФИО", "Правильно", "Всего", "%", "Время (мин:сек)", "Сворачивал", "Статус"])
    for c in ws[3]:
        c.font = Font(bold=True)
    for i, row in enumerate(r["ranking"], start=1):
        m, sec = divmod(row["duration_sec"], 60)
        ws.append([i, row["name"], row["correct"], row["total"], row["percent"], f"{m}:{sec:02d}", row["leaves"], row["reason"]])
    ws.append([])
    ws.append(["Средний результат, %", r["avg_percent"]])
    ws.column_dimensions["B"].width = 36
    ws.column_dimensions["H"].width = 24
    if r["hardest"]:
        ws2 = wb.create_sheet("Сложные вопросы")
        ws2.append(["Вопрос", "Ответили верно, %", "Всего ответов", "Правильный ответ"])
        for c in ws2[1]:
            c.font = Font(bold=True)
        for h in r["hardest"]:
            ws2.append([h["text"], h["correct_percent"], h["answers"], h["right_answer"]])
        ws2.column_dimensions["A"].width = 60
        ws2.column_dimensions["D"].width = 30
    buf = io.BytesIO()
    wb.save(buf)
    safe_group = "".join(ch for ch in r["group"] if ch.isalnum() or ch in "-_") or "group"
    return f"results_{safe_group}_{session_id}.xlsx", buf.getvalue()


# ---------------------------------------------------------------- админ

async def admin_stats(db: AsyncSession) -> dict:
    day_ago = utcnow() - timedelta(days=1)
    week_ago = utcnow() - timedelta(days=7)
    return {
        "users": await db.scalar(select(func.count()).select_from(User)),
        "teachers": await db.scalar(select(func.count()).select_from(User).where(User.role == "teacher")),
        "pending": await db.scalar(
            select(func.count()).select_from(User).where(User.teacher_pending.is_(True), User.role != "teacher")
        ),
        "pro": await db.scalar(
            select(func.count()).select_from(User).where(User.plan == "pro", User.pro_until > utcnow())
        ),
        "tests": await db.scalar(select(func.count()).select_from(Test)),
        "presentations": await db.scalar(select(func.coalesce(func.sum(User.pres_total), 0))),
        # Деньги: всего зачислено (подтверждённые пополнения) и сколько заявок ждёт подтверждения.
        "revenue": await db.scalar(
            select(func.coalesce(func.sum(TopUp.amount), 0)).where(TopUp.status == "approved")
        ),
        "topups_pending": await db.scalar(
            select(func.count()).select_from(TopUp).where(TopUp.status == "pending")
        ),
        "sessions_day": await db.scalar(
            select(func.count()).select_from(TestSession).where(TestSession.started_at >= day_ago)
        ),
        "sessions_week": await db.scalar(
            select(func.count()).select_from(TestSession).where(TestSession.started_at >= week_ago)
        ),
        "attempts_week": await db.scalar(
            select(func.count()).select_from(Attempt).where(Attempt.started_at >= week_ago)
        ),
    }


async def list_teachers(db: AsyncSession) -> list[User]:
    return list(
        (await db.scalars(select(User).where(User.role == "teacher").order_by(User.created_at))).all()
    )


async def users_by_audience(db: AsyncSession, audience: str) -> list[int]:
    """ID получателей рассылки (без заблокированных). teachers / students / all."""
    q = select(User.id).where(User.blocked.is_(False))
    if audience == "teachers":
        q = q.where(User.role == "teacher")
    elif audience == "students":
        q = q.where(User.role == "student")
    return list((await db.scalars(q)).all())


async def grant_balance(db: AsyncSession, audience: str, amount: int) -> list[int]:
    """Начислить сумму на баланс всем получателям аудитории (без заблокированных).
    Возвращает ID тех, кому начислили."""
    amount = int(amount)
    if amount <= 0:
        raise ServiceError("Сумма должна быть больше нуля.")
    ids = await users_by_audience(db, audience)
    if ids:
        await db.execute(update(User).where(User.id.in_(ids)).values(balance=User.balance + amount))
        await db.commit()
    return ids


# ---------------------------------------------------------------- админ-панель

ACTION_NAMES = {
    ("POST", "/api/teacher/tests/upload"): "загрузил тест",
    ("POST", "/api/teacher/subjects"): "создал предмет",
    ("POST", "/api/teacher/sessions"): "запустил тест",
    ("PUT", "/api/teacher/questions"): "изменил вопрос",
    ("DELETE", "/api/teacher/questions"): "удалил вопрос",
    ("DELETE", "/api/teacher/tests"): "удалил тест",
    ("PATCH", "/api/teacher/tests"): "переименовал тест",
    ("DELETE", "/api/teacher/subjects"): "удалил предмет",
}


def describe_action(method: str, path: str) -> str:
    for (m, prefix), name in ACTION_NAMES.items():
        if method == m and path.startswith(prefix):
            return name
    if path.endswith("/finish"):
        return "завершил тест"
    if path.endswith("/kick"):
        return "удалил студента из теста"
    if path.endswith("/archive"):
        return "архив теста"
    if path.endswith("/questions"):
        return "добавил вопрос"
    if path.endswith("/export"):
        return "выгрузил Excel"
    return f"{method} {path}"


def add_admin_log(db: AsyncSession, admin_id: int, target_id: int | None, action: str):
    from .models import AdminLog

    db.add(AdminLog(admin_id=admin_id, target_id=target_id, action=action[:300]))


async def admin_teachers(db: AsyncSession, query: str = "", status: str = "all") -> list[dict]:
    users = (
        await db.scalars(
            select(User)
            .where(or_(User.role == "teacher", User.teacher_pending.is_(True)))
            .order_by(User.created_at.desc())
        )
    ).all()
    if query:
        ql = query.lower().lstrip("@")
        users = [
            u
            for u in users
            if ql in (u.full_name or "").lower()
            or ql in (u.username or "").lower()
            or ql in (u.teacher_info or "").lower()
            or ql in (u.teacher_kafedra or "").lower()
            or ql == str(u.id)
        ]
    ids = [u.id for u in users]
    tests, sessions, students, last = {}, {}, {}, {}
    if ids:
        tests = dict(
            (await db.execute(select(Test.teacher_id, func.count()).where(Test.teacher_id.in_(ids)).group_by(Test.teacher_id))).all()
        )
        for tid, n, mx in (
            await db.execute(
                select(TestSession.teacher_id, func.count(), func.max(TestSession.started_at))
                .where(TestSession.teacher_id.in_(ids))
                .group_by(TestSession.teacher_id)
            )
        ).all():
            sessions[tid], last[tid] = n, mx
        students = dict(
            (
                await db.execute(
                    select(TestSession.teacher_id, func.count(Attempt.id))
                    .join(Attempt, Attempt.session_id == TestSession.id)
                    .where(TestSession.teacher_id.in_(ids))
                    .group_by(TestSession.teacher_id)
                )
            ).all()
        )
    out = [
        {
            "id": u.id,
            "name": u.full_name,
            "username": u.username,
            "info": u.teacher_info,
            "kafedra": u.teacher_kafedra,
            "role": u.role,
            "status": "pending" if (u.teacher_pending and u.role != "teacher") else "teacher",
            "plan": "pro" if u.is_pro else "free",
            "pro_until": u.pro_until.isoformat() if u.is_pro else None,
            "blocked": u.blocked,
            "is_admin": u.id in settings.admin_ids,
            "tests": tests.get(u.id, 0),
            "sessions": sessions.get(u.id, 0),
            "attempts": students.get(u.id, 0),
            "last_session": last[u.id].isoformat() if last.get(u.id) else None,
            "created_at": u.created_at.isoformat(),
        }
        for u in users
    ]
    out.sort(key=lambda r: 0 if r["status"] == "pending" else 1)  # заявки сверху
    return out


async def remove_teacher(db: AsyncSession, user_id: int) -> User:
    """Снять роль преподавателя: пользователь становится обычным студентом.
    Аккаунт, его тесты и вся история сохраняются — роль можно вернуть новой заявкой."""
    user = await db.get(User, user_id)
    if user is None:
        raise ServiceError("Пользователь не найден.", 404)
    if user_id in settings.admin_ids:
        raise ServiceError("Нельзя снять роль у администратора.")
    user.role = "student"
    user.teacher_pending = False
    user.plan = "free"  # вместе со статусом снимаем и Pro
    user.pro_until = None
    await db.commit()
    return user


async def remove_pro(db: AsyncSession, user_id: int) -> User:
    """Снять Pro-подписку (пользователь переходит на бесплатный тариф)."""
    user = await db.get(User, user_id)
    if user is None:
        raise ServiceError("Пользователь не найден.", 404)
    user.plan = "free"
    user.pro_until = None
    await db.commit()
    return user


async def set_blocked(db: AsyncSession, user_id: int, blocked: bool) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise ServiceError("Пользователь не найден.", 404)
    if user_id in settings.admin_ids:
        raise ServiceError("Нельзя заблокировать админа.")
    user.blocked = blocked
    await db.commit()
    return user


async def admin_log(db: AsyncSession, limit: int = 100) -> list[dict]:
    from .models import AdminLog

    rows = (await db.scalars(select(AdminLog).order_by(AdminLog.created_at.desc()).limit(limit))).all()
    ids = {r.target_id for r in rows if r.target_id} | {r.admin_id for r in rows}
    names = {}
    if ids:
        names = dict((await db.execute(select(User.id, User.full_name).where(User.id.in_(ids)))).all())
    return [
        {
            "admin": names.get(r.admin_id) or str(r.admin_id),
            "target": names.get(r.target_id) or (str(r.target_id) if r.target_id else ""),
            "action": r.action,
            "at": r.created_at.isoformat(),
        }
        for r in rows
    ]


# ---------------------------------------------------------------- электронная библиотека

LIBRARY_EXT = (".pdf", ".docx", ".txt", ".md")


async def list_library_subjects(db: AsyncSession, with_counts: bool = False) -> list[dict]:
    subs = (
        await db.scalars(select(LibrarySubject).order_by(LibrarySubject.position, LibrarySubject.name))
    ).all()
    counts = {}
    if with_counts:
        counts = dict(
            (
                await db.execute(
                    select(LibraryDoc.subject_id, func.count())
                    .where(LibraryDoc.status == "approved")
                    .group_by(LibraryDoc.subject_id)
                )
            ).all()
        )
    return [{"id": s.id, "name": s.name, "docs": counts.get(s.id, 0)} for s in subs]


async def add_library_subject(db: AsyncSession, name: str) -> LibrarySubject:
    name = " ".join((name or "").split())
    if not name:
        raise ServiceError("Введите название предмета.")
    # SQLite lower() не трогает кириллицу — сравниваем в Python.
    existing = (await db.scalars(select(LibrarySubject.name))).all()
    if any((e or "").lower() == name.lower() for e in existing):
        raise ServiceError("Такой предмет уже есть.")
    pos = await db.scalar(select(func.coalesce(func.max(LibrarySubject.position), 0)))
    s = LibrarySubject(name=name[:200], position=(pos or 0) + 1)
    db.add(s)
    await db.commit()
    return s


async def rename_library_subject(db: AsyncSession, subject_id: int, name: str) -> LibrarySubject:
    s = await db.get(LibrarySubject, subject_id)
    if s is None:
        raise ServiceError("Предмет не найден.", 404)
    name = " ".join((name or "").split())
    if not name:
        raise ServiceError("Введите название предмета.")
    s.name = name[:200]
    await db.commit()
    return s


async def delete_library_subject(db: AsyncSession, subject_id: int):
    s = await db.get(LibrarySubject, subject_id)
    if s is None:
        raise ServiceError("Предмет не найден.", 404)
    n = await db.scalar(select(func.count()).select_from(LibraryDoc).where(LibraryDoc.subject_id == subject_id))
    if n:
        raise ServiceError("Нельзя удалить предмет: в нём есть материалы.")
    await db.execute(delete(LibrarySubject).where(LibrarySubject.id == subject_id))
    await db.commit()


import os as _os
# Крупнее этого — текст не извлекаем (pypdf читает постранично, но PdfReader всё же держит
# структуру файла в памяти; на 1 ГБ VPS разумный потолок). Настраивается LIBRARY_EXTRACT_MAX_MB.
LIBRARY_TEXT_EXTRACT_MAX = int(_os.getenv("LIBRARY_EXTRACT_MAX_MB", "60")) * 1024 * 1024
LIBRARY_TEXT_STORE_MAX = 4_000_000  # максимум символов текста в БД (чтобы не раздувать базу/бэкап)


async def add_library_doc_from_path(
    db: AsyncSession, teacher: User, subject_id: int, title: str, filename: str,
    content_type: str | None, src_path: str, size: int,
) -> LibraryDoc:
    """Создать материал из уже сохранённого на диске файла (память не держим). На модерацию."""
    import os

    from .parsers import extract_document_text_path

    try:
        if not teacher.is_teacher:
            raise ServiceError("Загружать материалы в библиотеку могут только преподаватели.", 403)
        subj = await db.get(LibrarySubject, subject_id)
        if subj is None:
            raise ServiceError("Предмет не найден.", 404)
        title = " ".join((title or "").split())
        if not title:
            raise ServiceError("Введите название материала.")
        if not (filename or "").lower().endswith(LIBRARY_EXT):
            raise ServiceError("Поддерживаются файлы .pdf, .docx и .txt.")
    except Exception:
        try:
            os.remove(src_path)  # не оставляем временный файл
        except OSError:
            pass
        raise
    text = ""
    if 0 < size <= LIBRARY_TEXT_EXTRACT_MAX:  # для поиска/ИИ; у огромных сканов текста нет
        try:
            # извлечение текста из PDF — тяжёлое и блокирующее; уводим в отдельный поток,
            # чтобы загрузка большой книги НЕ подвешивала бот/приложение для остальных
            raw = await asyncio.to_thread(extract_document_text_path, filename, src_path)
            text = (raw or "")[:LIBRARY_TEXT_STORE_MAX]
        except Exception:
            text = ""
    doc = LibraryDoc(
        subject_id=subject_id, title=title[:300], filename=(filename or "file")[:300],
        content_type=content_type, size=size, path="", text=text,
        uploaded_by=teacher.id, status="pending",
    )
    db.add(doc)
    await db.flush()  # получить id для имени файла
    safe = "".join(ch for ch in (filename or "file") if ch.isalnum() or ch in "._- ").strip() or "file"
    os.makedirs(settings.library_dir, exist_ok=True)
    final = os.path.join(settings.library_dir, f"{doc.id}_{safe}")
    os.replace(src_path, final)  # перемещаем temp → финал
    doc.path = final
    await db.commit()
    return doc


async def add_library_doc(
    db: AsyncSession, teacher: User, subject_id: int, title: str, filename: str, content_type: str | None, data: bytes
) -> LibraryDoc:
    """Обёртка для небольших файлов/тестов: пишет bytes во временный файл и создаёт материал."""
    import os
    import tempfile

    os.makedirs(settings.library_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=settings.library_dir)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return await add_library_doc_from_path(db, teacher, subject_id, title, filename, content_type, tmp, len(data))


async def list_library_docs(
    db: AsyncSession, subject_id: int | None = None, q: str = "", status: str = "approved", limit: int = 200
) -> list[dict]:
    query = select(LibraryDoc).where(LibraryDoc.status == status)
    if subject_id:
        query = query.where(LibraryDoc.subject_id == subject_id)
    docs = (await db.scalars(query.order_by(LibraryDoc.created_at.desc()))).all()
    ql = (q or "").strip().lower()
    if ql:
        # SQLite lower() не трогает кириллицу → фильтруем в Python (по названию и тексту).
        docs = [d for d in docs if ql in (d.title or "").lower() or ql in (d.text or "").lower()]
    docs = docs[:limit]
    subj = dict((await db.execute(select(LibrarySubject.id, LibrarySubject.name))).all())
    uploaders = {}
    if docs:
        uploaders = dict(
            (await db.execute(select(User.id, User.full_name).where(User.id.in_({d.uploaded_by for d in docs})))).all()
        )
    return [
        {
            "id": d.id,
            "title": d.title,
            "subject_id": d.subject_id,
            "subject": subj.get(d.subject_id, ""),
            "filename": d.filename,
            "size": d.size,
            "status": d.status,
            "by": uploaders.get(d.uploaded_by) or "",
            "created_at": d.created_at.isoformat(),
        }
        for d in docs
    ]


async def get_library_doc(db: AsyncSession, doc_id: int, allow_pending: bool = False) -> dict:
    d = await db.get(LibraryDoc, doc_id)
    if d is None or (d.status != "approved" and not allow_pending):
        raise ServiceError("Материал не найден.", 404)
    subj = await db.get(LibrarySubject, d.subject_id)
    return {
        "id": d.id,
        "title": d.title,
        "subject": subj.name if subj else "",
        "subject_id": d.subject_id,
        "filename": d.filename,
        "size": d.size,
        "status": d.status,
        "text": d.text or "",
        "created_at": d.created_at.isoformat(),
    }


async def library_doc_file(db: AsyncSession, doc_id: int, allow_pending: bool = False) -> tuple[str, bytes]:
    d = await db.get(LibraryDoc, doc_id)
    if d is None or (d.status != "approved" and not allow_pending):
        raise ServiceError("Материал не найден.", 404)
    try:
        with open(d.path, "rb") as f:
            return d.filename, f.read()
    except OSError:
        raise ServiceError("Файл не найден на сервере.", 404)


async def library_doc_path(db: AsyncSession, doc_id: int, allow_pending: bool = False) -> tuple[str, str]:
    """Путь к файлу материала на диске (для отдачи с поддержкой Range → streaming)."""
    import os

    d = await db.get(LibraryDoc, doc_id)
    if d is None or (d.status != "approved" and not allow_pending):
        raise ServiceError("Материал не найден.", 404)
    if not d.path or not os.path.exists(d.path):
        raise ServiceError("Файл не найден на сервере.", 404)
    return d.path, d.filename


async def library_doc_search(db: AsyncSession, doc_id: int, q: str, allow_pending: bool = False) -> dict:
    """Поиск слова/темы по страницам PDF. Возвращает номера страниц (1-based), где встречается.
    Работает только для PDF с текстовым слоем (в сканах текста нет)."""
    d = await db.get(LibraryDoc, doc_id)
    if d is None or (d.status != "approved" and not allow_pending):
        raise ServiceError("Материал не найден.", 404)
    q = " ".join((q or "").split()).lower()
    if len(q) < 2:
        return {"pages": [], "total": 0}
    if not (d.filename or "").lower().endswith(".pdf"):
        return {"pages": [], "total": 0}
    def _scan(path: str, needle: str):
        from pypdf import PdfReader

        reader = PdfReader(path)
        total = len(reader.pages)
        pages: list[int] = []
        for i, page in enumerate(reader.pages, 1):
            try:
                txt = (page.extract_text() or "").lower()
            except Exception:
                txt = ""
            if needle in txt:
                pages.append(i)
            if len(pages) >= 60:  # не отдаём бесконечный список
                break
        return pages, total

    try:
        # постраничное чтение PDF — блокирующее; уводим в поток, чтобы поиск по большой
        # книге не подвешивал бот/приложение
        pages, total = await asyncio.to_thread(_scan, d.path, q)
    except Exception:
        return {"pages": [], "total": 0}
    return {"pages": pages, "total": total}


async def decide_library_doc(db: AsyncSession, doc_id: int, approve: bool, admin_id: int) -> LibraryDoc:
    d = await db.get(LibraryDoc, doc_id)
    if d is None:
        raise ServiceError("Материал не найден.", 404)
    d.status = "approved" if approve else "rejected"
    d.approved_by = admin_id
    d.approved_at = utcnow()
    await db.commit()
    if approve:
        # индексируем для RAG (лучшая попытка: ошибка эмбеддингов не должна срывать одобрение)
        try:
            await index_library_doc(db, d)
        except Exception:
            pass
        # Иллюстрации из PDF режем НЕ здесь (тяжело: vision на каждую фигуру) — лишь помечаем
        # книгу к обработке, чтобы одобрение было мгновенным. Режет фоновый воркер (режим
        # background) или ночной прогон (режим night) — см. app/figjobs.py.
        if settings.library_figures_enabled and (d.filename or "").lower().endswith(".pdf") and d.path:
            d.figures_status = "pending"
            await db.commit()
            if settings.library_figures_mode != "night":
                from . import figjobs
                figjobs.enqueue(d.id)
    else:
        await _delete_doc_chunks(db, doc_id)
        await _delete_doc_figures(db, doc_id)
    return d


async def delete_library_doc(db: AsyncSession, doc_id: int):
    import os

    d = await db.get(LibraryDoc, doc_id)
    if d is None:
        raise ServiceError("Материал не найден.", 404)
    if d.path:
        try:
            os.remove(d.path)
        except OSError:
            pass
    await _delete_doc_figures(db, doc_id)  # файлы фигур + записи
    await db.execute(delete(LibraryChunk).where(LibraryChunk.doc_id == doc_id))
    await db.execute(delete(LibraryDoc).where(LibraryDoc.id == doc_id))
    await db.commit()
    invalidate_vec_cache()


# ------------------------------------------------------------------ RAG: индексация и поиск

# Кэш векторов в памяти: не читаем их с диска на КАЖДУЮ генерацию. Храним только
# (chunk_id, doc_id, нормализованный вектор) — ~2 КБ/кусок (на ~4400 кусков ~15 МБ).
# Тексты топ-кусков и названия берём из БД точечно (это копейки). Сбрасывается при
# добавлении/удалении материала, так что всегда актуален. Качество поиска не меняется.
_vec_cache: list[tuple[int, int, list[float]]] | None = None


def invalidate_vec_cache() -> None:
    global _vec_cache
    _vec_cache = None


async def _get_vec_cache(db: AsyncSession) -> list[tuple[int, int, list[float]]]:
    global _vec_cache
    if _vec_cache is None:
        from . import embeddings as emb

        rows = (await db.execute(
            select(LibraryChunk.id, LibraryChunk.doc_id, LibraryChunk.vector)
        )).all()
        _vec_cache = [(cid, did, emb.unpack(blob)) for cid, did, blob in rows]
    return _vec_cache


async def _delete_doc_chunks(db: AsyncSession, doc_id: int):
    await db.execute(delete(LibraryChunk).where(LibraryChunk.doc_id == doc_id))
    await db.commit()
    invalidate_vec_cache()


# --- Фигуры из книг (иллюстрации для слайдов). Включается settings.library_figures_enabled. ---
_fig_cache: list[tuple[int, int, str, list[float]]] | None = None  # (fig_id, doc_id, path, вектор)


def invalidate_fig_cache() -> None:
    global _fig_cache
    _fig_cache = None


async def _get_fig_cache(db: AsyncSession):
    global _fig_cache
    if _fig_cache is None:
        from . import embeddings as emb

        rows = (await db.execute(
            select(LibraryFigure.id, LibraryFigure.doc_id, LibraryFigure.path, LibraryFigure.vector)
            .where(LibraryFigure.vector.is_not(None))
        )).all()
        _fig_cache = [(fid, did, path, emb.unpack(blob)) for fid, did, path, blob in rows if blob]
    return _fig_cache


async def _delete_doc_figures(db: AsyncSession, doc_id: int):
    import os

    rows = (await db.execute(select(LibraryFigure.path).where(LibraryFigure.doc_id == doc_id))).all()
    for (p,) in rows:
        try:
            os.remove(p)
        except OSError:
            pass
    await db.execute(delete(LibraryFigure).where(LibraryFigure.doc_id == doc_id))
    await db.commit()
    invalidate_fig_cache()


async def index_doc_figures(db: AsyncSession, doc: LibraryDoc) -> int:
    """Вырезает иллюстрации из PDF, подписывает зрением, эмбеддит подпись, сохраняет на диск+БД.
    Заменяет старые. Тяжело (vision на каждую фигуру) — только по флагу. Возвращает число фигур."""
    import os

    from . import ai
    from . import embeddings as emb
    from . import figures as figmod

    if not settings.library_figures_enabled or not emb.is_enabled():
        return 0
    if not (doc.filename or "").lower().endswith(".pdf") or not doc.path:
        return 0
    await _delete_doc_figures(db, doc.id)
    figs = await asyncio.to_thread(figmod.extract_pdf_figures, doc.path)
    if not figs:
        return 0
    base = os.path.join(settings.library_dir, "figures", str(doc.id))
    os.makedirs(base, exist_ok=True)
    saved = 0
    for i, f in enumerate(figs):
        b64 = figmod.vision_thumb_b64(f["data"])
        if not b64:
            continue
        caption = await ai.describe_image(b64)
        if not caption:
            continue
        try:
            vec = (await emb.embed_texts([caption], input_type="document"))[0]
        except Exception:
            continue
        path = os.path.join(base, f"{i}.jpg")
        try:
            with open(path, "wb") as fh:
                fh.write(f["data"])
        except OSError:
            continue
        db.add(LibraryFigure(
            doc_id=doc.id, subject_id=doc.subject_id, page=f["page"], path=path,
            w=f["w"], h=f["h"], caption=caption, dim=len(vec), vector=emb.pack(vec),
        ))
        saved += 1
    await db.commit()
    invalidate_fig_cache()
    return saved


async def pending_figure_doc_ids(db: AsyncSession) -> list[int]:
    """ID одобренных PDF-книг, ожидающих извлечения фигур (figures_status='pending')."""
    rows = (await db.execute(
        select(LibraryDoc.id)
        .where(LibraryDoc.status == "approved", LibraryDoc.figures_status == "pending")
        .order_by(LibraryDoc.id)
    )).all()
    return [r[0] for r in rows]


async def reindex_figures(db: AsyncSession, only_pending: bool = False) -> dict:
    """Бэкофилл фигур: вырезать иллюстрации из одобренных PDF (только при включённом флаге).
    only_pending=True — лишь книги со статусом pending (ночной прогон). Проставляет figures_status.
    Тяжело (vision на каждую фигуру) — запускать осознанно."""
    import logging

    from . import embeddings as emb

    if not settings.library_figures_enabled or not emb.is_enabled():
        return {"docs": 0, "figures": 0, "note": "LIBRARY_FIGURES выключен или нет ключа"}
    q = select(LibraryDoc).where(LibraryDoc.status == "approved")
    if only_pending:
        q = q.where(LibraryDoc.figures_status == "pending")
    docs = (await db.scalars(q.order_by(LibraryDoc.id))).all()
    d_cnt = f_cnt = 0
    for d in docs:
        if not (d.filename or "").lower().endswith(".pdf"):
            continue
        try:
            n = await index_doc_figures(db, d)
            d.figures_status = "done"
        except Exception:
            logging.getLogger("testroom.figjobs").exception("reindex_figures: ошибка на doc=%s", d.id)
            d.figures_status = "error"
            n = 0
        await db.commit()
        if n:
            d_cnt += 1
            f_cnt += n
    return {"docs": d_cnt, "figures": f_cnt}


async def figure_candidates_for(topic: str, k: int | None = None) -> list[dict]:
    """Топ-k фигур книг по теме слайда (по эмбеддингу подписи). Возвращает кандидатов в том же
    формате, что веб-фото ({data, vb64, ah, source}) — их дальше оценит зрение вместе с веб-фото.
    Открывает свою сессию БД (подбор фото не имеет доступа к db)."""
    from . import embeddings as emb
    from .db import SessionLocal
    from .images import _thumb_and_hash

    if not settings.library_figures_enabled or not emb.is_enabled():
        return []
    topic = " ".join((topic or "").split())
    if not topic:
        return []
    k = k or settings.library_figures_topk
    try:
        qv = emb.normalize((await emb.embed_texts([topic], input_type="query", max_retries=1))[0])
    except Exception:
        return []
    cache = _fig_cache
    if cache is None:  # загружаем из БД только один раз, дальше — из памяти (без сессий под нагрузкой)
        async with SessionLocal() as db:
            cache = await _get_fig_cache(db)
    if not cache:
        return []
    scored = sorted(((emb.dot(qv, vec), fid, path) for fid, did, path, vec in cache), reverse=True)
    out: list[dict] = []
    for score, fid, path in scored[: k * 2]:
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError:
            continue
        vb, ah = _thumb_and_hash(data)
        if not vb:
            continue
        out.append({"data": data, "vb64": vb, "ah": ah, "source": "Библиотека (книга)", "path": path})
        if len(out) >= k:
            break
    return out


async def index_library_doc(db: AsyncSession, doc: LibraryDoc, pace: float = 0.0) -> int:
    """Нарезает текст одобренного материала на куски, считает эмбеддинги и сохраняет.
    Старые куски этого документа заменяет. Возвращает число сохранённых кусков.
    pace — пауза между запросами (бэкофилл под rate limit); 0 — без пауз (одиночное одобрение)."""
    from . import embeddings as emb

    if not emb.is_enabled():
        return 0
    await _delete_doc_chunks(db, doc.id)
    chunks = emb.chunk_text(doc.text or "")
    if not chunks:
        return 0
    vectors = await emb.embed_texts(chunks, input_type="document", pace=pace)
    for i, (txt, vec) in enumerate(zip(chunks, vectors)):
        db.add(LibraryChunk(
            doc_id=doc.id, subject_id=doc.subject_id, idx=i,
            text=txt, dim=len(vec), vector=emb.pack(vec),
        ))
    await db.commit()
    invalidate_vec_cache()  # добавились куски → кэш пересоберётся при следующем поиске
    return len(chunks)


async def reindex_library(db: AsyncSession, only_missing: bool = True) -> dict:
    """Бэкофилл: проиндексировать одобренные материалы. only_missing — пропускать уже с кусками."""
    from . import embeddings as emb

    if not emb.is_enabled():
        return {"indexed": 0, "chunks": 0, "skipped": 0, "note": "VOYAGE_API_KEY не задан"}
    docs = (await db.scalars(
        select(LibraryDoc).where(LibraryDoc.status == "approved").order_by(LibraryDoc.id)
    )).all()
    indexed = chunks = skipped = 0
    for d in docs:
        if only_missing:
            has = await db.scalar(select(func.count()).select_from(LibraryChunk).where(LibraryChunk.doc_id == d.id))
            if has:
                skipped += 1
                continue
        if not (d.text or "").strip():
            skipped += 1
            continue
        n = await index_library_doc(db, d, pace=settings.rag_backfill_pace)
        if n:
            indexed += 1
            chunks += n
    return {"indexed": indexed, "chunks": chunks, "skipped": skipped}


async def library_context(
    db: AsyncSession, query: str, k: int | None = None, min_score: float | None = None
) -> dict:
    """Ищет в библиотеке самые близкие к теме куски (косинус по эмбеддингам).

    Возвращает {found, context, sources, score}. found=False → релевантного нет, генерим как обычно."""
    from . import embeddings as emb

    empty = {"found": False, "context": "", "sources": [], "score": 0.0}
    query = " ".join((query or "").split())
    if not query or not emb.is_enabled():
        return empty
    k = k or settings.rag_top_k
    min_score = settings.rag_min_score if min_score is None else min_score
    try:
        # быстрый отказ: при rate limit не заставляем пользователя ждать — просто фолбэк на общие знания
        qvec = emb.normalize((await emb.embed_texts([query], input_type="query", max_retries=1))[0])
    except Exception:
        return empty
    cache = await _get_vec_cache(db)  # векторы из памяти (не читаем с диска каждый раз)
    if not cache:
        return empty
    scored = [(emb.dot(qvec, vec), cid, did) for cid, did, vec in cache]
    scored.sort(key=lambda x: x[0], reverse=True)
    top = [s for s in scored[:k] if s[0] >= min_score]
    if not top:
        return empty
    # тексты только топ-кусков и названия книг — маленькие точечные запросы
    chunk_ids = [t[1] for t in top]
    doc_ids = {t[2] for t in top}
    texts = dict((await db.execute(
        select(LibraryChunk.id, LibraryChunk.text).where(LibraryChunk.id.in_(chunk_ids)))).all())
    titles = dict((await db.execute(
        select(LibraryDoc.id, LibraryDoc.title).where(LibraryDoc.id.in_(doc_ids)))).all())
    parts, sources = [], []
    for score, cid, did in top:
        title = titles.get(did, "")
        parts.append(f"[Источник: {title}]\n{texts.get(cid, '')}")
        if title and title not in sources:
            sources.append(title)
    return {"found": True, "context": "\n\n---\n\n".join(parts), "sources": sources, "score": round(top[0][0], 3)}
