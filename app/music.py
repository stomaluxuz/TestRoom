"""Генерация песни (аудио) через Mureka API.

Вся услуга «Песня» завязана на ключ Mureka: если ключа нет (`settings.mureka_api_key`
пуст) — функция выключена, кнопка в приложении/боте скрыта, ничего не списывается.

ВАЖНО: точные пути/поля Mureka API здесь заданы по документации (api.mureka.ai,
Bearer-авторизация, lyrics→song, модель «auto», prompt=стиль, асинхронно с опросом).
Домен документации был недоступен из песочницы при разработке, поэтому пути вынесены в
ENV (MUREKA_GEN_PATH / MUREKA_QUERY_PATH) — если реальный ключ покажет другие эндпоинты,
их можно поправить переменными окружения без правки кода.
"""
from __future__ import annotations

import asyncio
import os

import httpx

from .config import settings
from .services import ServiceError

_GEN_PATH = os.getenv("MUREKA_GEN_PATH", "/v1/song/generate")
_QUERY_PATH = os.getenv("MUREKA_QUERY_PATH", "/v1/song/query")  # + /{id}
_POLL_EVERY = 3.0
_POLL_MAX_SEC = 240
_AUDIO_EXT = (".mp3", ".flac", ".wav", ".m4a", ".ogg")


def enabled() -> bool:
    return bool(settings.mureka_api_key)


def _find_audio_url(obj) -> str | None:
    """Рекурсивно ищем в ответе ссылку на готовый аудиофайл."""
    if isinstance(obj, str):
        low = obj.lower()
        if low.startswith("http") and (low.split("?")[0].endswith(_AUDIO_EXT)):
            return obj
        return None
    if isinstance(obj, dict):
        # частые имена полей со ссылкой на аудио
        for key in ("mp3_url", "audio_url", "flac_url", "url", "audio"):
            v = obj.get(key)
            if isinstance(v, str) and v.lower().startswith("http"):
                return v
        for v in obj.values():
            found = _find_audio_url(v)
            if found:
                return found
        return None
    if isinstance(obj, list):
        for v in obj:
            found = _find_audio_url(v)
            if found:
                return found
    return None


def _status_of(data: dict) -> str:
    return str(data.get("status") or data.get("state") or "").lower()


async def make_song(lyrics: str, style: str, title: str) -> tuple[str, bytes]:
    """Озвучить текст песни через Mureka. Возвращает (имя_файла, mp3_байты).
    Бросает ServiceError при сбое/таймауте (деньги вернёт вызывающий)."""
    if not enabled():
        raise ServiceError("Озвучка песен пока не подключена.", 503)
    headers = {"Authorization": f"Bearer {settings.mureka_api_key}", "Content-Type": "application/json"}
    body = {"model": settings.mureka_model, "lyrics": lyrics[:6000]}
    if style:
        body["prompt"] = style[:300]
    base = settings.mureka_base.rstrip("/")
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            r = await client.post(base + _GEN_PATH, headers=headers, json=body)
            r.raise_for_status()
            job = r.json()
        except httpx.HTTPStatusError as e:
            raise ServiceError(f"Mureka отклонила запрос ({e.response.status_code}).", 502)
        except Exception as e:
            raise ServiceError(f"Не удалось обратиться к Mureka: {type(e).__name__}.", 502)

        # Иногда результат приходит сразу; иначе — опрашиваем по id.
        audio_url = _find_audio_url(job)
        job_id = str(job.get("id") or job.get("task_id") or job.get("job_id") or "")
        waited = 0.0
        while not audio_url and job_id and waited < _POLL_MAX_SEC:
            await asyncio.sleep(_POLL_EVERY)
            waited += _POLL_EVERY
            try:
                q = await client.get(f"{base}{_QUERY_PATH}/{job_id}", headers=headers)
                q.raise_for_status()
                data = q.json()
            except Exception:
                continue
            if _status_of(data) in ("failed", "error", "cancelled"):
                raise ServiceError("Mureka не смогла сгенерировать песню, попробуйте другую тему.", 502)
            audio_url = _find_audio_url(data)
        if not audio_url:
            raise ServiceError("Песня слишком долго генерируется — попробуйте позже.", 504)

        try:
            a = await client.get(audio_url, timeout=60)
            a.raise_for_status()
            blob = a.content
        except Exception:
            raise ServiceError("Не удалось скачать готовую песню.", 502)

    if not blob:
        raise ServiceError("Пустой аудиофайл от Mureka.", 502)
    safe = "".join(c for c in (title or "song") if c.isalnum() or c in " _-").strip()[:50] or "song"
    return f"{safe}.mp3", blob
