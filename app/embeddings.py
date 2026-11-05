"""Эмбеддинги для RAG: нарезка текста, запрос векторов у провайдера, упаковка/косинус.

Провайдер — Voyage AI (мультиязычный, ру/уз; бесплатный лимит). Ключ в .env VOYAGE_API_KEY.
Абстракция тонкая: чтобы сменить провайдера, достаточно переписать _embed_remote().
Векторы храним нормализованными (float32 bytes), тогда косинус = скалярное произведение.
"""
from __future__ import annotations

import math
import struct

from .config import settings

VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"


def is_enabled() -> bool:
    """RAG доступен только при наличии ключа эмбеддингов."""
    return bool(settings.voyage_api_key)


# ----------------------------------------------------------------- нарезка текста

def chunk_text(text: str, target_chars: int = 2800, overlap_chars: int = 200) -> list[str]:
    """Режет текст на куски ~1 страница по границам абзацев/предложений, с лёгким нахлёстом.

    target_chars ≈ 2800 (~700–900 токенов). overlap сохраняет контекст на стыках."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    # разбиваем на абзацы, слишком длинные абзацы — на предложения
    import re

    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    units: list[str] = []
    for p in paras:
        if len(p) <= target_chars:
            units.append(p)
        else:
            # длинный абзац → по предложениям, добирая до target
            sents = re.split(r"(?<=[.!?。])\s+", p)
            buf = ""
            for s in sents:
                if buf and len(buf) + len(s) + 1 > target_chars:
                    units.append(buf.strip())
                    buf = s
                else:
                    buf = (buf + " " + s).strip() if buf else s
            if buf.strip():
                units.append(buf.strip())
    # склеиваем мелкие юниты до target_chars
    chunks: list[str] = []
    buf = ""
    for u in units:
        if buf and len(buf) + len(u) + 1 > target_chars:
            chunks.append(buf.strip())
            # нахлёст: хвост предыдущего куска
            tail = buf[-overlap_chars:] if overlap_chars and len(buf) > overlap_chars else ""
            buf = (tail + "\n" + u).strip() if tail else u
        else:
            buf = (buf + "\n" + u).strip() if buf else u
    if buf.strip():
        chunks.append(buf.strip())
    # отбрасываем совсем пустые/мусорные
    return [c for c in chunks if len(c.strip()) >= 30]


# ----------------------------------------------------------------- векторы

def normalize(vec: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / n for x in vec]


def pack(vec: list[float]) -> bytes:
    """float32 bytes (вектор нормализуется перед упаковкой)."""
    v = normalize(vec)
    return struct.pack(f"<{len(v)}f", *v)


def unpack(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob)) if n else []


def dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


# ----------------------------------------------------------------- запрос к провайдеру

async def _embed_remote(texts: list[str], input_type: str, client, max_retries: int = 5) -> list[list[float]]:
    """Один запрос к Voyage с повтором при 429 (rate limit бесплатного тарифа) и 5xx.

    max_retries=1 — «быстрый отказ» (для запроса темы в рантайме, чтобы юзер не ждал)."""
    import asyncio

    payload = {
        "model": settings.voyage_model,
        "input": texts,
        "input_type": input_type,       # "document" | "query" — асимметрия улучшает поиск
        "output_dimension": settings.embed_dim,
        "truncation": True,             # слишком длинный вход Voyage сам укоротит
    }
    headers = {"Authorization": f"Bearer {settings.voyage_api_key}", "Content-Type": "application/json"}
    last = 0
    for attempt in range(max(1, max_retries)):
        r = await client.post(VOYAGE_URL, headers=headers, json=payload, timeout=60)
        if r.status_code == 200:
            data = r.json()
            return [item["embedding"] for item in sorted(data["data"], key=lambda x: x["index"])]
        last = r.status_code
        if r.status_code in (429, 500, 502, 503, 529) and attempt < max_retries - 1:
            # уважаем Retry-After, иначе экспоненциальная пауза 5→10→20→40 c
            try:
                wait = float(r.headers.get("retry-after", "")) or 0
            except ValueError:
                wait = 0
            await asyncio.sleep(min(60.0, wait or 5 * (2 ** attempt)))
            continue
        break
    from .services import ServiceError

    raise ServiceError(f"Эмбеддинги недоступны ({last}).", 502)


async def embed_texts(
    texts: list[str], input_type: str = "document", client=None, max_retries: int = 5, pace: float = 0.0
) -> list[list[float]]:
    """Векторы для списка текстов. Батчит и делает паузу между батчами (бесплатный лимит Voyage).

    input_type: 'document' для кусков библиотеки, 'query' для темы при поиске.
    max_retries: 5 для бэкофилла (дожидаемся), 1 для рантайма (быстрый отказ → фолбэк).
    pace: пауза (сек) ПЕРЕД каждым запросом — для бэкофилла под ~3 запроса/мин Voyage free."""
    import asyncio

    texts = [t if t else " " for t in texts]
    if not texts:
        return []
    if not is_enabled():
        from .services import ServiceError

        raise ServiceError("Эмбеддинги не подключены (VOYAGE_API_KEY).", 403)

    import httpx

    # Батчим по ОЦЕНКЕ токенов (~3 символа/токен), а не по числу входов: бесплатный тариф
    # Voyage режет большие запросы. До 128 входов/запрос и не более maxtok токенов.
    maxtok = max(500, settings.embed_max_tokens_per_req)
    batches: list[list[str]] = []
    cur: list[str] = []
    curtok = 0
    for t in texts:
        est = max(1, len(t) // 3)
        if cur and (curtok + est > maxtok or len(cur) >= 96):
            batches.append(cur)
            cur, curtok = [], 0
        cur.append(t)
        curtok += est
    if cur:
        batches.append(cur)

    own = client is None
    cl = client or httpx.AsyncClient()
    try:
        out: list[list[float]] = []
        for i, batch in enumerate(batches):
            if pace > 0:
                await asyncio.sleep(pace)       # держим темп под rate limit бесплатного тарифа
            elif i:
                await asyncio.sleep(1.0)
            out += await _embed_remote(batch, input_type, cl, max_retries=max_retries)
        return out
    finally:
        if own:
            await cl.aclose()
