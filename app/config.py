"""Настройки проекта. Все значения берутся из файла .env или переменных окружения."""
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _ids(value: str) -> set[int]:
    return {int(x) for x in value.replace(" ", "").split(",") if x}


def _library_dir() -> str:
    """Папка для файлов библиотеки. Явный LIBRARY_DIR, иначе рядом с файлом SQLite-базы."""
    env = os.getenv("LIBRARY_DIR", "").strip()
    if env:
        return env
    url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./testbot.db")
    if url.startswith("sqlite") and ":///" in url:
        db_path = url.split(":///", 1)[-1]
        if db_path:
            return os.path.join(os.path.dirname(db_path) or ".", "library")
    return "./library"


def _webapp_url() -> str:
    """Публичный адрес Mini App. На Railway берётся автоматически из RAILWAY_PUBLIC_DOMAIN."""
    url = os.getenv("WEBAPP_URL", "").strip()
    if url:
        return url
    domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
    return f"https://{domain}" if domain else ""


@dataclass
class Settings:
    # Токен бота от @BotFather
    bot_token: str = field(default_factory=lambda: os.getenv("BOT_TOKEN", ""))
    # Telegram ID админов через запятую (узнать свой ID: @userinfobot)
    admin_ids: set[int] = field(default_factory=lambda: _ids(os.getenv("ADMIN_IDS", "")))
    # Публичный https-адрес, по которому открывается Mini App
    webapp_url: str = field(default_factory=_webapp_url)
    # База данных. По умолчанию SQLite-файл рядом с проектом.
    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./testbot.db")
    )
    host: str = field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8080")))
    # Запускать ли Telegram-бота вместе с сервером (0 — только сервер Mini App)
    run_bot: bool = field(default_factory=lambda: os.getenv("RUN_BOT", "1") == "1")
    # Режим разработки: вход в Mini App из обычного браузера без Telegram.
    # НИКОГДА не включайте на рабочем сервере.
    dev_auth: bool = field(default_factory=lambda: os.getenv("DEV_AUTH", "0") == "1")

    # ИИ (Anthropic Claude) для генерации презентаций по теме. Пусто — ИИ-режим выключен.
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    anthropic_model: str = field(default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5"))

    # RAG: эмбеддинги библиотеки (Voyage AI). Пусто — RAG выключен, генерация как раньше.
    voyage_api_key: str = field(default_factory=lambda: os.getenv("VOYAGE_API_KEY", ""))
    voyage_model: str = field(default_factory=lambda: os.getenv("VOYAGE_MODEL", "voyage-3.5-lite"))
    # Размерность векторов (Voyage voyage-3.5-lite: 256/512/1024/2048). 512 — компромисс память/качество.
    embed_dim: int = field(default_factory=lambda: int(os.getenv("EMBED_DIM", "512")))
    # Сколько кусков библиотеки отдавать в контекст генерации.
    rag_top_k: int = field(default_factory=lambda: int(os.getenv("RAG_TOP_K", "6")))
    # Картинки ИЗ КНИГ библиотеки как источник фото для слайдов (вырезаем иллюстрации из PDF,
    # подписываем зрением, ищем по теме). Выключено по умолчанию: включать LIBRARY_FIGURES=1.
    # ВНИМАНИЕ: это копирайтные учебники — включать на усмотрение оператора.
    library_figures_enabled: bool = field(default_factory=lambda: os.getenv("LIBRARY_FIGURES", "0") == "1")
    # Сколько фигур из книги подмешивать в кандидаты на слайд (их финально оценит зрение).
    library_figures_topk: int = field(default_factory=lambda: int(os.getenv("LIBRARY_FIGURES_TOPK", "3")))
    # Когда резать иллюстрации из одобренной книги (режет = тяжело: 1 vision + 1 эмбеддинг на фигуру):
    #   background — сразу в фоне (одобрение не ждёт, книги обрабатываются по одной за раз);
    #   night      — откладывать до ночного часа (под нагрузкой: днём ничего не режем).
    library_figures_mode: str = field(default_factory=lambda: os.getenv("LIBRARY_FIGURES_MODE", "background"))
    # Час (местный, 0–23), в который в режиме night обрабатываются накопившиеся книги.
    library_figures_night_hour: int = field(default_factory=lambda: int(os.getenv("LIBRARY_FIGURES_NIGHT_HOUR", "3")))
    # Фото-этап: защита от зависаний при медленном/мёртвом источнике. Одна генерация не должна
    # занимать минуты и подвешивать Mini App на маленьком сервере.
    #   PHOTO_BUDGET_SEC — общий лимит времени на подбор фото для всей презентации (потом
    #     слайды, что не успели, остаются без фото; логика выбора та же);
    #   PHOTO_DL_TIMEOUT / PHOTO_API_TIMEOUT — таймаут одной загрузки картинки / запроса к источнику.
    photo_budget_sec: int = field(default_factory=lambda: int(os.getenv("PHOTO_BUDGET_SEC", "75")))
    photo_dl_timeout: float = field(default_factory=lambda: float(os.getenv("PHOTO_DL_TIMEOUT", "7")))
    photo_api_timeout: float = field(default_factory=lambda: float(os.getenv("PHOTO_API_TIMEOUT", "8")))
    # Порог косинусной близости: ниже — считаем, что в библиотеке релевантного нет.
    rag_min_score: float = field(default_factory=lambda: float(os.getenv("RAG_MIN_SCORE", "0.45")))
    # Пауза (сек) между запросами при БЭКОФИЛЛЕ. На платном тарифе Voyage лимиты высокие —
    # пейсинг почти не нужен. На бесплатном (3 RPM) поднимите RAG_BACKFILL_PACE=22 в .env.
    rag_backfill_pace: float = field(default_factory=lambda: float(os.getenv("RAG_BACKFILL_PACE", "0.5")))
    # Макс. оценка токенов на один запрос эмбеддингов. Платный Voyage допускает большие запросы;
    # на бесплатном (без карты) выставьте EMBED_MAX_TOKENS_PER_REQ=3000 в .env.
    embed_max_tokens_per_req: int = field(default_factory=lambda: int(os.getenv("EMBED_MAX_TOKENS_PER_REQ", "100000")))

    # Лимиты бесплатного тарифа
    # Сколько запусков теста (для группы) в день на бесплатном тарифе. 0 — без ограничения.
    free_max_sessions_per_day: int = field(default_factory=lambda: int(os.getenv("FREE_MAX_SESSIONS_PER_DAY", "1")))
    free_max_students: int = field(default_factory=lambda: int(os.getenv("FREE_MAX_STUDENTS", "30")))
    # Сколько презентаций в день можно создать (0 — без ограничения). Временно 1.
    free_max_pres_per_day: int = field(default_factory=lambda: int(os.getenv("FREE_MAX_PRES_PER_DAY", "1")))
    # Часовой пояс для границы «дня» (Узбекистан = UTC+5).
    tz_offset_hours: int = field(default_factory=lambda: int(os.getenv("TZ_OFFSET_HOURS", "5")))

    # Сколько генераций (презентация/тест) обрабатывать ОДНОВРЕМЕННО. Остальные ждут в очереди —
    # чтобы при наплыве сервер (1 ГБ) не падал по памяти. Поднимайте при более мощном сервере.
    max_concurrent_gen: int = field(default_factory=lambda: int(os.getenv("MAX_CONCURRENT_GEN", "5")))

    # Папка для файлов электронной библиотеки. По умолчанию — рядом с файлом базы
    # (на хостинге — /var/lib/testroom/library, переживает деплой; локально — ./library).
    library_dir: str = field(default_factory=lambda: _library_dir())

    # Ежедневный бэкап базы: бот присылает копию файлом админам. 0 — выключить.
    backup_enabled: bool = field(default_factory=lambda: os.getenv("BACKUP_ENABLED", "1") == "1")
    # Час локального времени (UTC+tz_offset_hours), когда отправлять бэкап.
    backup_hour: int = field(default_factory=lambda: int(os.getenv("BACKUP_HOUR", "4")))


settings = Settings()
