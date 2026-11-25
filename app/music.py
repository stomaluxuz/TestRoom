"""Генерация песни (аудио) через fal.ai (оплата по факту, без месячного минимума).

Вся услуга «Песня» завязана на ключ (`settings.song_api_key`): нет ключа —
функция выключена, кнопка скрыта, ничего не списывается.

По умолчанию — модель с вокалом на fal (MiniMax Music). fal использует «очередь»:
POST на queue.fal.run/{model} возвращает status_url/response_url; опрашиваем статус,
по COMPLETED забираем результат и ссылку на аудио. Модель и поля ввода настраиваются
через ENV (SONG_MODEL, SONG_INPUT_JSON), чтобы подогнать под конкретную модель на
живом ключе без правки кода.
"""
from __future__ import annotations

import asyncio
import json
import os

import httpx

from .config import settings
from .services import ServiceError

_POLL_EVERY = 3.0
_POLL_MAX_SEC = 240
_AUDIO_EXT = (".mp3", ".flac", ".wav", ".m4a", ".ogg")


def enabled() -> bool:
    return bool(settings.song_api_key)


def _find_audio_url(obj) -> str | None:
    """Рекурсивно ищем в ответе ссылку на готовый аудиофайл."""
    if isinstance(obj, str):
        low = obj.lower().split("?")[0]
        return obj if (obj.lower().startswith("http") and low.endswith(_AUDIO_EXT)) else None
    if isinstance(obj, dict):
        for key in ("audio_url", "audio", "mp3_url", "url", "file_url"):
            v = obj.get(key)
            if isinstance(v, str) and v.lower().startswith("http"):
                return v
            found = _find_audio_url(v)
            if found:
                return found
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


def _build_input(lyrics: str, style: str) -> dict:
    """Поля ввода модели. По умолчанию — универсальные lyrics/prompt; можно переопределить
    SONG_INPUT_JSON (шаблон с {lyrics}/{style})."""
    tpl = os.getenv("SONG_INPUT_JSON", "").strip()
    if tpl:
        try:
            return json.loads(tpl.replace("{lyrics}", json.dumps(lyrics)[1:-1]).replace("{style}", json.dumps(style)[1:-1]))
        except Exception:
            pass
    body = {"lyrics": lyrics[:3000]}
    body["prompt"] = (style or "pop song").strip()[:200]
    return body


async def make_song(lyrics: str, style: str, title: str) -> tuple[str, bytes]:
    """Озвучить текст песни. Возвращает (имя_файла, mp3_байты).
    Бросает ServiceError при сбое/таймауте (деньги вернёт вызывающий)."""
    if not enabled():
        raise ServiceError("Озвучка песен пока не подключена.", 503)
    headers = {"Authorization": f"{settings.song_auth_scheme} {settings.song_api_key}",
               "Content-Type": "application/json"}
    base = settings.song_base.rstrip("/")
    url = f"{base}/{settings.song_model.strip('/')}"
    body = _build_input(lyrics, style)
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            r = await client.post(url, headers=headers, json=body)
            r.raise_for_status()
            sub = r.json()
        except httpx.HTTPStatusError as e:
            raise ServiceError(f"Сервис песен отклонил запрос ({e.response.status_code}).", 502)
        except Exception as e:
            raise ServiceError(f"Не удалось обратиться к сервису песен: {type(e).__name__}.", 502)

        audio_url = _find_audio_url(sub)
        status_url = sub.get("status_url") if isinstance(sub, dict) else None
        response_url = sub.get("response_url") if isinstance(sub, dict) else None
        waited = 0.0
        while not audio_url and status_url and waited < _POLL_MAX_SEC:
            await asyncio.sleep(_POLL_EVERY)
            waited += _POLL_EVERY
            try:
                st = await client.get(status_url, headers=headers)
                st.raise_for_status()
                status = str(st.json().get("status") or "").upper()
            except Exception:
                continue
            if status in ("FAILED", "ERROR", "CANCELLED"):
                raise ServiceError("Не удалось сгенерировать песню, попробуйте другую тему.", 502)
            if status == "COMPLETED":
                try:
                    res = await client.get(response_url or status_url, headers=headers)
                    res.raise_for_status()
                    audio_url = _find_audio_url(res.json())
                except Exception:
                    pass
                break
        if not audio_url:
            raise ServiceError("Песня слишком долго генерируется — попробуйте позже.", 504)

        try:
            a = await client.get(audio_url, timeout=60)
            a.raise_for_status()
            blob = a.content
        except Exception:
            raise ServiceError("Не удалось скачать готовую песню.", 502)

    if not blob:
        raise ServiceError("Пустой аудиофайл от сервиса песен.", 502)
    safe = "".join(c for c in (title or "song") if c.isalnum() or c in " _-").strip()[:50] or "song"
    return f"{safe}.mp3", blob
