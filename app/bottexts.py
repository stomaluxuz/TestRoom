"""Локализация интерфейса бота (uz / ru / en). Этап 1: вход, меню, кнопки, регистрация.

t(key, lang) — строка на нужном языке; detect_lang — язык по коду Telegram;
BTN — тексты главных кнопок по языку; BTN_ALL — множества всех переводов кнопки
(для фильтров aiogram, чтобы кнопка ловилась на любом языке)."""
from __future__ import annotations

LANGS = ("uz", "ru", "en")
DEFAULT_LANG = "ru"


def detect_lang(code: str | None) -> str:
    """Язык по Telegram language_code ('uz', 'ru', 'en-US' …). По умолчанию — русский."""
    c = (code or "").lower()
    if c.startswith("uz"):
        return "uz"
    if c.startswith("en"):
        return "en"
    if c.startswith("ru"):
        return "ru"
    return DEFAULT_LANG


# Тексты главных кнопок (reply-клавиатура).
BTN = {
    "pres": {
        "ru": "🖥 Создать презентацию", "uz": "🖥 Taqdimot yaratish", "en": "🖥 Create presentation",
    },
    "test": {
        "ru": "📝 Создать тест", "uz": "📝 Test yaratish", "en": "📝 Create test",
    },
    "balance": {
        "ru": "💰 Мой баланс", "uz": "💰 Balansim", "en": "💰 My balance",
    },
    "topup": {
        "ru": "💳 Пополнить баланс", "uz": "💳 Balansni to'ldirish", "en": "💳 Top up balance",
    },
}
# Множества всех переводов каждой кнопки — для F.text.in_(...), чтобы ловить на любом языке.
BTN_ALL = {name: frozenset(v.values()) for name, v in BTN.items()}


def btn(name: str, lang: str) -> str:
    return BTN.get(name, {}).get(lang) or BTN.get(name, {}).get(DEFAULT_LANG, "")


_T = {
    "blocked": {
        "ru": "Доступ заблокирован.",
        "uz": "Kirish bloklangan.",
        "en": "Access is blocked.",
    },
    "welcome_name": {
        "ru": "Добро пожаловать! 👋\n\nНапишите ваши <b>Фамилию и Имя</b> полностью.\n"
              "Их увидит преподаватель в результатах тестов.\n\n<i>Например: Каримов Азиз</i>",
        "uz": "Xush kelibsiz! 👋\n\n<b>Familiya va Ismingizni</b> to'liq yozing.\n"
              "Ularni o'qituvchi test natijalarida ko'radi.\n\n<i>Masalan: Karimov Aziz</i>",
        "en": "Welcome! 👋\n\nPlease type your <b>full name</b>.\n"
              "Your teacher will see it in the test results.\n\n<i>Example: Karimov Aziz</i>",
    },
    "need_name": {
        "ru": "Сначала напишите ваши Фамилию и Имя: /start",
        "uz": "Avval Familiya va Ismingizni yozing: /start",
        "en": "First type your full name: /start",
    },
    "ai_off": {
        "ru": "🤖 ИИ пока не подключён. Обратитесь к администратору.",
        "uz": "🤖 AI hali ulanmagan. Administratorga murojaat qiling.",
        "en": "🤖 AI is not connected yet. Contact the administrator.",
    },
    "menu_hint_teacher": {
        "ru": "⬇️ Снизу закреплены кнопки: «📝 Создать тест» и «🖥 Создать презентацию».",
        "uz": "⬇️ Pastda tugmalar: «📝 Test yaratish» va «🖥 Taqdimot yaratish».",
        "en": "⬇️ Buttons below: “📝 Create test” and “🖥 Create presentation”.",
    },
    "menu_hint_student": {
        "ru": "⬇️ Снизу закреплены кнопки: «📝 Создать тест», «🖥 Создать презентацию», "
              "«💰 Мой баланс» и «💳 Пополнить баланс».",
        "uz": "⬇️ Pastda tugmalar: «📝 Test yaratish», «🖥 Taqdimot yaratish», "
              "«💰 Balansim» va «💳 Balansni to'ldirish».",
        "en": "⬇️ Buttons below: “📝 Create test”, “🖥 Create presentation”, "
              "“💰 My balance” and “💳 Top up balance”.",
    },
    "choose_language": {
        "ru": "🌐 Выберите язык интерфейса:",
        "uz": "🌐 Interfeys tilini tanlang:",
        "en": "🌐 Choose the interface language:",
    },
    "lang_set": {
        "ru": "✅ Язык переключён на русский.",
        "uz": "✅ Til o'zbekchaga o'zgartirildi.",
        "en": "✅ Language switched to English.",
    },
}


def t(key: str, lang: str) -> str:
    row = _T.get(key, {})
    return row.get(lang) or row.get(DEFAULT_LANG) or key
