"""Telegram-бот: регистрация, заявки преподавателей, загрузка тестов, админ-команды."""
from __future__ import annotations

import asyncio
import logging
import re
from html import escape
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    KeyboardButton,
    MenuButtonWebApp,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from sqlalchemy import select

from . import db as dbmod
from . import services as svc
from .config import settings
from .models import Attempt, Test, TestSession, User
from .parsers import (
    TEMPLATE_TXT,
    ParsedQuestion,
    ParseFailed,
    extract_document_text,
    parse_file,
    template_docx,
    template_xlsx,
)
from .ai import generate_slides, generate_test_questions
from .present import PRESENT_EXAMPLE, build_presentation, build_pptx, build_test_docx
from .universities import UNIVERSITIES
from . import limits
from .bottexts import BTN_ALL, btn, t as L

log = logging.getLogger("bot")
router = Router()

# ---------------------------------------------------------------- авто-очистка чата
# Чтобы переписка не «засиралась»: в пошаговых сценариях служебные сообщения
# (вопросы бота, ответы пользователя, «⏳», меню выбора) запоминаются и удаляются
# в конце, оставляя в чате только готовый файл. Файлы не запоминаются — остаются.
_trail: dict[int, list[int]] = {}


def _remember(chat_id: int, *mids: int) -> None:
    lst = _trail.setdefault(chat_id, [])
    for m in mids:
        if m:
            lst.append(m)
    if len(lst) > 120:  # не растём бесконечно
        del lst[:-120]


async def _say(message: Message, text: str, **kw) -> Message:
    """Отправить служебное сообщение и запомнить его для последующей очистки."""
    sent = await message.answer(text, **kw)
    _remember(message.chat.id, sent.message_id)
    return sent


async def _sweep(bot, chat_id: int) -> None:
    """Удалить все запомненные служебные сообщения чата (готовые файлы остаются)."""
    for mid in _trail.pop(chat_id, []):
        try:
            await bot.delete_message(chat_id, mid)
        except Exception:
            pass  # сообщение старше 48ч/уже удалено — не страшно

ALLOWED_EXT = (".docx", ".xlsx", ".txt")

CREDIT = '\n\nСоздатель · <a href="https://instagram.com/aat.abdurazzakov">@aat.abdurazzakov</a>'


class Reg(StatesGroup):
    name = State()


class Apply(StatesGroup):
    info = State()
    search = State()
    kafedra = State()


class Upload(StatesGroup):
    subject_new = State()
    title = State()


class Present(StatesGroup):
    text = State()
    topic = State()
    lang = State()


class MakeTest(StatesGroup):
    topic = State()
    lang = State()  # выбор языка
    count = State()
    subject = State()  # выбор предмета из списка
    subject_new = State()  # ввод названия нового предмета


class MakePres(StatesGroup):
    topic = State()
    lang = State()  # выбор языка
    fio = State()
    group = State()
    count = State()


class Pay(StatesGroup):
    receipt = State()  # ждём скриншот чека после «Я оплатил»


BTN_PRES = "🖥 Создать презентацию"
BTN_TEST = "📝 Создать тест"
BTN_BALANCE = "💰 Мой баланс"
BTN_TOPUP = "💳 Пополнить баланс"


def _money(n: int) -> str:
    """Сумма в сумах с разделителями: 25000 → «25 000 сум»."""
    return f"{int(n or 0):,}".replace(",", " ") + " сум"


# Выбор языка генерации ИИ
LANG_NAMES = {"ru": "русский", "uz": "o'zbek", "en": "English"}


def lang_kb(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🇷🇺 Рус", callback_data=f"{prefix}:ru"),
        InlineKeyboardButton(text="🇺🇿 Ўзб", callback_data=f"{prefix}:uz"),
        InlineKeyboardButton(text="🇬🇧 Eng", callback_data=f"{prefix}:en"),
    ]])


def main_reply_kb(user: User) -> ReplyKeyboardMarkup:
    """Закреплённые кнопки снизу. Презентации и тесты доступны всем; студентам
    добавляем баланс и пополнение (они платят за генерацию, преподаватели — бесплатно)."""
    lang = getattr(user, "lang", None) or "ru"
    rows = [[KeyboardButton(text=btn("pres", lang)), KeyboardButton(text=btn("test", lang))]]
    if not user.is_teacher and user.id not in settings.admin_ids:
        rows.append([KeyboardButton(text=btn("balance", lang)), KeyboardButton(text=btn("topup", lang))])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)


PRESENT_PROMPT = (
    "🖥 <b>Создание презентации</b>\n\n"
    "Пришлите текст одним сообщением в таком формате:\n"
    "• первые строки — <b>заголовок</b> и подзаголовок презентации;\n"
    "• каждый слайд начинайте со строки с «<b>#</b>» (это заголовок слайда);\n"
    "• под слайдом — пункты (можно с «-»).\n\n"
    "Готовый файл .pptx можно открыть и править в PowerPoint или Google Slides.\n"
    "Посмотреть пример — /present_example"
)


def is_admin(uid: int) -> bool:
    return uid in settings.admin_ids


def _short_title(s: str, n: int = 70) -> str:
    """Короткое чистое название из темы: срезает мусор в начале и обрезает по словам."""
    s = " ".join((s or "").split())
    # срезаем мусор в начале (эмодзи, «6. Тема:», слово «Тест» и т.п.) — повторяется, поэтому цикл
    prev = None
    for _ in range(20):
        if s == prev:
            break
        prev = s
        s = re.sub(r"^[^0-9A-Za-zА-Яа-яЁё]+", "", s)  # ведущие эмодзи/символы/кавычки
        s = re.sub(r"^\d+[.)\]]\s*", "", s)  # «6. »
        s = re.sub(r"^(?:тест|тема|готово|сохранено|вопрос\w*)\b[\s:«»\-–—]*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"[\s«»\"'`]+$", "", s) or "Без названия"  # и хвостовой мусор
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0] or s[:n]
    return cut.rstrip(" .,;:—-") + "…"


def webapp_button(text: str = "📱 Открыть приложение") -> InlineKeyboardButton | None:
    if settings.webapp_url.startswith("https://"):
        return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=settings.webapp_url))
    return None


def menu_keyboard(user: User) -> InlineKeyboardMarkup:
    rows = []
    btn = webapp_button()
    if btn:
        rows.append([btn])
    rows.append([InlineKeyboardButton(text="📄 Шаблоны файлов", callback_data="templates")])
    if not is_admin(user.id):
        if user.is_teacher:
            rows.append([InlineKeyboardButton(text="🎓 Стать студентом", callback_data="role:student")])
        elif user.teacher_pending:
            rows.append([InlineKeyboardButton(text="⏳ Заявка на рассмотрении", callback_data="apply_status")])
        else:
            rows.append([InlineKeyboardButton(text="👨‍🏫 Стать преподавателем", callback_data="apply")])
    else:
        rows.append(
            [
                InlineKeyboardButton(text="📊 Статистика", callback_data="adm:stats"),
                InlineKeyboardButton(text="👥 Преподаватели", callback_data="adm:teachers"),
            ]
        )
    rows.append([InlineKeyboardButton(text="✏️ Изменить ФИО", callback_data="editname")])
    if user.is_teacher:
        rows.append([InlineKeyboardButton(text="🏫 Изменить вуз", callback_data="editwork")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def role_choice_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎓 Я студент", callback_data="role:student")],
            [InlineKeyboardButton(text="👨‍🏫 Я преподаватель", callback_data="apply")],
        ]
    )


ROLE_CHOICE_TEXT = (
    "Кто вы? Роль можно сменить в любой момент.\n\n"
    "🎓 <b>Студент</b> — проходит тесты по коду и может прорешать свой тест для тренировки.\n"
    "👨‍🏫 <b>Преподаватель</b> — создаёт тесты и проводит их для группы по коду."
)

# Инструкция по боту на узбекском (для преподавателей). Скриншоты — если положить
# картинки в папку guide/ рядом с проектом (01.jpg, 02.jpg …), бот пришлёт их альбомом.
GUIDE_DIR = Path(__file__).resolve().parent.parent / "guide"

QOLLANMA_UZ = (
    "📘 <b>STOMALUX TestRoom — o'qituvchilar uchun qo'llanma</b>\n\n"
    "<b>1. Ro'yxatdan o'tish</b>\n"
    "• /start bosing → Familiya va Ismingizni to'liq yozing.\n"
    "• Menyuda «👨‍🏫 O'qituvchi bo'lish» → universitetingizni tanlang.\n"
    "• Administrator arizani tasdiqlaydi — shundan so'ng test yarata olasiz.\n\n"
    "<b>2. Test yaratish</b>\n"
    "• <b>AI orqali</b>: pastdagi «📝 Создать тест» tugmasi → mavzuni yozing → savollar sonini kiriting. "
    "Bot tayyor testni Word faylida yuboradi va qaysi fanga saqlashni so'raydi.\n"
    "• <b>O'z faylingiz</b>: /template dan namuna oling, savollarni yozing va faylni botga yuboring.\n\n"
    "<b>3. Testni guruhga o'tkazish</b>\n"
    "• «📱 Ilovani ochish» → «Mening testlarim».\n"
    "• Fanni oching → testni tanlang → «▶️ Testni faollashtirish».\n"
    "• Guruh, vaqt, savollar sonini kiriting → ekranda <b>6 xonali KOD</b> chiqadi.\n"
    "• Shu kodni studentlarga ayting.\n\n"
    "<b>4. Studentlar qanday qo'shiladi</b>\n"
    "• Student botda /start → KODni kiritadi → testni boshlaydi.\n\n"
    "<b>5. Jonli kuzatish va natijalar</b>\n"
    "• Kim kirgani va kim ilovani tark etgani ko'rinadi.\n"
    "• Test tugagach — reyting, o'rtacha natija, qiyin savollar.\n"
    "• «📥 Excel» tugmasi natijalar jadvalini botga yuboradi.\n\n"
    "<b>6. Taqdimot yaratish</b>\n"
    "• «🖥 Создать презентацию» → mavzu, F.I.Sh., guruh, slaydlar soni (maks. 20).\n"
    "• Bot rasmli tayyor .pptx faylini yuboradi.\n\n"
    "<b>7. Mashq rejimi (o'rganish)</b>\n"
    "• Testni oching → «▶️ Yechish». Har savoldan keyin to'g'ri javob ko'rsatiladi.\n\n"
    "<b>Cheklovlar (bepul tarif)</b>\n"
    "• Kuniga 1 ta test faollashtirish va 1 ta taqdimot (vaqtincha).\n"
    "• Testlarni cheksiz yaratish mumkin.\n\n"
    "Savol bo'lsa — administratorga murojaat qiling."
)


async def send_qollanma(message: Message) -> None:
    """Шлёт узбекскую инструкцию (+ скриншоты из guide/, если они есть)."""
    try:
        imgs = sorted(p for p in GUIDE_DIR.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    except Exception:
        imgs = []
    if imgs:
        media = [InputMediaPhoto(media=FSInputFile(str(p))) for p in imgs[:10]]
        try:
            await message.answer_media_group(media)
        except Exception:
            pass
    await message.answer(QOLLANMA_UZ, disable_web_page_preview=True)


def menu_text(user: User) -> str:
    name = escape(user.full_name or "")
    if user.is_teacher:
        return (
            f"👨‍🏫 <b>{name}</b>, вы преподаватель.\n\n"
            "• Откройте приложение, чтобы запустить тест для группы по коду и смотреть результаты.\n"
            "• Чтобы добавить тест, просто отправьте сюда файл (.docx, .xlsx или .txt)."
        )
    return (
        f"🎓 <b>{name}</b>, вы студент.\n\n"
        "• Когда преподаватель назовёт код — откройте приложение и введите его.\n"
        "• Можно загрузить свой тест файлом и прорешать его для тренировки.\n"
        "• Хотите проводить тесты для группы — нажмите «Стать преподавателем»."
    )


async def send_menu(message: Message, user: User):
    await message.answer(menu_text(user) + CREDIT, reply_markup=menu_keyboard(user))
    lang = getattr(user, "lang", None) or "ru"
    if user.is_teacher or user.id in settings.admin_ids:
        hint = L("menu_hint_teacher", lang)
    else:
        hint = L("menu_hint_student", lang)
    await message.answer(hint, reply_markup=main_reply_kb(user))


# ---------------------------------------------------------------- регистрация

@router.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    async with dbmod.SessionLocal() as db:
        user = await svc.get_or_create_user(
            db, message.from_user.id, message.from_user.username,
            lang_code=message.from_user.language_code,
        )
    lang = getattr(user, "lang", None) or "ru"
    if user.blocked:
        return await message.answer(L("blocked", lang))
    if not user.full_name:
        await state.set_state(Reg.name)
        await state.update_data(first_time=True)
        return await message.answer(L("welcome_name", lang))
    await send_menu(message, user)


# ---------------------------------------------------------------- выбор языка интерфейса
def language_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🇺🇿 O'zbek", callback_data="setlang:uz"),
        InlineKeyboardButton(text="🇷🇺 Русский", callback_data="setlang:ru"),
        InlineKeyboardButton(text="🇬🇧 English", callback_data="setlang:en"),
    ]])


@router.message(Command("language", "til", "lang"))
async def change_language(message: Message):
    async with dbmod.SessionLocal() as db:
        user = await svc.get_or_create_user(db, message.from_user.id, message.from_user.username)
    lang = getattr(user, "lang", None) or "ru"
    await message.answer(L("choose_language", lang), reply_markup=language_kb())


@router.callback_query(F.data.startswith("setlang:"))
async def set_language(cb: CallbackQuery):
    lang = cb.data.split(":", 1)[1]
    if lang not in ("uz", "ru", "en"):
        return await cb.answer()
    async with dbmod.SessionLocal() as db:
        user = await svc.set_user_lang(db, cb.from_user.id, lang)
    await cb.answer("✅")
    try:
        await cb.message.edit_text(L("lang_set", lang))
    except Exception:
        pass
    # Пересобираем нижние кнопки на новом языке.
    await cb.message.answer(L("menu_hint_student", lang) if not (
        user.is_teacher or user.id in settings.admin_ids
    ) else L("menu_hint_teacher", lang), reply_markup=main_reply_kb(user))


# ---------------------------------------------------------------- ИИ: тест/презентация по теме
async def _ai_gate(message: Message, state: FSMContext) -> bool:
    async with dbmod.SessionLocal() as db:
        user = await svc.get_or_create_user(db, message.from_user.id, message.from_user.username)
    lang = getattr(user, "lang", None) or "ru"
    if user.blocked:
        await message.answer(L("blocked", lang))
        return False
    if not user.full_name:
        await message.answer(L("need_name", lang))
        return False
    if not settings.anthropic_api_key:
        await state.clear()
        await message.answer(L("ai_off", lang))
        return False
    return True


@router.message(F.text.in_(BTN_ALL["test"]))
async def make_test_start(message: Message, state: FSMContext):
    if not await _ai_gate(message, state):
        return
    async with dbmod.SessionLocal() as db:
        user = await svc.get_or_create_user(db, message.from_user.id, message.from_user.username)
        price = 0 if svc.is_free_user(user) else await svc.get_price(db, "test")
    _remember(message.chat.id, message.message_id)
    await state.set_state(MakeTest.topic)
    hint = f"\n\n💳 Стоимость: {_money(price)} (спишется с баланса при создании)." if price else ""
    await _say(
        message,
        "📝 Напишите <b>тему теста</b> (например: «Кариес» или «Кости черепа»).\n"
        "Или пришлите <b>файл</b> (PDF, Word, PowerPoint, TXT) либо вставьте <b>текст</b> — "
        "тогда составлю вопросы <b>строго по вашему материалу</b>." + hint,
    )


# Порог: длинный текст считаем прикреплённым материалом, а не темой.
MATERIAL_TEXT_MIN = 400
MATERIAL_EXT = (".pdf", ".docx", ".pptx", ".txt")


@router.message(MakeTest.topic, F.text)
async def make_test_topic(message: Message, state: FSMContext):
    _remember(message.chat.id, message.message_id)
    txt = (message.text or "").strip()
    if len(txt) >= MATERIAL_TEXT_MIN:
        # Пользователь вставил содержание темы — делаем тест строго по нему.
        await state.update_data(topic=_short_title(txt), material=txt, strict=True)
        note = "📄 Принял текст как материал — составлю строго по нему. "
    else:
        await state.update_data(topic=txt, material="", strict=False)
        note = ""
    await state.set_state(MakeTest.lang)
    await _say(message, note + "На каком <b>языке</b> составить тест?", reply_markup=lang_kb("tlang"))


@router.message(MakeTest.topic, F.document)
async def make_test_material_file(message: Message, state: FSMContext, bot: Bot):
    """В шаге выбора темы можно прислать файл (PDF/Word/PowerPoint/TXT) как материал для теста."""
    _remember(message.chat.id, message.message_id)
    name = message.document.file_name or ""
    if not name.lower().endswith(MATERIAL_EXT):
        return await _say(
            message,
            "Пришлите файл <b>.pdf</b>, <b>.docx</b>, <b>.pptx</b> или <b>.txt</b> — "
            "или напишите тему текстом.",
        )
    if (message.document.file_size or 0) > 10 * 1024 * 1024:
        return await _say(message, "Файл больше 10 МБ.")
    wait = await _say(message, "⏳ Читаю файл…")
    try:
        buf = await bot.download(message.document.file_id)
        text = await asyncio.to_thread(extract_document_text, name, buf.read())
    except ParseFailed as e:
        return await _say(message, "❌ " + escape(str(e)))
    except Exception:
        return await _say(message, "❌ Не удалось прочитать файл. Пришлите другой или напишите тему.")
    finally:
        try:
            await wait.delete()
        except Exception:
            pass
    text = (text or "").strip()
    if len(text) < 30:
        return await _say(
            message,
            "В файле не нашлось текста (возможно, это скан-картинки). "
            "Пришлите текстовый файл или напишите тему вручную.",
        )
    await state.update_data(topic=_short_title(name.rsplit(".", 1)[0]), material=text, strict=True)
    await state.set_state(MakeTest.lang)
    await _say(
        message,
        f"📄 Принял материал ({len(text)} символов) — составлю тест строго по нему. "
        "На каком <b>языке</b>?",
        reply_markup=lang_kb("tlang"),
    )


@router.callback_query(MakeTest.lang, F.data.regexp(r"^tlang:(ru|uz|en)$"))
async def make_test_lang(cb: CallbackQuery, state: FSMContext):
    await state.update_data(lang=cb.data.split(":")[1])
    await state.set_state(MakeTest.count)
    await _say(cb.message, "Сколько вопросов сделать? Напишите число (например 10, максимум 40).")
    await cb.answer()


@router.message(MakeTest.count, F.text)
async def make_test_count(message: Message, state: FSMContext):
    _remember(message.chat.id, message.message_id)
    digits = "".join(ch for ch in message.text if ch.isdigit())
    if not digits:
        return await _say(message, "Напишите число, например 10.")
    n = max(1, min(int(digits), 40))
    data = await state.get_data()
    topic, lang = data.get("topic", ""), data.get("lang", "ru")
    material = data.get("material", "")
    strict = bool(data.get("strict"))
    # Списываем стоимость заранее (для студентов). Преподаватели — бесплатно (charged=0).
    async with dbmod.SessionLocal() as db:
        user = await svc.get_or_create_user(db, message.from_user.id, message.from_user.username)
        is_teacher = user.is_teacher
        try:
            charged = await svc.charge_feature(db, user, "test")
        except svc.ServiceError as e:
            await state.clear()
            return await message.answer("❌ " + escape(e.message), reply_markup=topup_inline_kb())
    qn = " Много запросов — вы в очереди, подождите." if limits.queued() else ""
    src_note = " по вашему материалу" if material else ""
    label = f"«{escape(topic)}»" if topic else ""
    wait = await _say(message, f"⏳ Генерирую тест {label} на {n} вопросов{src_note}…" + qn)
    ctx = None
    try:
        async with limits.gen_slot():
            if material:
                # Материал прислал пользователь — RAG по библиотеке не нужен, берём строго его.
                async with limits.timing("text"):
                    questions = await generate_test_questions(
                        topic, n, lang=lang, context=material, strict=True
                    )
            else:
                async with dbmod.SessionLocal() as db, limits.timing("rag"):
                    ctx = await svc.library_context(db, topic)
                async with limits.timing("text"):
                    questions = await generate_test_questions(topic, n, lang=lang, context=ctx["context"])
    except svc.ServiceError as e:
        await _refund(message.from_user, charged)
        await state.clear()
        return await message.answer("❌ " + escape(e.message))
    if not questions:
        await _refund(message.from_user, charged)
        await state.clear()
        return await message.answer("❌ Не получилось собрать тест, попробуйте другую тему.")
    qs = [{"text": q.text, "options": q.options, "correct": q.correct} for q in questions]
    try:
        await wait.delete()
    except Exception:
        pass
    # 1) сразу отправляем тест в Word
    title = _short_title(topic)
    name, blob = build_test_docx(title, qs)
    note = "" if len(qs) >= n else f" (запрашивали {n}, собрано {len(qs)})"
    paid = f" Списано {_money(charged)}." if charged else ""
    src = ("\n📄 Строго по вашему материалу" if material else _rag_note(ctx, lang))
    await message.answer_document(
        BufferedInputFile(blob, name),
        caption=f"📄 Готово — {len(qs)} вопросов{note}.{paid} Проверьте файл.{src}",
    )
    if not is_teacher:
        # Студенту отдаём ТОЛЬКО файл — в приложении тест не сохраняется (запуск для группы — у преподавателей).
        await state.clear()
        await _sweep(message.bot, message.chat.id)
        return await message.answer(
            "Это ваш файл для учёбы 📚 В приложении тест не сохраняется — "
            "запускать тесты для группы могут только преподаватели."
        )
    # 2) преподаватель: спрашиваем предмет из списка и сохраняем в приложение
    await state.update_data(questions=qs, title=title)
    await state.set_state(MakeTest.subject)
    async with dbmod.SessionLocal() as db:
        user = await svc.get_or_create_user(db, message.from_user.id, message.from_user.username)
        subjects = await svc.list_subjects(db, user)
    rows = [[InlineKeyboardButton(text=s["name"], callback_data=f"tsubj:{s['id']}")] for s in subjects]
    rows.append([InlineKeyboardButton(text="➕ Новый предмет", callback_data="tsubj_new")])
    await _say(
        message,
        "В какой <b>предмет</b> сохранить этот тест?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


async def _save_ai_test(reply_to: Message, from_user, state: FSMContext, subject_id: int):
    data = await state.get_data()
    qs, title = data.get("questions") or [], data.get("title", "Без названия")
    await state.clear()
    if not qs:
        return await reply_to.answer("Данные теста устарели, создайте заново.")
    questions = [ParsedQuestion(d["text"], d["options"], d["correct"]) for d in qs]
    async with dbmod.SessionLocal() as db:
        user = await svc.get_or_create_user(db, from_user.id, from_user.username)
        try:
            test = await svc.create_test(db, user, subject_id, title, questions)
        except svc.ServiceError as e:
            return await reply_to.answer("❌ " + escape(e.message))
    await _sweep(reply_to.bot, reply_to.chat.id)  # убираем всю служебную переписку, файл остаётся
    kb = InlineKeyboardMarkup(inline_keyboard=[[b]] if (b := webapp_button("▶️ Открыть в приложении")) else [])
    await reply_to.answer(
        f"✅ Сохранено ({len(questions)} вопросов). Можно запускать в приложении.\n<i>{escape(title)}</i>",
        reply_markup=kb,
    )


@router.callback_query(MakeTest.subject, F.data.regexp(r"^tsubj:\d+$"))
async def make_test_subject(cb: CallbackQuery, state: FSMContext):
    await _save_ai_test(cb.message, cb.from_user, state, int(cb.data.split(":")[1]))
    await cb.answer("Готово ✅")


@router.callback_query(MakeTest.subject, F.data == "tsubj_new")
async def make_test_subject_new(cb: CallbackQuery, state: FSMContext):
    await state.set_state(MakeTest.subject_new)
    await _say(cb.message, "Напишите название нового предмета:")
    await cb.answer()


@router.message(MakeTest.subject_new, F.text)
async def make_test_subject_name(message: Message, state: FSMContext):
    _remember(message.chat.id, message.message_id)
    async with dbmod.SessionLocal() as db:
        user = await svc.get_or_create_user(db, message.from_user.id, message.from_user.username)
        try:
            subj = await svc.create_subject(db, user, message.text)
        except svc.ServiceError as e:
            return await message.answer("❌ " + escape(e.message))
        sid = subj.id
    await _save_ai_test(message, message.from_user, state, sid)


def _rag_note(ctx: dict, lang: str = "ru") -> str:
    """Короткая пометка об источнике генерации: библиотека или общие знания ИИ."""
    if ctx and ctx.get("found"):
        src = ", ".join(ctx.get("sources", [])[:3])
        base = {"ru": "📚 По материалам библиотеки", "uz": "📚 Kutubxona materiallari asosida",
                "en": "📚 Based on library materials"}.get(lang, "📚 По материалам библиотеки")
        return "\n" + base + (f": {escape(src)}" if src else "")
    base = {"ru": "🧠 Общие знания ИИ", "uz": "🧠 Umumiy bilim (AI)",
            "en": "🧠 General AI knowledge"}.get(lang, "🧠 Общие знания ИИ")
    return "\n" + base


@router.message(F.text.in_(BTN_ALL["pres"]))
async def make_pres_start(message: Message, state: FSMContext):
    if not await _ai_gate(message, state):
        return
    async with dbmod.SessionLocal() as db:
        user = await svc.get_or_create_user(db, message.from_user.id, message.from_user.username)
        price = 0 if svc.is_free_user(user) else await svc.get_price(db, "presentation")
    _remember(message.chat.id, message.message_id)
    await state.set_state(MakePres.topic)
    hint = f"\n\n💳 Стоимость: {_money(price)} (спишется с баланса при создании)." if price else ""
    await _say(message, "🖥 Напишите <b>тему презентации</b> (например: «Анатомия сердца»)." + hint)


@router.message(MakePres.topic, F.text)
async def make_pres_topic(message: Message, state: FSMContext):
    _remember(message.chat.id, message.message_id)
    await state.update_data(topic=message.text.strip())
    await state.set_state(MakePres.lang)
    await _say(message, "На каком <b>языке</b> сделать презентацию?", reply_markup=lang_kb("plang"))


@router.callback_query(MakePres.lang, F.data.regexp(r"^plang:(ru|uz|en)$"))
async def make_pres_lang(cb: CallbackQuery, state: FSMContext):
    await state.update_data(lang=cb.data.split(":")[1])
    await state.set_state(MakePres.fio)
    await _say(cb.message, "Напишите <b>ФИО</b> (кто выполнил):")
    await cb.answer()


@router.message(MakePres.fio, F.text)
async def make_pres_fio(message: Message, state: FSMContext):
    _remember(message.chat.id, message.message_id)
    await state.update_data(fio=message.text.strip())
    await state.set_state(MakePres.group)
    await _say(message, "Напишите <b>номер группы</b>:")


@router.message(MakePres.group, F.text)
async def make_pres_group(message: Message, state: FSMContext):
    _remember(message.chat.id, message.message_id)
    await state.update_data(group=message.text.strip())
    await state.set_state(MakePres.count)
    await _say(message, "Сколько слайдов? Напишите число (максимум 20).")


@router.message(MakePres.count, F.text)
async def make_pres_count(message: Message, state: FSMContext):
    _remember(message.chat.id, message.message_id)
    digits = "".join(ch for ch in message.text if ch.isdigit())
    if not digits:
        return await _say(message, "Напишите число, например 10.")
    n = max(1, min(int(digits), 20))
    data = await state.get_data()
    topic, fio, group = data.get("topic", ""), data.get("fio", ""), data.get("group", "")
    lang = data.get("lang", "ru")
    await state.clear()
    async with dbmod.SessionLocal() as db:
        user = await svc.get_or_create_user(db, message.from_user.id, message.from_user.username)
        try:
            charged = await svc.charge_feature(db, user, "presentation")  # 0 для преподавателей
        except svc.ServiceError as e:
            return await message.answer("❌ " + escape(e.message), reply_markup=topup_inline_kb())
        await svc.reserve_presentation(db, user)
    note = " Много запросов — вы в очереди, подождите." if limits.queued() else ""
    wait = await _say(message, "⏳ Генерирую презентацию и подбираю фото…" + note)
    try:
        async with limits.gen_slot():  # очередь: не больше N генераций разом
            async with dbmod.SessionLocal() as db, limits.timing("rag"):
                ctx = await svc.library_context(db, topic)
            async with limits.timing("text"):
                body = await generate_slides(topic, slides=n, lang=lang, context=ctx["context"])
            # Берём КОРОТКИЙ заголовок от ИИ (не весь введённый текст темы),
            # а подзаголовок титульного — только автор и группа (подпись — на языке презентации).
            from .present import parse as _parse
            atitle, _asub, _sl = _parse(body)
            idx = body.find("#")
            slides_part = body[idx:] if idx != -1 else body
            clean_title = " ".join(atitle.split())[:100] or "Презентация"
            by = {"ru": "Выполнил(а)", "uz": "Bajardi", "en": "Prepared by"}.get(lang, "Выполнил(а)")
            grp = {"ru": "Группа", "uz": "Guruh", "en": "Group"}.get(lang, "Группа")
            author = f"{by}: {fio} · {grp} {group}" if (fio or group) else ""
            final = f"{clean_title}\n{author}\n\n{slides_part}"
            async with limits.timing("photos+build"):
                name, blob = await build_presentation(final, max_per_slide=2, sources=ctx.get("sources"))
    except svc.ServiceError as e:
        async with dbmod.SessionLocal() as db:
            u = await svc.get_or_create_user(db, message.from_user.id, message.from_user.username)
            await svc.refund(db, u, charged)  # вернуть деньги студенту
            await svc.release_presentation(db, u)
        return await message.answer("❌ " + escape(e.message))
    try:
        await wait.delete()
    except Exception:
        pass
    paid = f" Списано {_money(charged)}." if charged else ""
    await message.answer_document(
        BufferedInputFile(blob, name),
        caption=f"Готовая презентация ✅ Тема: {escape(topic)}.{paid} Откройте в PowerPoint / Google Slides.{_rag_note(ctx, lang)}",
    )
    await _sweep(message.bot, message.chat.id)  # убираем служебную переписку, файл остаётся


# ---------------------------------------------------------------- баланс и пополнение (студенты)

def topup_inline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=BTN_TOPUP, callback_data="tpopen")]])


async def _refund(from_user, amount: int):
    """Вернуть списанные средства студенту (если генерация не удалась)."""
    if not amount:
        return
    async with dbmod.SessionLocal() as db:
        u = await svc.get_or_create_user(db, from_user.id, from_user.username)
        await svc.refund(db, u, amount)


@router.message(F.text.in_(BTN_ALL["balance"]))
@router.message(Command("balance"))
async def balance_cmd(message: Message):
    async with dbmod.SessionLocal() as db:
        user = await svc.get_or_create_user(db, message.from_user.id, message.from_user.username)
        cfg = await svc.get_settings(db)
    if svc.is_free_user(user):
        return await message.answer("Для преподавателей создание тестов и презентаций бесплатно ✅")
    await message.answer(
        f"💰 Ваш баланс: <b>{_money(user.balance or 0)}</b>\n\n"
        f"Цены:\n🖥 Презентация — {_money(svc._price(cfg, 'presentation'))}\n"
        f"📝 Тест — {_money(svc._price(cfg, 'test'))}\n\n"
        "Пополнить — кнопка ниже или «💳 Пополнить баланс».",
        reply_markup=topup_inline_kb(),
    )


async def _topup_amounts_kb(user_id: int, username: str | None):
    """Клавиатура с суммами пополнения. Возвращает (kb, err): err — если пополнять не нужно."""
    async with dbmod.SessionLocal() as db:
        user = await svc.get_or_create_user(db, user_id, username)
        cfg = await svc.get_settings(db)
    if svc.is_free_user(user):
        return None, "Для преподавателей всё бесплатно — пополнять баланс не нужно ✅"
    amounts = []
    for part in (cfg.get("topup_amounts") or "").split(","):
        digits = "".join(ch for ch in part if ch.isdigit())
        if digits:
            amounts.append(int(digits))
    amounts = amounts or [10000, 25000, 50000]
    rows = [[InlineKeyboardButton(text=_money(a), callback_data=f"tpamt:{a}")] for a in amounts]
    return InlineKeyboardMarkup(inline_keyboard=rows), None


@router.message(F.text.in_(BTN_ALL["topup"]))
async def topup_start(message: Message):
    kb, err = await _topup_amounts_kb(message.from_user.id, message.from_user.username)
    if err:
        return await message.answer(err)
    await message.answer("💳 На какую сумму пополнить баланс?", reply_markup=kb)


@router.callback_query(F.data == "tpopen")
async def topup_open_cb(cb: CallbackQuery):
    kb, err = await _topup_amounts_kb(cb.from_user.id, cb.from_user.username)
    if err:
        return await cb.answer(err, show_alert=True)
    await cb.message.answer("💳 На какую сумму пополнить баланс?", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.regexp(r"^tpamt:\d+$"))
async def topup_amount_cb(cb: CallbackQuery):
    amount = int(cb.data.split(":")[1])
    async with dbmod.SessionLocal() as db:
        cfg = await svc.get_settings(db)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"tppaid:{amount}")]]
    )
    await cb.message.answer(
        f"💳 Пополнение на <b>{_money(amount)}</b>\n\n"
        "Переведите эту сумму на карту (Humo/Uzcard):\n"
        f"<code>{escape(cfg.get('card_number', ''))}</code>\n{escape(cfg.get('card_holder', ''))}\n\n"
        "После перевода нажмите «✅ Я оплатил» и <b>обязательно</b> пришлите скриншот чека.",
        reply_markup=kb,
    )
    await cb.answer()


@router.callback_query(F.data.regexp(r"^tppaid:\d+$"))
async def topup_paid_cb(cb: CallbackQuery, state: FSMContext):
    amount = int(cb.data.split(":")[1])
    await state.set_state(Pay.receipt)
    await state.update_data(amount=amount)
    await cb.message.answer(
        "📸 Пришлите <b>скриншот чека</b> об оплате — это обязательно. "
        "Без чека заявку подтвердить нельзя."
    )
    await cb.answer()


async def _submit_topup(reply_to: Message, bot: Bot, from_user, amount: int, photo_id: str | None):
    if amount <= 0:
        return await reply_to.answer("Сумма не распознана, начните заново: «💳 Пополнить баланс».")
    async with dbmod.SessionLocal() as db:
        user = await svc.get_or_create_user(db, from_user.id, from_user.username)
        topup = await svc.create_topup(db, user.id, amount)
        tid, uname = topup.id, user.full_name or "—"
    await reply_to.answer(
        "✅ Заявка отправлена! Админ проверит оплату и зачислит баланс — обычно это быстро. "
        "Баланс смотрите по кнопке «💰 Мой баланс»."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"tpok:{tid}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"tpno:{tid}"),
    ]])
    uref = f"@{from_user.username}" if from_user.username else "—"
    caption = (
        f"💳 <b>Пополнение #{tid}</b>\n"
        f"{escape(uname)} ({escape(uref)}, ID <code>{from_user.id}</code>)\n"
        f"Сумма: <b>{_money(amount)}</b>"
    )
    for admin in settings.admin_ids:
        try:
            if photo_id:
                await bot.send_photo(admin, photo_id, caption=caption, reply_markup=kb)
            else:
                await bot.send_message(admin, caption + "\n<i>(без чека)</i>", reply_markup=kb)
        except Exception:
            pass


@router.message(Pay.receipt, F.photo)
async def topup_receipt_photo(message: Message, state: FSMContext, bot: Bot):
    amount = (await state.get_data()).get("amount", 0)
    await state.clear()
    await _submit_topup(message, bot, message.from_user, amount, message.photo[-1].file_id)


@router.message(Pay.receipt)
async def topup_receipt_other(message: Message):
    await message.answer(
        "📸 Нужен именно <b>фото-скриншот чека</b> об оплате — пришлите его. "
        "Без чека заявку подтвердить нельзя."
    )


@router.callback_query(F.data.regexp(r"^tp(ok|no):\d+$"))
async def topup_decide_cb(cb: CallbackQuery, bot: Bot):
    if not is_admin(cb.from_user.id):
        return await cb.answer("Только для админа", show_alert=True)
    approve = cb.data.startswith("tpok")
    tid = int(cb.data.split(":")[1])
    async with dbmod.SessionLocal() as db:
        try:
            topup, user = await svc.decide_topup(db, tid, approve, cb.from_user.id)
        except svc.ServiceError as e:
            return await cb.answer(e.message, show_alert=True)
        svc.add_admin_log(
            db, cb.from_user.id, topup.user_id,
            f"{'зачислил' if approve else 'отклонил'} пополнение {topup.amount} сум",
        )
        await db.commit()
        uid, amount, bal = topup.user_id, topup.amount, (user.balance if user else 0)
    verdict = (
        f"✅ Зачислено {_money(amount)} · {escape(cb.from_user.full_name)}"
        if approve else f"❌ Отклонено · {escape(cb.from_user.full_name)}"
    )
    try:
        base = cb.message.html_text or ""
        if cb.message.photo:
            await cb.message.edit_caption(caption=f"{base}\n\n{verdict}")
        else:
            await cb.message.edit_text(f"{base}\n\n{verdict}")
    except Exception:
        pass
    try:
        if approve:
            await bot.send_message(uid, f"✅ Баланс пополнен на {_money(amount)}. Текущий баланс: {_money(bal)}.")
        else:
            await bot.send_message(uid, "❌ Пополнение отклонено. Если вы оплатили — свяжитесь с администратором.")
    except Exception:
        pass
    await cb.answer("Готово")


@router.message(Command("name"))
async def change_name(message: Message, state: FSMContext):
    await state.set_state(Reg.name)
    await message.answer("Напишите новые Фамилию и Имя:")


@router.message(Reg.name, F.text)
async def got_name(message: Message, state: FSMContext):
    first_time = (await state.get_data()).get("first_time")
    async with dbmod.SessionLocal() as db:
        user = await svc.get_or_create_user(db, message.from_user.id, message.from_user.username)
        try:
            await svc.set_full_name(db, user, message.text)
        except svc.ServiceError as e:
            return await message.answer(e.message)
    await state.clear()
    await message.answer(f"Готово, <b>{escape(user.full_name)}</b> ✅")
    # При первой регистрации спрашиваем роль; админ сразу преподаватель.
    if first_time and not is_admin(user.id):
        return await message.answer(ROLE_CHOICE_TEXT, reply_markup=role_choice_keyboard())
    await send_menu(message, user)


# ---------------------------------------------------------------- выбор и смена роли

@router.callback_query(F.data == "role:student")
async def choose_student(cb: CallbackQuery):
    async with dbmod.SessionLocal() as db:
        user = await svc.get_or_create_user(db, cb.from_user.id, cb.from_user.username)
        try:
            await svc.set_role(db, user, "student")
        except svc.ServiceError as e:
            return await cb.answer(e.message, show_alert=True)
    await cb.answer("Готово ✅")
    await send_menu(cb.message, user)


@router.callback_query(F.data == "apply_status")
async def apply_status(cb: CallbackQuery):
    await cb.answer("Заявка преподавателя ещё на рассмотрении.", show_alert=True)


def universities_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=u, callback_data=f"uni:{i}")] for i, u in enumerate(UNIVERSITIES)]
    rows.append([InlineKeyboardButton(text="➕ Другой вуз…", callback_data="uni:other")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _search_keyboard(matches: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=u, callback_data=f"uni:{i}")] for i, u in matches[:40]]
    rows.append([InlineKeyboardButton(text="➕ Другой вуз…", callback_data="uni:other")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _uni_search_prompt() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Показать все вузы", callback_data="uni_all")],
            [InlineKeyboardButton(text="➕ Другой вуз…", callback_data="uni:other")],
        ]
    )


@router.callback_query(F.data == "apply")
async def apply(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Apply.search)  # далее текст от пользователя трактуем как поиск вуза
    await state.update_data(mode="apply")
    await cb.message.answer(
        "Напишите <b>название вашего вуза</b> (можно часть) — покажу совпадения.\n"
        "Или откройте полный список кнопкой ниже.",
        reply_markup=_uni_search_prompt(),
    )
    await cb.answer()


@router.callback_query(F.data == "editname")
async def edit_name_cb(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Reg.name)
    await cb.message.answer("Напишите новые Фамилию и Имя:")
    await cb.answer()


@router.callback_query(F.data == "editwork")
async def edit_work_cb(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Apply.search)
    await state.update_data(mode="edit")
    await cb.message.answer(
        "Напишите <b>название вашего вуза</b> (можно часть) — покажу совпадения, "
        "и выбранный вуз станет вашим местом работы.",
        reply_markup=_uni_search_prompt(),
    )
    await cb.answer()


async def _ask_kafedra(reply_to: Message, state: FSMContext, vuz: str):
    """После выбора вуза спрашиваем кафедру."""
    await state.update_data(vuz=vuz)
    await state.set_state(Apply.kafedra)
    await reply_to.answer(f"Вуз: <b>{escape(vuz)}</b>\nТеперь напишите вашу <b>кафедру</b>:")


async def _apply_choice(cb_or_msg, from_user, bot: Bot, state: FSMContext, info: str, kafedra: str):
    """Применить вуз + кафедру: либо заявка, либо смена места работы."""
    mode = (await state.get_data()).get("mode")
    await state.clear()
    if mode == "edit":
        async with dbmod.SessionLocal() as db:
            user = await svc.get_or_create_user(db, from_user.id, from_user.username)
            try:
                await svc.set_teacher_info(db, user, info, kafedra)
            except svc.ServiceError as e:
                return await cb_or_msg.answer(e.message)
        return await cb_or_msg.answer(
            f"Обновлено ✅\nВуз: <b>{escape(info)}</b>\nКафедра: <b>{escape(kafedra)}</b>"
        )
    await _submit_application(cb_or_msg, from_user, bot, info, kafedra)


@router.message(Apply.search, F.text)
async def apply_search(message: Message, state: FSMContext):
    q = " ".join(message.text.split()).lower()
    matches = [(i, u) for i, u in enumerate(UNIVERSITIES) if q in u.lower()]
    if not matches:
        return await message.answer(
            "Ничего не нашлось. Попробуйте другую часть названия или нажмите «Другой вуз».",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="➕ Другой вуз…", callback_data="uni:other")]]
            ),
        )
    extra = f"\nНайдено {len(matches)}, показаны первые 40." if len(matches) > 40 else ""
    await message.answer(f"Выберите ваш вуз:{extra}", reply_markup=_search_keyboard(matches))


@router.callback_query(F.data == "uni_all")
async def apply_all(cb: CallbackQuery):
    await cb.message.answer("Все вузы:", reply_markup=universities_keyboard())
    await cb.answer()


@router.callback_query(F.data.regexp(r"^uni:(\d+|other)$"))
async def apply_uni(cb: CallbackQuery, state: FSMContext, bot: Bot):
    val = cb.data.split(":")[1]
    if val == "other":
        await state.set_state(Apply.info)
        await cb.message.answer("Напишите название вашего вуза:")
        return await cb.answer()
    idx = int(val)
    if idx >= len(UNIVERSITIES):
        return await cb.answer("Выберите вуз из списка.", show_alert=True)
    await _ask_kafedra(cb.message, state, UNIVERSITIES[idx])
    await cb.answer()


@router.message(Apply.info, F.text)
async def apply_info(message: Message, state: FSMContext):
    await _ask_kafedra(message, state, " ".join(message.text.split()))


@router.message(Apply.kafedra, F.text)
async def apply_kafedra(message: Message, state: FSMContext, bot: Bot):
    vuz = (await state.get_data()).get("vuz", "")
    await _apply_choice(message, message.from_user, bot, state, vuz, message.text)


async def _submit_application(reply_to: Message, from_user, bot: Bot, info: str, kafedra: str = ""):
    """Подать заявку преподавателя с выбранным вузом и кафедрой."""
    async with dbmod.SessionLocal() as db:
        user = await svc.get_or_create_user(db, from_user.id, from_user.username)
        try:
            await svc.request_teacher(db, user, info, kafedra)
        except svc.ServiceError as e:
            return await reply_to.answer(e.message)
        pending, saved_info, saved_kaf = user.teacher_pending, user.teacher_info, user.teacher_kafedra
    if not pending:  # админ — одобрен сразу
        await reply_to.answer("Вы преподаватель ✅")
        return await send_menu(reply_to, user)
    await reply_to.answer("Заявка отправлена ✅ Мы сообщим, когда её одобрят.")
    # Сразу показываем меню и кнопки — чтобы не нужно было заново нажимать /start.
    async with dbmod.SessionLocal() as db:
        u2 = await svc.get_or_create_user(db, from_user.id, from_user.username)
    await send_menu(reply_to, u2)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve:{user.id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{user.id}"),
            ]
        ]
    )
    uname = f" (@{escape(user.username)})" if user.username else ""
    for admin in settings.admin_ids:
        try:
            await bot.send_message(
                admin,
                f"🆕 Заявка преподавателя\n\n<b>{escape(user.full_name or '')}</b>{uname}\n"
                f"Вуз: {escape(saved_info or '—')}\nКафедра: {escape(saved_kaf or '—')}\n"
                f"ID: <code>{user.id}</code>",
                reply_markup=kb,
            )
        except Exception as e:  # админ не запускал бота
            log.warning("Не удалось уведомить админа %s: %s", admin, e)


@router.callback_query(F.data.regexp(r"^(approve|reject):\d+$"))
async def decide(cb: CallbackQuery, bot: Bot):
    if not is_admin(cb.from_user.id):
        return await cb.answer("Только для админа", show_alert=True)
    action, uid = cb.data.split(":")
    approve = action == "approve"
    async with dbmod.SessionLocal() as db:
        try:
            user = await svc.decide_teacher(db, int(uid), approve)
        except svc.ServiceError as e:
            return await cb.answer(e.message, show_alert=True)
    mark = "✅ Одобрено" if approve else "❌ Отклонено"
    await cb.message.edit_text(cb.message.html_text + f"\n\n<b>{mark}</b>")
    try:
        if approve:
            await bot.send_message(
                user.id,
                "🎉 Вы подтверждены как преподаватель!\n\nОтправьте сюда файл с тестом или откройте приложение.",
                reply_markup=menu_keyboard(user),
            )
            # Обновляем закреплённые кнопки снизу (появится «Создать тест») — без повторного /start.
            await bot.send_message(
                user.id,
                "⬇️ Снизу закреплены кнопки: «📝 Создать тест» и «🖥 Создать презентацию».",
                reply_markup=main_reply_kb(user),
            )
        else:
            await bot.send_message(user.id, "К сожалению, заявка преподавателя отклонена.")
    except Exception as e:
        log.warning("Не удалось уведомить пользователя %s: %s", user.id, e)
    await cb.answer()


# ---------------------------------------------------------------- шаблоны и загрузка тестов

@router.callback_query(F.data == "templates")
async def templates_cb(cb: CallbackQuery):
    await send_templates(cb.message)
    await cb.answer()


@router.message(Command("template"))
async def templates_cmd(message: Message):
    await send_templates(message)


# ---------------------------------------------------------------- презентации
def present_choice_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🤖 По теме (ИИ сам напишет)", callback_data="present:ai")],
            [InlineKeyboardButton(text="📝 Из моего текста", callback_data="present:text")],
        ]
    )


PRESENT_CHOICE = "🖥 <b>Создание презентации</b>\n\nКак сделать?"


@router.callback_query(F.data == "present")
async def present_cb(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer(PRESENT_CHOICE, reply_markup=present_choice_kb())
    await cb.answer()


@router.message(Command("present"))
async def present_cmd(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(PRESENT_CHOICE, reply_markup=present_choice_kb())


@router.callback_query(F.data == "present:text")
async def present_text_cb(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Present.text)
    await cb.message.answer(PRESENT_PROMPT)
    await cb.answer()


@router.callback_query(F.data == "present:ai")
async def present_ai_cb(cb: CallbackQuery, state: FSMContext):
    if not settings.anthropic_api_key:
        await state.clear()
        return await cb.answer(
            "ИИ-режим пока не подключён. Нужен ключ ANTHROPIC_API_KEY в .env. "
            "Пока доступно «Из моего текста».",
            show_alert=True,
        )
    await state.set_state(Present.topic)
    sent = await cb.message.answer(
        "🤖 Напишите <b>тему</b> презентации одним сообщением.\n"
        "<i>Например: «Анатомия сердца» или «Кариес: причины и профилактика».</i>"
    )
    _remember(cb.message.chat.id, sent.message_id)
    await cb.answer()


@router.message(Present.topic, F.text)
async def present_ai_topic(message: Message, state: FSMContext):
    _remember(message.chat.id, message.message_id)
    await state.update_data(topic=message.text.strip())
    await state.set_state(Present.lang)
    await _say(message, "На каком <b>языке</b> сделать презентацию?", reply_markup=lang_kb("prlang"))


@router.callback_query(Present.lang, F.data.regexp(r"^prlang:(ru|uz|en)$"))
async def present_ai_build(cb: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    topic, lang = data.get("topic", ""), cb.data.split(":")[1]
    await state.clear()
    await cb.answer()
    async with dbmod.SessionLocal() as db:
        user = await svc.get_or_create_user(db, cb.from_user.id, cb.from_user.username)
        try:
            await svc.reserve_presentation(db, user)
        except svc.ServiceError as e:
            return await cb.message.answer("❌ " + escape(e.message))
    qn = " Много запросов — вы в очереди, подождите." if limits.queued() else ""
    await _say(cb.message, "⏳ Генерирую презентацию по теме и подбираю фото, это займёт немного времени…" + qn)
    try:
        async with limits.gen_slot():
            async with dbmod.SessionLocal() as db, limits.timing("rag"):
                ctx = await svc.library_context(db, topic)
            async with limits.timing("text"):
                text = await generate_slides(topic, lang=lang, context=ctx["context"])
            async with limits.timing("photos+build"):
                name, data2 = await build_presentation(text, max_per_slide=2, sources=ctx.get("sources"))
    except svc.ServiceError as e:
        async with dbmod.SessionLocal() as db:
            u = await svc.get_or_create_user(db, cb.from_user.id, cb.from_user.username)
            await svc.release_presentation(db, u)
        return await cb.message.answer("❌ " + escape(e.message))
    await cb.message.answer_document(
        BufferedInputFile(data2, name),
        caption="Готовая презентация ✅ Проверьте содержание и при желании поправьте в PowerPoint / Google Slides." + _rag_note(ctx, lang),
    )
    await _sweep(bot, cb.message.chat.id)  # убираем служебную переписку, файл остаётся


@router.message(Command("present_example"))
async def present_example_cmd(message: Message):
    await message.answer(
        "Пример текста для презентации (скопируйте, замените на своё и пришлите):\n\n"
        "<pre>" + escape(PRESENT_EXAMPLE) + "</pre>"
    )


@router.message(Present.text, F.text)
async def present_build(message: Message, state: FSMContext):
    await state.clear()
    try:
        # сборка .pptx — тяжёлая синхронная работа; в поток, чтобы не блокировать loop
        name, data = await asyncio.to_thread(build_pptx, message.text)
    except svc.ServiceError as e:
        return await message.answer("❌ " + escape(e.message))
    await message.answer_document(
        BufferedInputFile(data, name),
        caption="Готовая презентация ✅ Откройте в PowerPoint или Google Slides и при желании поправьте.",
    )


async def send_templates(message: Message):
    await message.answer_document(
        BufferedInputFile(template_docx(), "shablon_test.docx"),
        caption="Word: варианты A) B) C)…, правильный отметьте звёздочкой * перед буквой",
    )
    await message.answer_document(
        BufferedInputFile(template_xlsx(), "shablon_test.xlsx"),
        caption="Excel: Вопрос | Варианты | Ответ (буква A, B, C...)",
    )
    await message.answer(
        "Также подходят форматы «+/−» (правильный +, неправильные −) "
        "и систем тестирования (++++ / ==== / #правильный).\n\n"
        "Пример текста:\n<pre>" + escape(TEMPLATE_TXT) + "</pre>"
    )


@router.message(F.document)
async def got_document(message: Message, state: FSMContext):
    async with dbmod.SessionLocal() as db:
        user = await svc.get_or_create_user(db, message.from_user.id, message.from_user.username)
        if user.blocked:
            return await message.answer("Доступ заблокирован.")
        if not user.full_name:
            return await message.answer("Сначала напишите ваши Фамилию и Имя: /start")
        name = (message.document.file_name or "").lower()
        if not name.endswith(ALLOWED_EXT):
            return await message.answer("Поддерживаются файлы .docx, .xlsx и .txt. Шаблоны: /template")
        if (message.document.file_size or 0) > 10 * 1024 * 1024:
            return await message.answer("Файл больше 10 МБ.")
        subjects = await svc.list_subjects(db, user)
    await state.clear()
    await state.update_data(file_id=message.document.file_id, file_name=message.document.file_name)
    rows = [[InlineKeyboardButton(text=s["name"], callback_data=f"up_subj:{s['id']}")] for s in subjects]
    rows.append([InlineKeyboardButton(text="➕ Новый предмет", callback_data="up_new")])
    await message.answer("Для какого предмета этот тест?", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "up_new")
async def up_new(cb: CallbackQuery, state: FSMContext):
    if not (await state.get_data()).get("file_id"):
        return await cb.answer("Сначала отправьте файл", show_alert=True)
    await state.set_state(Upload.subject_new)
    await cb.message.answer("Напишите название предмета:")
    await cb.answer()


@router.message(Upload.subject_new, F.text)
async def up_subject_name(message: Message, state: FSMContext):
    async with dbmod.SessionLocal() as db:
        user = await svc.get_or_create_user(db, message.from_user.id)
        try:
            subj = await svc.create_subject(db, user, message.text)
        except svc.ServiceError as e:
            return await message.answer(e.message)
    await state.update_data(subject_id=subj.id)
    await state.set_state(Upload.title)
    await message.answer("Напишите название теста (например: «Кости скелета»):")


@router.callback_query(F.data.regexp(r"^up_subj:\d+$"))
async def up_subject(cb: CallbackQuery, state: FSMContext):
    if not (await state.get_data()).get("file_id"):
        return await cb.answer("Сначала отправьте файл", show_alert=True)
    await state.update_data(subject_id=int(cb.data.split(":")[1]))
    await state.set_state(Upload.title)
    await cb.message.answer("Напишите название теста (например: «Кости скелета»):")
    await cb.answer()


async def _parse_from_state(bot: Bot, data: dict):
    buf = await bot.download(data["file_id"])
    # разбор файла (docx/xlsx/pdf) — синхронный и может быть тяжёлым; уводим в поток
    return await asyncio.to_thread(parse_file, data["file_name"], buf.read())


@router.message(Upload.title, F.text)
async def up_title(message: Message, state: FSMContext, bot: Bot):
    await state.update_data(title=message.text.strip())
    data = await state.get_data()
    try:
        parsed = await _parse_from_state(bot, data)
    except ParseFailed as e:
        await state.clear()
        return await message.answer(f"❌ {escape(str(e))}")
    if not parsed.questions and not parsed.errors:
        await state.clear()
        return await message.answer("В файле не найдено вопросов. Посмотрите шаблоны: /template")
    if parsed.errors:
        lines = [f"№{e.number}: {escape(e.message)} — <i>{escape(e.preview)}</i>" for e in parsed.errors[:15]]
        more = f"\n…и ещё {len(parsed.errors) - 15}" if len(parsed.errors) > 15 else ""
        rows = []
        if parsed.questions:
            rows.append(
                [InlineKeyboardButton(text=f"💾 Сохранить {len(parsed.questions)} правильных", callback_data="up_save")]
            )
        rows.append([InlineKeyboardButton(text="✖️ Отмена (исправлю файл)", callback_data="up_cancel")])
        return await message.answer(
            f"Найдено вопросов: <b>{parsed.total_found}</b>\n"
            f"✅ Без ошибок: {len(parsed.questions)}\n⚠️ С ошибками: {len(parsed.errors)}\n\n"
            + "\n".join(lines)
            + more
            + "\n\nМожно исправить файл и отправить заново, или сохранить правильные "
            "и дописать остальные в приложении.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
    await _save(message, state, parsed, message.from_user.id)


@router.callback_query(F.data == "up_save")
async def up_save(cb: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    if not data.get("file_id"):
        return await cb.answer("Загрузка устарела, отправьте файл заново", show_alert=True)
    try:
        parsed = await _parse_from_state(bot, data)
    except ParseFailed as e:
        await state.clear()
        return await cb.message.answer(f"❌ {escape(str(e))}")
    await _save(cb.message, state, parsed, cb.from_user.id)
    await cb.answer()


@router.callback_query(F.data == "up_cancel")
async def up_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer("Отменено. Исправьте файл и отправьте снова.")
    await cb.answer()


async def _save(message: Message, state: FSMContext, parsed, user_id: int):
    data = await state.get_data()
    async with dbmod.SessionLocal() as db:
        user = await svc.get_or_create_user(db, user_id)
        try:
            test = await svc.create_test(db, user, data["subject_id"], data["title"], parsed.questions)
        except svc.ServiceError as e:
            await state.clear()
            return await message.answer(f"❌ {escape(e.message)}")
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[[b]] if (b := webapp_button("▶️ Запустить в приложении")) else [])
    await message.answer(
        f"✅ Сохранено ({len(parsed.questions)} вопросов). Можно запускать в приложении.\n<i>{escape(test.title)}</i>",
        reply_markup=kb,
    )


# ---------------------------------------------------------------- админ

@router.message(Command("myid"))
async def myid(message: Message):
    await message.answer(f"Ваш Telegram ID: <code>{message.from_user.id}</code>")


def _stats_text(s: dict) -> str:
    return (
        "📊 <b>Статистика</b>\n\n"
        f"Пользователей: {s['users']}\n"
        f"Преподавателей: {s['teachers']}\n"
        f"Pro-подписок: {s['pro']}\n"
        f"📝 Тестов создано: {s['tests']}\n"
        f"🖥 Презентаций всего: {s.get('presentations', 0)}\n"
        f"💰 Заработано: {_money(s.get('revenue', 0))}\n"
        f"🧾 Пополнений ждут подтверждения: {s.get('topups_pending', 0)}\n"
        f"Запусков за сутки: {s['sessions_day']}, за неделю: {s['sessions_week']}\n"
        f"Прохождений за неделю: {s['attempts_week']}"
    )


def _teachers_text(users: list[User]) -> str:
    if not users:
        return "Преподавателей пока нет."
    lines = []
    for u in users[:100]:
        if u.is_pro_plus:
            plan = f"Pro+ до {u.proplus_until:%d.%m.%Y}"
        elif u.is_pro:
            plan = f"Pro до {u.pro_until:%d.%m.%Y}"
        else:
            plan = "free"
        kaf = f" · {escape(u.teacher_kafedra)}" if u.teacher_kafedra else ""
        lines.append(f"<code>{u.id}</code> {escape(u.full_name or '?')} — {escape(u.teacher_info or '')}{kaf} [{plan}]")
    return "\n".join(lines)


@router.message(Command("stats"))
async def stats(message: Message):
    if not is_admin(message.from_user.id):
        return
    async with dbmod.SessionLocal() as db:
        s = await svc.admin_stats(db)
    await message.answer(_stats_text(s))


@router.message(Command("teachers"))
async def teachers(message: Message):
    if not is_admin(message.from_user.id):
        return
    async with dbmod.SessionLocal() as db:
        users = await svc.list_teachers(db)
    await message.answer(_teachers_text(users))


@router.message(Command("backup"))
async def backup_now(message: Message, bot: Bot):
    """Сделать копию базы и прислать её прямо сейчас (для админа)."""
    if not is_admin(message.from_user.id):
        return
    from .backup import send_backup

    await message.answer("Делаю копию базы…")
    try:
        n = await send_backup(bot)
        if not n:
            await message.answer("Не удалось создать копию: файл базы не найден.")
    except Exception:
        log.exception("Ошибка ручного бэкапа")
        await message.answer("Не удалось создать копию. Подробности в логах.")


@router.callback_query(F.data == "adm:stats")
async def adm_stats_cb(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return await cb.answer("Только для админа", show_alert=True)
    async with dbmod.SessionLocal() as db:
        s = await svc.admin_stats(db)
    await cb.message.answer(_stats_text(s))
    await cb.answer()


@router.callback_query(F.data == "adm:teachers")
async def adm_teachers_cb(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return await cb.answer("Только для админа", show_alert=True)
    async with dbmod.SessionLocal() as db:
        users = await svc.list_teachers(db)
    await cb.message.answer(_teachers_text(users))
    await cb.answer()


@router.message(Command("give_pro"))
async def give_pro(message: Message, command: CommandObject, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    try:
        uid, days = (int(x) for x in (command.args or "").split())
    except ValueError:
        return await message.answer("Формат: /give_pro <ID> <дней>\nНапример: /give_pro 123456789 30")
    async with dbmod.SessionLocal() as db:
        try:
            user = await svc.give_pro(db, uid, days)
        except svc.ServiceError as e:
            return await message.answer(e.message)
    await message.answer(f"✅ Pro до {user.pro_until:%d.%m.%Y} для {escape(user.full_name or str(uid))}")
    try:
        await bot.send_message(uid, f"⭐ Подписка Pro активна до {user.pro_until:%d.%m.%Y}. Спасибо!")
    except Exception:
        pass


@router.message(Command("unpro"))
async def unpro(message: Message, command: CommandObject, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    try:
        uid = int((command.args or "").strip())
    except ValueError:
        return await message.answer("Формат: /unpro <ID>\nНапример: /unpro 123456789")
    async with dbmod.SessionLocal() as db:
        try:
            user = await svc.remove_pro(db, uid)
        except svc.ServiceError as e:
            return await message.answer(e.message)
    await message.answer(f"✅ Pro снят у {escape(user.full_name or str(uid))}")
    try:
        await bot.send_message(uid, "Подписка Pro снята. Вы на бесплатном тарифе.")
    except Exception:
        pass


@router.message(Command("give_proplus"))
async def give_proplus_cmd(message: Message, command: CommandObject, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    try:
        uid, days = (int(x) for x in (command.args or "").split())
    except ValueError:
        return await message.answer("Формат: /give_proplus <ID> <дней>\nНапример: /give_proplus 123456789 30")
    async with dbmod.SessionLocal() as db:
        try:
            user = await svc.give_pro_plus(db, uid, days)
        except svc.ServiceError as e:
            return await message.answer(e.message)
    await message.answer(f"💎 Pro+ до {user.proplus_until:%d.%m.%Y} для {escape(user.full_name or str(uid))}")
    try:
        await bot.send_message(uid, f"💎 Pro+ активен до {user.proplus_until:%d.%m.%Y}. Открыты все возможности!")
    except Exception:
        pass


@router.message(Command("unproplus"))
async def unproplus_cmd(message: Message, command: CommandObject, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    try:
        uid = int((command.args or "").strip())
    except ValueError:
        return await message.answer("Формат: /unproplus <ID>\nНапример: /unproplus 123456789")
    async with dbmod.SessionLocal() as db:
        try:
            user = await svc.remove_pro_plus(db, uid)
        except svc.ServiceError as e:
            return await message.answer(e.message)
    await message.answer(f"✅ Pro+ снят у {escape(user.full_name or str(uid))}")
    try:
        await bot.send_message(uid, "Подписка Pro+ снята.")
    except Exception:
        pass


@router.message(Command("covers"))
async def covers_cmd(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("⏳ Делаю обложки и определяю названия для уже загруженных книг…")
    async with dbmod.SessionLocal() as db:
        try:
            n = await svc.backfill_covers(db)
        except Exception as e:
            return await message.answer(f"Ошибка: {escape(str(e))}")
    await message.answer(f"✅ Обработано книг: {n}. Откройте библиотеку — обложки на месте.")


@router.message(Command("block", "unblock"))
async def block(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        return
    try:
        uid = int((command.args or "").strip())
    except ValueError:
        return await message.answer(f"Формат: /{command.command} <ID>")
    async with dbmod.SessionLocal() as db:
        user = await db.get(User, uid)
        if not user:
            return await message.answer("Пользователь не найден.")
        user.blocked = command.command == "block"
        await db.commit()
    await message.answer("Готово.")


@router.message(Command("qollanma"))
async def qollanma_cmd(message: Message):
    await send_qollanma(message)


@router.callback_query(F.data == "qollanma")
async def qollanma_cb(cb: CallbackQuery):
    await send_qollanma(cb.message)
    await cb.answer()


@router.message(Command("help"))
async def help_cmd(message: Message):
    text = (
        "/start — меню\n/name — изменить ФИО\n/template — шаблоны файлов для тестов\n"
        "/present — сделать презентацию\n/balance — баланс и пополнение\n/myid — ваш ID"
    )
    if is_admin(message.from_user.id):
        text += (
            "\n\n<b>Админ:</b>\n/stats — статистика\n/teachers — преподаватели\n"
            "/give_pro ID ДНЕЙ — выдать Pro\n/block ID, /unblock ID"
        )
    await message.answer(text + CREDIT)


@router.message(F.text)
async def fallback(message: Message, state: FSMContext):
    if await state.get_state():
        return await message.answer("Пожалуйста, отправьте текст или /start, чтобы начать заново.")
    async with dbmod.SessionLocal() as db:
        user = await svc.get_or_create_user(db, message.from_user.id, message.from_user.username)
    if not user.full_name:
        return await start(message, state)
    if message.text.strip().replace(" ", "").isdigit():
        kb = InlineKeyboardMarkup(inline_keyboard=[[b]] if (b := webapp_button("▶️ Ввести код в приложении")) else [])
        return await message.answer("Код теста вводится в приложении 👇", reply_markup=kb)
    await send_menu(message, user)


# ---------------------------------------------------------------- уведомления

async def notify_finished(bot: Bot, session_ids: list[int]):
    """Сообщить учителю, что тест закончился, с итогами."""
    for sid in session_ids:
        async with dbmod.SessionLocal() as db:
            s = await db.get(TestSession, sid)
            if not s or s.notified:
                continue
            test = await db.get(Test, s.test_id)
            attempts = (await db.scalars(select(Attempt).where(Attempt.session_id == sid))).all()
            counted = [a for a in attempts if a.finish_reason != "kicked" and a.total]
            avg = round(sum(a.correct_count * 100 / a.total for a in counted) / len(counted)) if counted else 0
            s.notified = True
            await db.commit()
        kb = InlineKeyboardMarkup(inline_keyboard=[[b]] if (b := webapp_button("📊 Открыть результаты")) else [])
        try:
            await bot.send_message(
                s.teacher_id,
                f"⏰ Тест <b>{escape(test.title)}</b> (группа {escape(s.group_name)}) завершён.\n"
                f"Писали: {len(counted)} · средний результат: {avg}%",
                reply_markup=kb,
            )
        except Exception as e:
            log.warning("Не удалось уведомить учителя %s: %s", s.teacher_id, e)


_dispatcher: Dispatcher | None = None


def create_bot() -> tuple[Bot, Dispatcher]:
    global _dispatcher
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    if _dispatcher is None:
        _dispatcher = Dispatcher()
        _dispatcher.include_router(router)
    return bot, _dispatcher


async def setup_bot(bot: Bot):
    from aiogram.types import BotCommand

    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Меню"),
            BotCommand(command="name", description="Изменить ФИО"),
            BotCommand(command="template", description="Шаблоны файлов для тестов"),
            BotCommand(command="present", description="Сделать презентацию"),
            BotCommand(command="balance", description="Баланс и пополнение"),
            BotCommand(command="language", description="🌐 Til / Язык / Language"),
            BotCommand(command="help", description="Помощь"),
        ]
    )
    if settings.webapp_url.startswith("https://"):
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Приложение", web_app=WebAppInfo(url=settings.webapp_url))
        )
    else:
        log.warning("WEBAPP_URL не задан или не https — кнопка приложения не появится.")
