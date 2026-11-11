"""HTTP API для Mini App (учитель и студент)."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import AsyncIterator

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from . import db as dbmod
from . import services as svc
from .auth import AuthError, validate_init_data
from .config import settings
from .models import User
from .parsers import ParseFailed, parse_file
from .universities import UNIVERSITIES

log = logging.getLogger("api")

WEBAPP_DIR = Path(__file__).resolve().parent.parent / "webapp"
MAX_UPLOAD = 10 * 1024 * 1024
# Для библиотеки лимит больше (учебники). Читать в приложении можно любой размер (streaming);
# скачивание через бота работает только до 50 МБ (ограничение Telegram Bot API).
MAX_LIBRARY_UPLOAD = 100 * 1024 * 1024
BOT_SEND_LIMIT = 50 * 1024 * 1024


class BotRef:
    """Сюда main.py кладёт объект бота, чтобы API мог отправлять файлы в Telegram."""

    bot = None


bot_ref = BotRef()


async def get_db() -> AsyncIterator[AsyncSession]:
    async with dbmod.SessionLocal() as session:
        yield session


def _telegram_user(x_init_data: str | None, x_dev_user: str | None) -> dict:
    if settings.dev_auth and x_dev_user and not x_init_data:
        return {"id": int(x_dev_user), "username": f"dev{x_dev_user}"}
    try:
        return validate_init_data(x_init_data or "", settings.bot_token)
    except AuthError as e:
        raise HTTPException(401, f"Откройте приложение через Telegram ({e}).")


async def current_user_id(
    x_init_data: str | None = Header(default=None, alias="X-Init-Data"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
) -> int:
    """Быстрая проверка без обращения к базе — для частых запросов студента во время теста."""
    return int(_telegram_user(x_init_data, x_dev_user)["id"])


async def current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_init_data: str | None = Header(default=None, alias="X-Init-Data"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_act_as: str | None = Header(default=None, alias="X-Act-As"),
) -> User:
    """Текущий пользователь. Админ может работать в кабинете преподавателя (заголовок X-Act-As)."""
    tg = _telegram_user(x_init_data, x_dev_user)
    user = await svc.get_or_create_user(db, int(tg["id"]), tg.get("username"))
    request.state.real_user_id = user.id
    request.state.acting = False
    if x_act_as:
        if user.id not in settings.admin_ids:
            raise HTTPException(403, "Только для админа.")
        target = await db.get(User, int(x_act_as))
        if target is None:
            raise HTTPException(404, "Преподаватель не найден.")
        request.state.acting = True
        if request.method != "GET":
            svc.add_admin_log(db, user.id, target.id, svc.describe_action(request.method, request.url.path))
            await db.commit()
        return target  # блокировка не мешает админу помогать
    if user.blocked:
        raise HTTPException(403, "Доступ заблокирован.")
    return user


async def admin_user(
    db: AsyncSession = Depends(get_db),
    x_init_data: str | None = Header(default=None, alias="X-Init-Data"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
) -> User:
    tg = _telegram_user(x_init_data, x_dev_user)
    if int(tg["id"]) not in settings.admin_ids:
        raise HTTPException(403, "Только для админа.")
    return await svc.get_or_create_user(db, int(tg["id"]), tg.get("username"))


async def notify(user_id: int, text: str):
    if bot_ref.bot is None:
        return
    try:
        await bot_ref.bot.send_message(user_id, text)
    except Exception:
        pass


async def _run_broadcast(ids: list[int], text: str, admin_id: int):
    """Фоновая рассылка: шлём каждому в личку с паузами, чтобы не упереться в лимиты Telegram.
    По завершении отправляем админу краткий отчёт."""
    import asyncio

    if bot_ref.bot is None:
        return
    sent = failed = 0
    for i, uid in enumerate(ids):
        try:
            # Отправляем обычным текстом (parse_mode=None), чтобы случайные < или & не ломали сообщение.
            await bot_ref.bot.send_message(uid, text, parse_mode=None)
            sent += 1
        except Exception:
            failed += 1
        if i % 20 == 19:
            await asyncio.sleep(1)
    try:
        report = f"📢 Рассылка завершена: доставлено {sent} из {len(ids)}."
        if failed:
            report += f" Не доставлено: {failed} (не нажимали /start или заблокировали бота)."
        await bot_ref.bot.send_message(admin_id, report)
    except Exception:
        pass


# ---------------------------------------------------------------- схемы запросов

class NameIn(BaseModel):
    full_name: str


class RoleIn(BaseModel):
    role: str


class LangIn(BaseModel):
    lang: str


class TeacherRequestIn(BaseModel):
    info: str = ""
    kafedra: str = ""


class WorkplaceIn(BaseModel):
    info: str
    kafedra: str = ""


class SoloIn(BaseModel):
    test_id: int
    question_count: int = 0
    duration_min: int = Field(30, ge=1, le=240)


class SubjectIn(BaseModel):
    name: str


class QuestionIn(BaseModel):
    text: str
    options: list[str]
    correct: int


class ArchiveIn(BaseModel):
    archived: bool


class TitleIn(BaseModel):
    title: str


class SessionIn(BaseModel):
    test_id: int
    group_name: str
    duration_min: int = Field(30, ge=1, le=240)
    question_count: int = 0
    max_leaves: int = 3
    max_students: int = 0
    show_answers: bool = False
    join_window_min: int = Field(3, ge=0, le=60)  # код действует N минут после старта (0 — весь тест)


class KickIn(BaseModel):
    attempt_id: int


class JoinIn(BaseModel):
    code: str


class AnswerIn(BaseModel):
    question_id: int
    option_index: int


class LeaveIn(BaseModel):
    seconds: int = 0


class DecideIn(BaseModel):
    approve: bool


class ProIn(BaseModel):
    days: int = Field(30, ge=1, le=3650)


class ChatIn(BaseModel):
    messages: list[dict] = []
    lang: str = "ru"


class BlockIn(BaseModel):
    blocked: bool


class SettingsIn(BaseModel):
    price_presentation: int | None = Field(None, ge=0, le=100_000_000)
    price_test: int | None = Field(None, ge=0, le=100_000_000)
    card_number: str | None = None
    card_holder: str | None = None
    topup_amounts: str | None = None
    welcome_bonus: int | None = Field(None, ge=0, le=100_000_000)


class TopupDecideIn(BaseModel):
    approve: bool


class BroadcastIn(BaseModel):
    audience: str  # teachers | students | all
    text: str


class GrantIn(BaseModel):
    audience: str  # teachers | students | all
    amount: int = Field(ge=1, le=100_000_000)
    notify: bool = False


class LibrarySubjectIn(BaseModel):
    name: str


class LibraryDecideIn(BaseModel):
    approve: bool


class ProgressIn(BaseModel):
    page: int = Field(1, ge=1, le=100_000)


# ---------------------------------------------------------------- приложение

def create_app() -> FastAPI:
    app = FastAPI(title="TestRoom", docs_url=None, redoc_url=None)

    @app.exception_handler(svc.ServiceError)
    async def _service_error(_: Request, exc: svc.ServiceError):
        return JSONResponse({"detail": exc.message}, status_code=exc.status)

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.get("/api/universities")
    async def universities():
        return UNIVERSITIES

    # ------------------------------------------------ общее
    @app.get("/api/me")
    async def me(request: Request, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
        acting = request.state.acting
        data = {
            "id": user.id,
            "full_name": user.full_name,
            "role": user.role,
            "teacher_pending": user.teacher_pending,
            "teacher_info": user.teacher_info,
            "teacher_kafedra": user.teacher_kafedra,
            "is_teacher": user.is_teacher or (acting and user.role == "teacher"),
            "is_admin": request.state.real_user_id in settings.admin_ids,
            "acting_as": {"id": user.id, "name": user.full_name, "blocked": user.blocked} if acting else None,
            "plan": "proplus" if user.is_pro_plus else ("pro" if user.is_pro else "free"),
            "pro_until": user.pro_until.isoformat() if user.is_pro else None,
            "is_pro_plus": user.is_pro_plus,
            "proplus_until": user.proplus_until.isoformat() if user.is_pro_plus else None,
            "lang": getattr(user, "lang", None) or "ru",
        }
        cfg = await svc.get_settings(db)
        data["balance"] = user.balance or 0
        data["pays"] = not svc.is_free_user(user)  # платит ли этот пользователь за генерацию
        data["prices"] = {
            "presentation": svc._price(cfg, "presentation"),
            "test": svc._price(cfg, "test"),
        }
        if user.is_teacher:
            data["active_session"] = await svc.active_session(db, user)
        return data

    @app.post("/api/me/name")
    async def set_name(body: NameIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
        await svc.set_full_name(db, user, body.full_name)
        return {"full_name": user.full_name}

    @app.post("/api/me/role")
    async def set_role(body: RoleIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
        await svc.set_role(db, user, body.role)
        return {"role": user.role, "is_teacher": user.is_teacher}

    @app.post("/api/me/lang")
    async def set_lang(body: LangIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
        """Единый язык бота и приложения: переключатель в Mini App сохраняет его в БД."""
        lang = body.lang if body.lang in ("uz", "ru", "en") else "ru"
        await svc.set_user_lang(db, user.id, lang)
        return {"lang": lang}

    @app.post("/api/me/workplace")
    async def set_workplace(
        body: WorkplaceIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
    ):
        await svc.set_teacher_info(db, user, body.info, body.kafedra)
        return {"teacher_info": user.teacher_info, "teacher_kafedra": user.teacher_kafedra}

    @app.post("/api/me/teacher-request")
    async def teacher_request(
        body: TeacherRequestIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
    ):
        await svc.request_teacher(db, user, body.info, body.kafedra)
        if user.teacher_pending:  # обычный пользователь — уведомить админов о заявке
            for admin in settings.admin_ids:
                await notify(admin, f"🆕 Заявка преподавателя: {user.full_name} (ID {user.id}). Откройте админ-панель.")
        return {"role": user.role, "pending": user.teacher_pending}

    # ------------------------------------------------ учитель: тесты
    @app.get("/api/teacher/subjects")
    async def subjects(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
        return await svc.list_subjects(db, user)

    @app.post("/api/teacher/subjects")
    async def add_subject(body: SubjectIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
        s = await svc.create_subject(db, user, body.name)
        return {"id": s.id, "name": s.name}

    @app.delete("/api/teacher/subjects/{subject_id}")
    async def delete_subject(subject_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
        await svc.delete_subject(db, user, subject_id)
        return {"ok": True}

    @app.post("/api/teacher/tests/upload")
    async def upload_test(
        file: UploadFile = File(...),
        subject_id: int = Form(...),
        title: str = Form(...),
        save_valid: bool = Form(False),
        user: User = Depends(current_user),
        db: AsyncSession = Depends(get_db),
    ):
        svc.require_teacher(user)
        data = await file.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            raise svc.ServiceError("Файл больше 10 МБ.")
        try:
            # разбор файла — CPU-bound; уводим в поток, чтобы не подвешивать event loop
            parsed = await asyncio.to_thread(parse_file, file.filename or "", data)
        except ParseFailed as e:
            raise svc.ServiceError(str(e))
        report = {
            "found": parsed.total_found,
            "valid": len(parsed.questions),
            "errors": [{"number": e.number, "preview": e.preview, "message": e.message} for e in parsed.errors],
        }
        if parsed.errors and not save_valid:
            return {"saved": False, **report}
        test = await svc.create_test(db, user, subject_id, title, parsed.questions)
        return {"saved": True, "test_id": test.id, **report}

    @app.get("/api/teacher/tests/{test_id}")
    async def get_test(test_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
        return await svc.get_test(db, user, test_id)

    @app.post("/api/teacher/tests/{test_id}/questions")
    async def add_question(
        test_id: int, body: QuestionIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
    ):
        q = await svc.add_question(db, user, test_id, body.text, body.options, body.correct)
        return {"id": q.id}

    @app.put("/api/teacher/questions/{question_id}")
    async def edit_question(
        question_id: int, body: QuestionIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
    ):
        q = await svc.update_question(db, user, question_id, body.text, body.options, body.correct)
        return {"id": q.id}

    @app.delete("/api/teacher/questions/{question_id}")
    async def del_question(question_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
        await svc.delete_question(db, user, question_id)
        return {"ok": True}

    @app.post("/api/teacher/tests/{test_id}/archive")
    async def archive(test_id: int, body: ArchiveIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
        t = await svc.set_archived(db, user, test_id, body.archived)
        return {"id": t.id, "archived": t.archived}

    @app.patch("/api/teacher/tests/{test_id}")
    async def rename_test(
        test_id: int, body: TitleIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
    ):
        t = await svc.rename_test(db, user, test_id, body.title)
        return {"id": t.id, "title": t.title}

    @app.delete("/api/teacher/tests/{test_id}")
    async def delete_test(test_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
        await svc.delete_test(db, user, test_id)
        return {"ok": True}

    # ------------------------------------------------ учитель: запуски
    @app.post("/api/teacher/sessions")
    async def start(body: SessionIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
        s = await svc.start_session(
            db,
            user,
            body.test_id,
            body.group_name,
            body.duration_min,
            body.question_count,
            body.max_leaves,
            body.max_students,
            body.show_answers,
            body.join_window_min,
        )
        return {"id": s.id, "code": s.code}

    @app.get("/api/teacher/sessions")
    async def history(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
        return await svc.teacher_sessions(db, user)

    @app.get("/api/teacher/sessions/{session_id}/live")
    async def live(session_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
        return await svc.session_live(db, user, session_id)

    @app.get("/api/teacher/sessions/{session_id}/results")
    async def results(session_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
        return await svc.session_results(db, user, session_id)

    @app.post("/api/teacher/sessions/{session_id}/finish")
    async def finish(session_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
        await svc.finish_session_by_teacher(db, user, session_id)
        return {"ok": True}

    @app.post("/api/teacher/sessions/{session_id}/kick")
    async def kick(session_id: int, body: KickIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
        await svc.kick_student(db, user, session_id, body.attempt_id)
        return {"ok": True}

    @app.post("/api/teacher/sessions/{session_id}/export")
    async def export(
        session_id: int, request: Request, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
    ):
        """Отправляет Excel-файл учителю в чат с ботом (скачивание внутри Mini App ненадёжно)."""
        name, data = await svc.export_xlsx(db, user, session_id)
        if bot_ref.bot is None:
            raise svc.ServiceError("Бот не запущен, отправить файл не получилось.", 503)
        await db.rollback()  # отпустить соединение с базой, пока файл уходит в Telegram
        from aiogram.types import BufferedInputFile

        # админ в чужом кабинете получает файл себе, а не преподавателю
        await bot_ref.bot.send_document(
            request.state.real_user_id, BufferedInputFile(data, filename=name), caption="Результаты теста"
        )
        return {"ok": True}

    @app.post("/api/teacher/tests/{test_id}/download")
    async def download_test(
        test_id: int, request: Request, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
    ):
        """Присылает тест (.docx с ответами) в чат с ботом тому, кто запросил.
        Админ в кабинете преподавателя получает файл СЕБЕ; преподаватель не уведомляется."""
        t = await svc.get_test(db, user, test_id)  # проверяет доступ (владение / режим админа)
        from .present import build_test_docx

        name, data = build_test_docx(t["title"], t["questions"])
        if bot_ref.bot is None:
            raise svc.ServiceError("Бот не запущен, отправить файл не получилось.", 503)
        await db.rollback()
        from aiogram.types import BufferedInputFile

        await bot_ref.bot.send_document(
            request.state.real_user_id,
            BufferedInputFile(data, filename=name),
            caption=f"📄 Тест: {t['title']}",
        )
        return {"ok": True}

    @app.get("/api/teacher/sessions/{session_id}/export.xlsx")
    async def export_file(session_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
        name, data = await svc.export_xlsx(db, user, session_id)
        return Response(
            data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    # ------------------------------------------------ студент
    @app.post("/api/student/join")
    async def join(body: JoinIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
        a = await svc.join_by_code(db, user, body.code)
        return await svc.attempt_state(db, user, a.id)

    @app.post("/api/student/solo")
    async def solo(body: SoloIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
        """Тренировка: решить свой тест в одиночку, без кода для группы."""
        a = await svc.start_solo_session(db, user, body.test_id, body.question_count, body.duration_min)
        return await svc.attempt_state(db, user, a.id)

    @app.get("/api/student/attempts/{attempt_id}")
    async def state(attempt_id: int, uid: int = Depends(current_user_id), db: AsyncSession = Depends(get_db)):
        return await svc.attempt_state(db, uid, attempt_id)

    @app.post("/api/student/attempts/{attempt_id}/answer")
    async def answer(
        attempt_id: int, body: AnswerIn, uid: int = Depends(current_user_id), db: AsyncSession = Depends(get_db)
    ):
        return await svc.submit_answer(db, uid, attempt_id, body.question_id, body.option_index)

    @app.post("/api/student/attempts/{attempt_id}/leave")
    async def leave(attempt_id: int, body: LeaveIn, uid: int = Depends(current_user_id), db: AsyncSession = Depends(get_db)):
        return await svc.report_leave(db, uid, attempt_id, body.seconds)

    @app.post("/api/student/attempts/{attempt_id}/share")
    async def share_result(
        attempt_id: int, request: Request, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
    ):
        """Рисует карточку результата и отправляет её в чат студента с ботом (для репоста)."""
        try:
            png = await svc.result_card_png(db, user, attempt_id)
        except svc.ServiceError:
            raise
        except Exception as e:  # ошибка рисования — не роняем 500, сообщаем понятно
            log.exception("Не удалось нарисовать карточку результата")
            raise svc.ServiceError(f"Не удалось нарисовать карточку: {type(e).__name__}", 500)

        if bot_ref.bot is None:
            raise svc.ServiceError("Бот не запущен — карточку отправить не получилось.", 503)
        from aiogram.types import BufferedInputFile

        lang = getattr(user, "lang", None) or "ru"
        link = f"https://t.me/{settings.bot_username}" if settings.bot_username else ""
        cap = {
            "ru": "🎉 Твой результат! Поделись и позови друзей:",
            "uz": "🎉 Natijang! Ulashib, do'stlaringni chaqir:",
            "en": "🎉 Your result! Share it and invite friends:",
        }.get(lang, "🎉 Твой результат!")
        caption = f"{cap}\n{link}".strip()
        chat_id = request.state.real_user_id
        # Отправляем фото без HTML-разметки (подпись — обычный текст). Если send_photo
        # почему-то не прошёл — пробуем документом (проверенный путь), чтобы карточка дошла.
        try:
            await bot_ref.bot.send_photo(
                chat_id, BufferedInputFile(png, filename="result.jpg"),
                caption=caption, parse_mode=None,
            )
        except Exception as e:
            log.exception("send_photo карточки не прошёл, пробую send_document")
            try:
                await bot_ref.bot.send_document(
                    chat_id, BufferedInputFile(png, filename="result.jpg"),
                    caption=caption, parse_mode=None,
                )
            except Exception as e2:
                log.exception("send_document карточки тоже не прошёл")
                raise svc.ServiceError(
                    f"Не удалось отправить карточку: {type(e).__name__}: {str(e)[:150]}", 502
                )
        return {"ok": True}

    @app.get("/api/student/history")
    async def my_history(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
        return await svc.student_history(db, user)

    # ------------------------------------------------ библиотека (чтение — все, загрузка — препод)
    @app.get("/api/library/subjects")
    async def library_subjects(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
        return await svc.list_library_subjects(db, with_counts=True)

    @app.get("/api/library/docs")
    async def library_docs(
        subject_id: int | None = None, q: str = "", user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
    ):
        return await svc.list_library_docs(db, subject_id, q, status="approved")

    @app.get("/api/library/docs/{doc_id}")
    async def library_doc(doc_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
        return await svc.get_library_doc(db, doc_id)

    @app.get("/api/library/docs/{doc_id}/file")
    async def library_file(doc_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
        """Отдаёт файл материала с поддержкой Range (streaming — PDF грузится постранично)."""
        import mimetypes

        path, name = await svc.library_doc_path(db, doc_id)
        # КРИТИЧНО: отпускаем единственное соединение SQLite ДО отдачи файла. Иначе медленная
        # загрузка книги (особенно с телефона) держит соединение весь download и подвешивает
        # и бота, и приложение для всех остальных.
        await db.close()
        media = mimetypes.guess_type(name)[0] or "application/octet-stream"
        # FileResponse сам поддерживает HTTP Range → PDF.js тянет только нужные страницы.
        return FileResponse(path, media_type=media, headers={"Cache-Control": "private, max-age=600"})

    @app.post("/api/ai/chat")
    async def ai_chat_ep(
        body: ChatIn, request: Request, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
    ):
        """ИИ-чат «спроси базу» + действия (презентация/тест/документ в бот). Только Pro+."""
        target_id = request.state.real_user_id

        async def send_file(filename: str, data: bytes, caption: str):
            if bot_ref.bot is None:
                raise svc.ServiceError("Бот не запущен — файл отправить не получилось.", 503)
            from aiogram.types import BufferedInputFile

            await bot_ref.bot.send_document(
                target_id, BufferedInputFile(data, filename=filename), caption=caption
            )

        return await svc.ai_chat(db, user, body.messages or [], body.lang or "ru", send_file=send_file)

    @app.get("/api/library/docs/{doc_id}/cover")
    async def library_cover(doc_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
        """Обложка книги (1-я страница PDF)."""
        path = await svc.library_cover_path(db, doc_id)
        await db.close()  # отпускаем соединение до отдачи файла
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})

    @app.get("/api/library/docs/{doc_id}/progress")
    async def library_progress_get(
        doc_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
    ):
        return {"page": await svc.get_library_progress(db, user.id, doc_id)}

    @app.post("/api/library/docs/{doc_id}/progress")
    async def library_progress_set(
        doc_id: int, body: ProgressIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
    ):
        return {"page": await svc.set_library_progress(db, user.id, doc_id, body.page)}

    @app.get("/api/library/docs/{doc_id}/search")
    async def library_search(
        doc_id: int, q: str = "", user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
    ):
        return await svc.library_doc_search(db, doc_id, q)

    @app.post("/api/library/docs/{doc_id}/download")
    async def library_download(
        doc_id: int, request: Request, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
    ):
        """Отправляет оригинальный файл материала в чат с ботом тому, кто запросил."""
        name, data = await svc.library_doc_file(db, doc_id)
        if bot_ref.bot is None:
            raise svc.ServiceError("Бот не запущен, отправить файл не получилось.", 503)
        await db.rollback()
        from aiogram.types import BufferedInputFile

        await bot_ref.bot.send_document(
            request.state.real_user_id, BufferedInputFile(data, filename=name), caption=f"📚 {name}"
        )
        return {"ok": True}

    @app.post("/api/library/docs")
    async def library_upload(
        file: UploadFile = File(...),
        subject_id: int = Form(...),
        title: str = Form(...),
        user: User = Depends(current_user),
        db: AsyncSession = Depends(get_db),
    ):
        import os
        import tempfile

        svc.require_teacher(user)
        os.makedirs(settings.library_dir, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=settings.library_dir)
        size = 0
        try:
            with os.fdopen(fd, "wb") as out:  # стримим на диск, не держим файл в памяти (1 ГБ RAM)
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_LIBRARY_UPLOAD:
                        raise svc.ServiceError("Файл больше 100 МБ. Сожмите или разделите на части.")
                    out.write(chunk)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        doc = await svc.add_library_doc_from_path(
            db, user, subject_id, title, file.filename or "", file.content_type, tmp, size
        )
        for admin in settings.admin_ids:  # уведомить админов о новом материале на модерацию
            await notify(admin, f"📚 Новый материал в библиотеку: «{doc.title}» от {user.full_name}. Нужна модерация.")
        return {"id": doc.id, "status": doc.status}

    # ------------------------------------------------ админ
    @app.get("/api/admin/stats")
    async def a_stats(admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
        return await svc.admin_stats(db)

    @app.get("/api/admin/stats/daily")
    async def a_stats_daily(
        metric: str, days: int = 30, admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)
    ):
        return await svc.admin_daily_stats(db, metric, days)

    @app.get("/api/admin/teachers")
    async def a_teachers(
        q: str = "", status: str = "all", admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)
    ):
        return await svc.admin_teachers(db, q.strip(), status)

    @app.post("/api/admin/teachers/{uid}/decide")
    async def a_decide(uid: int, body: DecideIn, admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
        u = await svc.decide_teacher(db, uid, body.approve)
        svc.add_admin_log(db, admin.id, uid, "одобрил заявку" if body.approve else "отклонил заявку")
        await db.commit()
        await notify(
            uid,
            "🎉 Вы подтверждены как преподаватель! Откройте приложение, чтобы запустить тест."
            if body.approve
            else "К сожалению, заявка преподавателя отклонена.",
        )
        if body.approve and bot_ref.bot is not None:  # обновить кнопки снизу без повторного /start
            try:
                from .bot import main_reply_kb

                await bot_ref.bot.send_message(
                    uid,
                    "⬇️ Снизу закреплены кнопки: «📝 Создать тест» и «🖥 Создать презентацию».",
                    reply_markup=main_reply_kb(u),
                )
            except Exception:
                pass
        return {"role": u.role, "pending": u.teacher_pending}

    @app.post("/api/admin/teachers/{uid}/remove")
    async def a_remove(uid: int, admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
        await svc.remove_teacher(db, uid)
        svc.add_admin_log(db, admin.id, uid, "снял роль преподавателя")
        await db.commit()
        await notify(
            uid,
            "Администратор снял роль преподавателя — вы снова обычный пользователь. "
            "Ваши тесты и история сохранены. При желании можно снова подать заявку на преподавателя.",
        )
        return {"ok": True}

    @app.post("/api/admin/teachers/{uid}/pro")
    async def a_pro(uid: int, body: ProIn, admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
        u = await svc.give_pro(db, uid, body.days)
        svc.add_admin_log(db, admin.id, uid, f"выдал Pro на {body.days} дн.")
        await db.commit()
        await notify(uid, f"⭐ Подписка Pro активна до {u.pro_until:%d.%m.%Y}. Спасибо!")
        return {"pro_until": u.pro_until.isoformat()}

    @app.post("/api/admin/teachers/{uid}/unpro")
    async def a_unpro(uid: int, admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
        await svc.remove_pro(db, uid)
        svc.add_admin_log(db, admin.id, uid, "снял Pro")
        await db.commit()
        await notify(uid, "Подписка Pro снята. Вы на бесплатном тарифе.")
        return {"ok": True}

    @app.post("/api/admin/teachers/{uid}/proplus")
    async def a_proplus(uid: int, body: ProIn, admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
        u = await svc.give_pro_plus(db, uid, body.days)
        svc.add_admin_log(db, admin.id, uid, f"выдал Pro+ на {body.days} дн.")
        await db.commit()
        await notify(uid, f"💎 Pro+ активен до {u.proplus_until:%d.%m.%Y}. Открыты все возможности!")
        return {"proplus_until": u.proplus_until.isoformat()}

    @app.post("/api/admin/teachers/{uid}/unproplus")
    async def a_unproplus(uid: int, admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
        await svc.remove_pro_plus(db, uid)
        svc.add_admin_log(db, admin.id, uid, "снял Pro+")
        await db.commit()
        await notify(uid, "Подписка Pro+ снята.")
        return {"ok": True}

    @app.post("/api/admin/teachers/{uid}/block")
    async def a_block(uid: int, body: BlockIn, admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
        await svc.set_blocked(db, uid, body.blocked)
        svc.add_admin_log(db, admin.id, uid, "заблокировал" if body.blocked else "разблокировал")
        await db.commit()
        return {"blocked": body.blocked}

    @app.post("/api/admin/teachers/{uid}/enter")
    async def a_enter(uid: int, admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
        target = await db.get(User, uid)
        if target is None or target.role != "teacher":
            raise svc.ServiceError("Войти можно только в кабинет преподавателя.", 404)
        svc.add_admin_log(db, admin.id, uid, "вошёл в кабинет")
        await db.commit()
        return {"id": target.id, "name": target.full_name}

    @app.get("/api/admin/log")
    async def a_log(admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
        return await svc.admin_log(db)

    # ------------------------------------------------ админ: оплата (цены, карта, пополнения)
    @app.get("/api/admin/settings")
    async def a_get_settings(admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
        return await svc.get_settings(db)

    @app.post("/api/admin/settings")
    async def a_set_settings(body: SettingsIn, admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
        values = {k: v for k, v in body.model_dump().items() if v is not None}
        cfg = await svc.set_settings(db, values)
        svc.add_admin_log(db, admin.id, None, "изменил настройки оплаты")
        await db.commit()
        return cfg

    @app.post("/api/admin/grant")
    async def a_grant(body: GrantIn, admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
        import asyncio

        if body.audience not in ("teachers", "students", "all"):
            raise svc.ServiceError("Неизвестная аудитория.")
        ids = await svc.grant_balance(db, body.audience, body.amount)
        svc.add_admin_log(db, admin.id, None, f"начислил {body.amount} сум на баланс ({body.audience}, {len(ids)} чел.)")
        await db.commit()
        if body.notify and ids and bot_ref.bot is not None:
            msg = (
                f"🎁 Вам начислено {body.amount} сум на баланс! "
                "Теперь можно создавать презентации и тесты. Баланс — кнопка «💰 Мой баланс»."
            )
            asyncio.create_task(_run_broadcast(ids, msg, admin.id))
        return {"granted": len(ids), "amount": body.amount}

    @app.post("/api/admin/broadcast")
    async def a_broadcast(body: BroadcastIn, admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
        import asyncio

        text = (body.text or "").strip()
        if not text:
            raise svc.ServiceError("Введите текст сообщения.")
        if len(text) > 4000:
            raise svc.ServiceError("Сообщение слишком длинное (максимум 4000 символов).")
        if body.audience not in ("teachers", "students", "all"):
            raise svc.ServiceError("Неизвестная аудитория.")
        if bot_ref.bot is None:
            raise svc.ServiceError("Бот не запущен, рассылка невозможна.", 503)
        ids = await svc.users_by_audience(db, body.audience)
        svc.add_admin_log(db, admin.id, None, f"рассылка ({body.audience}, {len(ids)} чел.)")
        await db.commit()
        # Отправляем в фоне, чтобы не держать HTTP-запрос и соединение с базой открытыми.
        asyncio.create_task(_run_broadcast(ids, text, admin.id))
        return {"queued": len(ids)}

    @app.get("/api/admin/topups")
    async def a_topups(status: str = "pending", admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
        return await svc.admin_topups(db, status)

    @app.post("/api/admin/topups/{topup_id}/decide")
    async def a_topup_decide(
        topup_id: int, body: TopupDecideIn, admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)
    ):
        t, u = await svc.decide_topup(db, topup_id, body.approve, admin.id)
        svc.add_admin_log(db, admin.id, t.user_id, f"{'зачислил' if body.approve else 'отклонил'} пополнение {t.amount} сум")
        await db.commit()
        if body.approve:
            await notify(t.user_id, f"✅ Баланс пополнен на {t.amount} сум. Текущий баланс: {(u.balance if u else 0)} сум.")
        else:
            await notify(t.user_id, "❌ Пополнение отклонено. Если вы оплатили — свяжитесь с администратором.")
        return {"ok": True, "status": t.status, "balance": u.balance if u else 0}

    # ------------------------------------------------ админ: библиотека
    @app.get("/api/admin/library/pending")
    async def a_lib_pending(admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
        return await svc.list_library_docs(db, status="pending")

    @app.get("/api/admin/library/docs/{doc_id}")
    async def a_lib_doc(doc_id: int, admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
        return await svc.get_library_doc(db, doc_id, allow_pending=True)

    @app.post("/api/admin/library/docs/{doc_id}/download")
    async def a_lib_download(
        doc_id: int, request: Request, admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)
    ):
        name, data = await svc.library_doc_file(db, doc_id, allow_pending=True)
        if bot_ref.bot is None:
            raise svc.ServiceError("Бот не запущен.", 503)
        await db.rollback()
        from aiogram.types import BufferedInputFile

        await bot_ref.bot.send_document(admin.id, BufferedInputFile(data, filename=name), caption=f"📚 {name}")
        return {"ok": True}

    @app.post("/api/admin/library/docs/{doc_id}/decide")
    async def a_lib_decide(
        doc_id: int, body: LibraryDecideIn, admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)
    ):
        d = await svc.decide_library_doc(db, doc_id, body.approve, admin.id)
        svc.add_admin_log(db, admin.id, d.uploaded_by, f"{'одобрил' if body.approve else 'отклонил'} материал «{d.title}»")
        await db.commit()
        await notify(
            d.uploaded_by,
            f"✅ Ваш материал «{d.title}» одобрен и добавлен в библиотеку. Спасибо!"
            if body.approve
            else f"❌ Материал «{d.title}» отклонён модератором.",
        )
        return {"ok": True, "status": d.status}

    @app.delete("/api/admin/library/docs/{doc_id}")
    async def a_lib_delete(doc_id: int, admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
        await svc.delete_library_doc(db, doc_id)
        svc.add_admin_log(db, admin.id, None, "удалил материал из библиотеки")
        await db.commit()
        return {"ok": True}

    @app.post("/api/admin/library/subjects")
    async def a_lib_subj_add(body: LibrarySubjectIn, admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
        s = await svc.add_library_subject(db, body.name)
        return {"id": s.id, "name": s.name}

    @app.patch("/api/admin/library/subjects/{subject_id}")
    async def a_lib_subj_rename(
        subject_id: int, body: LibrarySubjectIn, admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)
    ):
        s = await svc.rename_library_subject(db, subject_id, body.name)
        return {"id": s.id, "name": s.name}

    @app.delete("/api/admin/library/subjects/{subject_id}")
    async def a_lib_subj_delete(subject_id: int, admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
        await svc.delete_library_subject(db, subject_id)
        return {"ok": True}

    # ------------------------------------------------ сам Mini App
    @app.get("/")
    async def index():
        # Подставляем версию (mtime) к ссылкам на app.js/style.css, чтобы Telegram-webview
        # не держал старую закэшированную версию после обновлений.
        html = (WEBAPP_DIR / "index.html").read_text(encoding="utf-8")
        try:
            v = int(max((WEBAPP_DIR / "app.js").stat().st_mtime, (WEBAPP_DIR / "style.css").stat().st_mtime))
        except OSError:
            v = 0
        html = html.replace("/static/app.js", f"/static/app.js?v={v}").replace("/static/style.css", f"/static/style.css?v={v}")
        return Response(html, media_type="text/html", headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=WEBAPP_DIR), name="static")
    return app
