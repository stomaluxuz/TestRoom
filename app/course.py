"""Учебный путь: курс из силлабуса. ИИ разбирает силлабус на темы и по каждой генерит
теорию (конспект) и тест. Студент: читает теорию → проходит тест → прогресс.

Генерация тяжёлая (теория + тест на каждую тему), поэтому идёт в фоне, по одной теме,
с уведомлением владельцу в бот. Тест темы хранится как JSON (как в квизе) — без привязки
к Test/Subject.
"""
from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Course, CourseProgress, CourseTopic, User, utcnow
from .services import ServiceError, require_teacher

MAX_TOPICS = 40
TEST_PER_TOPIC = 10


async def create_course(db: AsyncSession, owner: User, title: str, info: str, lang: str,
                        topics: list[str]) -> Course:
    """Создать курс с темами (status pending). Генерацию запускает эндпоинт в фоне."""
    require_teacher(owner)
    clean = [" ".join((t or "").split())[:400] for t in (topics or []) if (t or "").strip()][:MAX_TOPICS]
    if not clean:
        raise ServiceError("Не из чего собрать курс — список тем пуст.")
    course = Course(
        owner_id=owner.id, title=(title or "Курс").strip()[:300], info=(info or "").strip()[:300],
        lang=lang if lang in ("ru", "uz", "en") else "ru", status="building", published=True,
    )
    db.add(course)
    await db.flush()
    for i, tp in enumerate(clean):
        db.add(CourseTopic(course_id=course.id, position=i, title=tp, status="pending"))
    await db.commit()
    return course


async def _build_one(db: AsyncSession, title: str, course_title: str, lang: str, topic: CourseTopic):
    """Сгенерировать теорию и тест для одной темы (ИИ не держит соединение с БД)."""
    from . import ai, limits
    from .services import library_context

    try:
        ctx = await library_context(db, title)
    except Exception:
        ctx = {"context": "", "sources": []}
    await db.rollback()  # освобождаем соединение на время ИИ
    context = ctx.get("context", "")
    async with limits.gen_slot():
        theory = await ai.generate_theory(title, course_title, lang, context)
        parsed = await ai.generate_test_questions(title, TEST_PER_TOPIC, lang=lang, context=context)
    questions = [
        {"q": p.text, "options": p.options, "correct": p.correct}
        for p in parsed if p.correct is not None and p.correct >= 0 and len(p.options) >= 2
    ]
    topic.theory = (theory or "")[:20000]
    topic.questions = questions
    topic.sources = (ctx.get("sources") or [])[:5]
    topic.status = "done" if (theory and questions) else "error"
    await db.commit()


async def build_course(course_id: int, notify=None):
    """Фоновая сборка: по каждой теме генерим теорию+тест. По готовности — status=ready и уведомление."""
    from . import db as dbmod

    async with dbmod.SessionLocal() as db:
        course = await db.get(Course, course_id)
        if course is None:
            return
        course_title, lang, owner_id = course.title, course.lang, course.owner_id
        topic_ids = [t.id for t in await db.scalars(
            select(CourseTopic).where(CourseTopic.course_id == course_id).order_by(CourseTopic.position))]
    done = 0
    for tid in topic_ids:
        async with dbmod.SessionLocal() as db:
            topic = await db.get(CourseTopic, tid)
            if topic is None:
                continue
            try:
                await _build_one(db, topic.title, course_title, lang, topic)
                done += 1
            except Exception:
                async with dbmod.SessionLocal() as db2:
                    t2 = await db2.get(CourseTopic, tid)
                    if t2:
                        t2.status = "error"
                        await db2.commit()
    async with dbmod.SessionLocal() as db:
        course = await db.get(Course, course_id)
        if course:
            course.status = "ready"
            await db.commit()
    if notify:
        await notify(owner_id, course_title, done, len(topic_ids))


# ------------------------------------------------ чтение / прогресс

async def _topics(db: AsyncSession, course_id: int) -> list[CourseTopic]:
    return list(await db.scalars(
        select(CourseTopic).where(CourseTopic.course_id == course_id).order_by(CourseTopic.position)))


async def _progress_map(db: AsyncSession, user_id: int, topic_ids: list[int]) -> dict[int, CourseProgress]:
    if not topic_ids:
        return {}
    rows = await db.scalars(select(CourseProgress).where(
        CourseProgress.user_id == user_id, CourseProgress.topic_id.in_(topic_ids)))
    return {p.topic_id: p for p in rows}


async def list_courses(db: AsyncSession) -> list[dict]:
    """Готовые опубликованные курсы (для студентов)."""
    rows = await db.scalars(
        select(Course).where(Course.published.is_(True), Course.status == "ready").order_by(Course.id.desc()))
    out = []
    for c in rows:
        n = await db.scalar(select(func.count()).select_from(CourseTopic).where(CourseTopic.course_id == c.id))
        out.append({"id": c.id, "title": c.title, "info": c.info, "lang": c.lang, "topics": n or 0})
    return out


async def course_detail(db: AsyncSession, user: User, course_id: int) -> dict:
    course = await db.get(Course, course_id)
    if course is None:
        raise ServiceError("Курс не найден.", 404)
    topics = await _topics(db, course.id)
    prog = await _progress_map(db, user.id, [t.id for t in topics])
    out = {"id": course.id, "title": course.title, "info": course.info, "status": course.status, "topics": []}
    for t in topics:
        p = prog.get(t.id)
        out["topics"].append({
            "id": t.id, "position": t.position, "title": t.title, "status": t.status,
            "has_test": bool(t.questions), "read": bool(p and p.read),
            "best_correct": p.best_correct if p else 0, "best_total": p.best_total if p else 0,
        })
    return out


async def topic_detail(db: AsyncSession, user: User, topic_id: int) -> dict:
    """Теория + вопросы темы (для чтения и самопроверки)."""
    t = await db.get(CourseTopic, topic_id)
    if t is None:
        raise ServiceError("Тема не найдена.", 404)
    p = await db.scalar(select(CourseProgress).where(
        CourseProgress.user_id == user.id, CourseProgress.topic_id == topic_id))
    return {
        "id": t.id, "title": t.title, "theory": t.theory, "sources": t.sources or [],
        "questions": t.questions or [], "status": t.status,
        "read": bool(p and p.read), "best_correct": p.best_correct if p else 0,
        "best_total": p.best_total if p else 0,
    }


async def _get_progress(db: AsyncSession, user_id: int, topic_id: int) -> CourseProgress:
    p = await db.scalar(select(CourseProgress).where(
        CourseProgress.user_id == user_id, CourseProgress.topic_id == topic_id))
    if p is None:
        p = CourseProgress(user_id=user_id, topic_id=topic_id)
        db.add(p)
    return p


async def mark_read(db: AsyncSession, user: User, topic_id: int) -> dict:
    if await db.get(CourseTopic, topic_id) is None:
        raise ServiceError("Тема не найдена.", 404)
    p = await _get_progress(db, user.id, topic_id)
    p.read = True
    p.updated_at = utcnow()
    await db.commit()
    return {"ok": True}


async def submit_topic_test(db: AsyncSession, user: User, topic_id: int, correct: int, total: int) -> dict:
    t = await db.get(CourseTopic, topic_id)
    if t is None:
        raise ServiceError("Тема не найдена.", 404)
    total = max(0, min(int(total), len(t.questions or [])))
    correct = max(0, min(int(correct), total))
    p = await _get_progress(db, user.id, topic_id)
    if total and correct / total >= (p.best_correct / p.best_total if p.best_total else -1):
        p.best_correct, p.best_total = correct, total
    p.updated_at = utcnow()
    await db.commit()
    return {"best_correct": p.best_correct, "best_total": p.best_total}


# ------------------------------------------------ админ

async def admin_courses(db: AsyncSession) -> list[dict]:
    rows = await db.scalars(select(Course).order_by(Course.id.desc()))
    out = []
    for c in rows:
        n = await db.scalar(select(func.count()).select_from(CourseTopic).where(CourseTopic.course_id == c.id))
        ready = await db.scalar(select(func.count()).select_from(CourseTopic).where(
            CourseTopic.course_id == c.id, CourseTopic.status == "done"))
        out.append({"id": c.id, "title": c.title, "info": c.info, "status": c.status,
                    "topics": n or 0, "ready": ready or 0, "published": c.published})
    return out


async def delete_course(db: AsyncSession, course_id: int):
    tids = [t.id for t in await _topics(db, course_id)]
    if tids:
        await db.execute(delete(CourseProgress).where(CourseProgress.topic_id.in_(tids)))
    await db.execute(delete(CourseTopic).where(CourseTopic.course_id == course_id))
    await db.execute(delete(Course).where(Course.id == course_id))
    await db.commit()
