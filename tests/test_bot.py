"""Проверка бота без интернета: запросы к Telegram подменяются заглушкой."""
import datetime as dt
from typing import Any

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import GetFile, SendDocument, SendMessage
from aiogram.methods.base import TelegramMethod
from aiogram.types import CallbackQuery, Chat, Document, File, Message, Update
from aiogram.types import User as TgUser

from app import db as dbmod
from app import services as svc
from app.bot import create_bot, notify_finished
from app.models import User, utcnow
from app.parsers import template_docx

from .conftest import ADMIN_ID, TOKEN


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls: list[TelegramMethod] = []
        self.file_bytes = b""

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None) -> Any:
        self.calls.append(method)
        if isinstance(method, GetFile):
            return File(file_id=method.file_id, file_unique_id="u", file_path="documents/file")
        if isinstance(method, (SendMessage, SendDocument)) or type(method).__name__ == "EditMessageText":
            chat_id = getattr(method, "chat_id", 0) or 0
            return Message(message_id=1, date=dt.datetime.now(), chat=Chat(id=chat_id, type="private"), text="ok")
        return True

    async def stream_content(self, url, headers=None, timeout=30, chunk_size=65536, raise_for_status=True):
        yield self.file_bytes

    async def close(self):
        pass

    def texts(self, chat_id=None):
        return [
            m.text
            for m in self.calls
            if isinstance(m, SendMessage) and (chat_id is None or m.chat_id == chat_id)
        ]


@pytest.fixture
def bot_dp():
    bot, dp = create_bot()
    session = FakeSession()
    bot.session = session
    return bot, dp, session


_uid = iter(range(1, 10**6))


def msg(uid, text=None, document=None):
    return Update(
        update_id=next(_uid),
        message=Message(
            message_id=next(_uid),
            date=dt.datetime.now(),
            chat=Chat(id=uid, type="private"),
            from_user=TgUser(id=uid, is_bot=False, first_name="T"),
            text=text,
            document=document,
        ),
    )


def cb(uid, data, text="msg"):
    return Update(
        update_id=next(_uid),
        callback_query=CallbackQuery(
            id=str(next(_uid)),
            from_user=TgUser(id=uid, is_bot=False, first_name="T"),
            chat_instance="ci",
            data=data,
            message=Message(message_id=5, date=dt.datetime.now(), chat=Chat(id=uid, type="private"), text=text),
        ),
    )


async def get_user(uid) -> User:
    async with dbmod.SessionLocal() as db:
        return await db.get(User, uid)


async def test_registration_role_and_upload(bot_dp):
    bot, dp, s = bot_dp
    T = 555

    await dp.feed_update(bot, msg(T, "/start"))
    assert "Фамилию и Имя" in s.texts(T)[-1]
    await dp.feed_update(bot, msg(T, "a"))  # слишком коротко
    assert "ФИО" in s.texts(T)[-1]
    await dp.feed_update(bot, msg(T, "Рахимова Нигора"))
    assert (await get_user(T)).full_name == "Рахимова Нигора"

    # после регистрации бот спрашивает роль
    assert "Кто вы" in s.texts(T)[-1]
    await dp.feed_update(bot, cb(T, "role:student"))
    assert (await get_user(T)).role == "student"

    # студент тоже может загрузить свой тест для тренировки
    s.file_bytes = template_docx()
    doc = Document(file_id="f1", file_unique_id="u1", file_name="test.docx", file_size=1000)
    await dp.feed_update(bot, msg(T, document=doc))
    assert "Для какого предмета" in s.texts(T)[-1]
    await dp.feed_update(bot, cb(T, "up_new"))
    await dp.feed_update(bot, msg(T, "Анатомия"))
    await dp.feed_update(bot, msg(T, "Кости скелета"))
    assert "Сохранено (2 вопросов)" in s.texts(T)[-1]

    # заявка в преподаватели: выбор вуза из списка → уведомление админу
    await dp.feed_update(bot, cb(T, "apply"))
    assert "вуз" in s.texts(T)[-1].lower()  # показан список вузов
    await dp.feed_update(bot, cb(T, "uni:0"))
    await dp.feed_update(bot, msg(T, "Анатомия человека"))  # теперь спрашивается кафедра
    from app.universities import UNIVERSITIES

    assert (await get_user(T)).teacher_pending
    assert (await get_user(T)).teacher_info == UNIVERSITIES[0]  # вуз сохранён
    assert (await get_user(T)).teacher_kafedra == "Анатомия человека"
    assert any("Заявка преподавателя" in t for t in s.texts(ADMIN_ID))
    # не-админ не одобрит, админ одобрит — роль выдаётся только после одобрения
    await dp.feed_update(bot, cb(T, f"approve:{T}"))
    assert (await get_user(T)).teacher_pending and not (await get_user(T)).is_teacher
    await dp.feed_update(bot, cb(ADMIN_ID, f"approve:{T}"))
    assert (await get_user(T)).is_teacher
    assert any("подтверждены" in t for t in s.texts(T))

    # файл с ошибками → отчёт и сохранение только правильных
    s.file_bytes = b"1. A?\n+ a\n- b\n2. B?\n- a\n- b\n"
    doc2 = Document(file_id="f2", file_unique_id="u2", file_name="t.txt", file_size=100)
    await dp.feed_update(bot, msg(T, document=doc2))
    async with dbmod.SessionLocal() as db:
        subj_id = (await svc.list_subjects(db, await db.get(User, T)))[0]["id"]
    await dp.feed_update(bot, cb(T, f"up_subj:{subj_id}"))
    await dp.feed_update(bot, msg(T, "Второй тест"))
    assert "С ошибками: 1" in s.texts(T)[-1]
    await dp.feed_update(bot, cb(T, "up_save"))
    assert "Сохранено (1 вопросов)" in s.texts(T)[-1]

    # шаблоны
    await dp.feed_update(bot, msg(T, "/template"))
    assert sum(isinstance(m, SendDocument) for m in s.calls) == 2


async def test_university_search(bot_dp):
    bot, dp, s = bot_dp
    U = 606
    await dp.feed_update(bot, msg(U, "/start"))
    await dp.feed_update(bot, msg(U, "Иванов Иван"))
    await dp.feed_update(bot, cb(U, "role:student"))
    # заявка преподавателя → поиск вуза по части названия
    await dp.feed_update(bot, cb(U, "apply"))
    await dp.feed_update(bot, msg(U, "стомат"))
    assert any("Выберите ваш вуз" in t for t in s.texts(U))
    # ничего не найдено
    await dp.feed_update(bot, msg(U, "zzzzz"))
    assert any("Ничего не нашлось" in t for t in s.texts(U))
    # выбор найденного вуза подаёт заявку
    from app.universities import UNIVERSITIES

    idx = next(i for i, u in enumerate(UNIVERSITIES) if "стоматолог" in u.lower())
    await dp.feed_update(bot, cb(U, f"uni:{idx}"))
    await dp.feed_update(bot, msg(U, "Терапевтическая стоматология"))  # кафедра
    assert (await get_user(U)).teacher_pending
    assert (await get_user(U)).teacher_info == UNIVERSITIES[idx]
    assert (await get_user(U)).teacher_kafedra == "Терапевтическая стоматология"


async def test_edit_profile(bot_dp):
    bot, dp, s = bot_dp
    from app.universities import UNIVERSITIES

    T = 707
    await dp.feed_update(bot, msg(T, "/start"))
    await dp.feed_update(bot, msg(T, "Собиров Собир"))
    await dp.feed_update(bot, cb(T, "role:student"))
    # становится преподавателем (заявка с вузом + одобрение)
    await dp.feed_update(bot, cb(T, "apply"))
    await dp.feed_update(bot, cb(T, "uni:0"))
    await dp.feed_update(bot, msg(T, "Анатомия"))  # кафедра
    await dp.feed_update(bot, cb(ADMIN_ID, f"approve:{T}"))
    assert (await get_user(T)).is_teacher
    # сам меняет ФИО кнопкой
    await dp.feed_update(bot, cb(T, "editname"))
    await dp.feed_update(bot, msg(T, "Собиров Собиржон"))
    assert (await get_user(T)).full_name == "Собиров Собиржон"
    # сам меняет вуз кнопкой: поиск + выбор найденного
    idx = next(i for i, u in enumerate(UNIVERSITIES) if "стоматолог" in u.lower())
    await dp.feed_update(bot, cb(T, "editwork"))
    await dp.feed_update(bot, msg(T, "стомат"))
    assert any("Выберите ваш вуз" in t for t in s.texts(T))
    await dp.feed_update(bot, cb(T, f"uni:{idx}"))
    await dp.feed_update(bot, msg(T, "Ортопедическая стоматология"))  # кафедра
    assert (await get_user(T)).teacher_info == UNIVERSITIES[idx]
    assert (await get_user(T)).teacher_kafedra == "Ортопедическая стоматология"
    assert any("Обновлено" in t for t in s.texts(T))


async def test_admin_commands(bot_dp):
    bot, dp, s = bot_dp
    await dp.feed_update(bot, msg(ADMIN_ID, "/start"))
    await dp.feed_update(bot, msg(ADMIN_ID, "Админ Админов"))
    await dp.feed_update(bot, msg(ADMIN_ID, "/stats"))
    assert "Статистика" in s.texts(ADMIN_ID)[-1]
    await dp.feed_update(bot, msg(ADMIN_ID, "/give_pro 999 30"))
    assert "не найден" in s.texts(ADMIN_ID)[-1]
    await dp.feed_update(bot, msg(ADMIN_ID, f"/give_pro {ADMIN_ID} 30"))
    assert (await get_user(ADMIN_ID)).is_pro
    # обычный пользователь не видит админ-команды
    await dp.feed_update(bot, msg(777, "/stats"))
    assert not any("Статистика" in t for t in s.texts(777))


async def test_finish_notification(bot_dp):
    bot, dp, s = bot_dp
    async with dbmod.SessionLocal() as db:
        t = await svc.get_or_create_user(db, ADMIN_ID)
        await svc.set_full_name(db, t, "Учитель Тест")
        from app.parsers import ParsedQuestion

        subj = await svc.create_subject(db, t, "Химия")
        test = await svc.create_test(db, t, subj.id, "Кислоты", [ParsedQuestion("Q?", ["a", "b"], 0)])
        sess = await svc.start_session(db, t, test.id, "201", 10, 1)
        sess.ends_at = utcnow() - dt.timedelta(seconds=1)
        await db.commit()
        closed = await svc.close_expired_sessions(db)
    await notify_finished(bot, closed)
    assert any("Кислоты" in t and "завершён" in t for t in s.texts(ADMIN_ID))
    n = len(s.calls)
    await notify_finished(bot, closed)  # повторно не уведомляет
    assert len(s.calls) == n
