"""Подбор иллюстраций для слайдов.

Было: одна случайная картинка из Wikimedia Commons по короткому запросу.
Стало: собираем НЕСКОЛЬКО кандидатов из нескольких бесплатных источников
(по сфере предмета), затем Claude ЗРЕНИЕМ выбирает самые релевантные теме слайда,
нерелевантные отбрасывает. Лицензии — только переиспользуемые (CC / public domain),
т.к. презентации раздаются студентам.

Источники:
  • Wikimedia Commons — общая база (CC/PD), без ключа;
  • Open-i (openi.nlm.nih.gov) — медицинские изображения из открытых научных статей PMC;
  • Openverse (api.openverse.org) — агрегатор CC-картинок (история, искусство, общее), без ключа.

Публичная точка входа — illustrate_slides(): заполняет sl["images"] (список bytes).
"""
from __future__ import annotations

import asyncio
import io
import logging

from .config import settings

log = logging.getLogger("testroom.photos")

UA = {
    "User-Agent": "TestRoomBot/1.0 (https://t.me/testroom_ai; aat.allserver@gmail.com) python-httpx",
    "Accept": "application/json",
}

# Ключевые слова, по которым тему относим к медицине (ru / en / lat).
_MED_HINTS = (
    "анатом", "физиолог", "болезн", "заболев", "диагноз", "симптом", "синдром",
    "лечени", "терап", "хирург", "стоматолог", "зуб", "кари", "пародонт", "кост", "мышц",
    "сердц", "лёгк", "легк", "печен", "почк", "желуд", "кишеч", "кров", "сосуд", "нерв",
    "мозг", "клетк", "ткан", "орган", "вирус", "бактери", "инфекц", "иммун", "гормон",
    "фармаколог", "лекарств", "препарат", "микроб", "патолог", "онколог", "опухол",
    "anatomy", "physiolog", "disease", "clinical", "medical", "medicine", "surgery",
    "dental", "tooth", "teeth", "cardiac", "pulmon", "hepat", "renal", "neuro", "cell",
    "tissue", "bacteria", "virus", "patholog", "tumor", "tumour", "muscle", "bone",
)

# Гуманитарные/исторические — для них лучше Openverse (искусство, архивы, музеи).
_HUM_HINTS = (
    "истор", "литератур", "искусств", "культур", "философ", "религ", "язык", "лингвист",
    "эконом", "политик", "обществ", "социолог", "географ", "археолог", "музей", "картин",
    "живопис", "архитект", "music", "history", "literature", "art", "culture", "philosoph",
    "religion", "language", "econom", "politic", "society", "geography", "archaeolog",
    "painting", "architecture", "museum",
)


def detect_domain(text: str) -> str:
    """Грубо определяем сферу темы: 'medical' | 'humanities' | 'general'."""
    low = (text or "").lower()
    med = sum(1 for h in _MED_HINTS if h in low)
    hum = sum(1 for h in _HUM_HINTS if h in low)
    if med and med >= hum:
        return "medical"
    if hum:
        return "humanities"
    return "general"


def _variants(query: str) -> list[str]:
    """Полный запрос + всё более короткие (длинный часто даёт 0 результатов)."""
    query = " ".join((query or "").split())
    if not query:
        return []
    words = query.split()
    out = [query]
    for n in (4, 3, 2):
        v = " ".join(words[:n])
        if v and v not in out:
            out.append(v)
    return out


# ------------------------------------------------------------------ источники

async def _wikimedia(query: str, client, limit: int = 8) -> list[dict]:
    API = "https://commons.wikimedia.org/w/api.php"
    for q in _variants(query):
        params = {
            "action": "query", "format": "json", "generator": "search",
            "gsrsearch": f"{q} filetype:bitmap", "gsrnamespace": "6",
            "gsrlimit": str(limit), "prop": "imageinfo", "iiprop": "url|mime",
            "iiurlwidth": "900",
        }
        try:
            r = await client.get(API, params=params, headers=UA, timeout=settings.photo_api_timeout)
            pages = (r.json().get("query") or {}).get("pages") or {}
        except Exception:
            continue
        out = []
        for p in sorted(pages.values(), key=lambda x: x.get("index", 999)):
            info = (p.get("imageinfo") or [{}])[0]
            url = info.get("thumburl") or info.get("url")
            if url and info.get("mime", "") in ("image/jpeg", "image/png"):
                out.append({"url": url, "source": "Wikimedia Commons"})
        if out:
            return out[:limit]
    return []


async def _openi(query: str, client, limit: int = 8) -> list[dict]:
    """Медицинские изображения из открытых статей PMC (NLM, можно переиспользовать)."""
    API = "https://openi.nlm.nih.gov/api/search"
    base = "https://openi.nlm.nih.gov"
    for q in _variants(query):
        params = {"query": q, "it": "p,ph,x", "m": "1", "n": str(limit)}
        try:
            r = await client.get(API, params=params, headers=UA, timeout=settings.photo_api_timeout)
            data = r.json()
        except Exception:
            continue
        out = []
        for item in (data.get("list") or [])[:limit]:
            img = item.get("imgLarge") or item.get("imgGrid") or item.get("imgThumb")
            if img:
                url = img if img.startswith("http") else base + img
                out.append({"url": url, "source": "Open-i (NLM)"})
        if out:
            return out[:limit]
    return []


async def _openverse(query: str, client, limit: int = 8) -> list[dict]:
    """CC-картинки (история, искусство, общее). license_type: разрешено коммерч. и модификация."""
    API = "https://api.openverse.org/v1/images/"
    for q in _variants(query):
        params = {
            "q": q, "page_size": str(limit),
            "license_type": "commercial,modification",  # можно раздавать и править
            "mature": "false",
        }
        try:
            r = await client.get(API, params=params, headers=UA, timeout=settings.photo_api_timeout)
            data = r.json()
        except Exception:
            continue
        out = []
        for item in (data.get("results") or [])[:limit]:
            url = item.get("thumbnail") or item.get("url")
            if url:
                out.append({"url": url, "source": "Openverse"})
        if out:
            return out[:limit]
    return []


# Порядок важен: первый источник профильный. Перечислены ВСЕ источники (как фолбэк),
# опрашиваем по порядку, пока не наберём достаточно кандидатов — чтобы фото было на каждом слайде.
# Медицина: Wikimedia (чистые анатомические фото/схемы) → Open-i (снимки из статей) → Openverse.
# История/общее: Wikimedia (памятники, бюсты, портреты) → Openverse → Open-i.
_SOURCES = {
    "medical": (_wikimedia, _openi, _openverse),
    "humanities": (_wikimedia, _openverse, _openi),
    "general": (_wikimedia, _openverse, _openi),
}

# Профиль фото ПОД ПРЕДМЕТ: какие источники опрашивать первыми и каким англ. термином уточнить
# запрос, чтобы картинки были «по предмету» (реальные препараты/снимки, а не скучные стоки) и
# реже пропускались. Open-i (мед-статьи PMC) даёт клинические фото/гистологию/макропрепараты —
# для патанатомии/гистологии/хирургии ставим его первым. Термин добавляется В КОНЕЦ запроса
# (в коротких вариантах _variants он отбрасывается первым — мягкий фолбэк).
_PHOTO_SUBJECTS = [
    (("патолог", "патанатом", "некроз", "дистроф", "атроф", "гиперплаз", "метаплаз", "дисплаз",
      "воспал", "инфаркт", "тромб", "эмбол", "опухол", "неоплаз", "карцином", "сарком", "гранул",
      "амилоид", "склероз", "фиброз"),
     "histopathology specimen", (_openi, _wikimedia, _openverse)),
    (("гистолог", "клетк", "ткан", "эпители", "микроскоп", "цитолог", "органелл", "эмбриолог"),
     "histology micrograph", (_openi, _wikimedia, _openverse)),
    (("хирург", "остеомиел", "перелом", "вывих", "имплант", "операц", "флегмон", "абсцесс",
      "резекц", "секвестр", "лоскут", "одонтоген", "периостит", "альвеолит"),
     "oral surgery clinical", (_openi, _wikimedia, _openverse)),
    (("кариес", "пульпит", "периодонтит", "эндодонт", "пломб", "пародонт", "стоматолог", "зуб",
      "эмал", "дентин", "гингивит"),
     "dentistry tooth clinical", (_openi, _wikimedia, _openverse)),
    (("ортопед", "коронк", "протез", "мостовид", "вкладк", "винир", "брекет", "ортодонт", "прикус"),
     "dental prosthesis", (_wikimedia, _openi, _openverse)),
    (("анатом", "мышц", "сосуд", "нерв", "сустав", "кост", "череп", "связк", "скелет"),
     "human anatomy", (_wikimedia, _openi, _openverse)),
    (("фармаколог", "препарат", "лекарств", "доза", "антибиотик", "анестетик", "анальгетик"),
     "pharmacology medicine", (_wikimedia, _openverse, _openi)),
]


def detect_photo_subject(text: str):
    """По словам в теме → (англ. уточнение запроса, порядок источников). Нет совпадений → (None, None)."""
    low = " ".join((text or "").lower().split())
    best, score = (None, None), 0
    for kws, hint, funcs in _PHOTO_SUBJECTS:
        c = sum(1 for w in kws if w in low)
        if c > score:
            best, score = (hint, funcs), c
    return best


async def _download(url: str, client) -> bytes | None:
    try:
        r = await client.get(url, headers=UA, timeout=settings.photo_dl_timeout)
        if r.status_code == 200 and r.content and len(r.content) > 500:
            return r.content
    except Exception:
        return None
    return None


def _thumb_and_hash(data: bytes, px: int = 256) -> tuple[str | None, int | None]:
    """(base64 JPEG для зрения Claude, aHash для отсева дублей) или (None, None), если не картинка."""
    try:
        import base64

        from PIL import Image

        im = Image.open(io.BytesIO(data))
        # aHash: 8x8 в оттенках серого → 64-битный отпечаток (ловит одинаковые/похожие фото)
        g = im.convert("L").resize((8, 8))
        pxs = list(g.getdata())
        avg = (sum(pxs) / len(pxs)) if pxs else 0
        ah = 0
        for i, p in enumerate(pxs):
            if p >= avg:
                ah |= (1 << i)
        rgb = im.convert("RGB")
        rgb.thumbnail((px, px))
        buf = io.BytesIO()
        rgb.save(buf, format="JPEG", quality=60)
        return base64.b64encode(buf.getvalue()).decode("ascii"), ah
    except Exception:
        return None, None


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


async def gather_candidates(query: str, domain: str, client, limit: int = 6,
                            hint: str | None = None, source_funcs=None) -> list[dict]:
    """Собирает кандидатов из источников сферы, качает байты, готовит превью для зрения.

    hint — англ. уточнение запроса по предмету (в конец); source_funcs — порядок источников
    под предмет (клинические вперёд). Возвращает [{url, source, data, vb64}] — до limit штук."""
    funcs = source_funcs or _SOURCES.get(domain, _SOURCES["general"])

    async def _collect(q: str, seen_url: set, seen_hash: list) -> list[dict]:
        """Опрашивает источники и ЧЕРЕДУЕТ их (round-robin) — чтобы зрению досталась разнообразная
        выборка (клинические препараты + чистые фото), а не 6 однотипных из одного источника.
        Качает, отсеивает дубли/не-картинки. Возвращает валидные, до limit штук."""
        per: list[list[dict]] = []
        for fn in funcs:
            try:
                per.append(await fn(q, client, limit=limit))
            except Exception:
                per.append([])
            if sum(len(x) for x in per) >= limit * 2 and len(per) >= 2:
                break  # из двух источников уже вдоволь — медленный третий не дёргаем
        ordered: list[dict] = []
        for i in range(limit):
            for lst in per:
                if i < len(lst):
                    ordered.append(lst[i])
        uniq = []
        for c in ordered:
            if c["url"] not in seen_url:
                seen_url.add(c["url"]); uniq.append(c)
        uniq = uniq[: limit * 2]
        datas = await asyncio.gather(*(_download(c["url"], client) for c in uniq), return_exceptions=True)
        out: list[dict] = []
        for c, d in zip(uniq, datas):
            if isinstance(d, bytes) and d:
                # Pillow-декод/уменьшение — CPU; в поток, чтобы не блокировать loop на пачке фото
                vb, ah = await asyncio.to_thread(_thumb_and_hash, d)
                if not vb:
                    continue
                if ah is not None and any(_hamming(ah, h) <= 6 for h in seen_hash):
                    continue  # одинаковое/похожее фото уже есть
                if ah is not None:
                    seen_hash.append(ah)
                out.append({**c, "data": d, "vb64": vb, "ah": ah})
            if len(out) >= limit:
                break
        return out

    seen_url: set = set()
    seen_hash: list = []
    # основной запрос — с уточнением по предмету; если набралось мало, ДОБИРАЕМ обычным запросом
    # (без уточнения) — чтобы меньше было слайдов без фото. Платный vision-вызов по-прежнему ОДИН.
    out = await _collect(f"{query} {hint}".strip() if hint else query, seen_url, seen_hash)
    if hint and len(out) < limit:
        out += (await _collect(query, seen_url, seen_hash))[: limit - len(out)]
    return out


async def illustrate_slides(slides: list[dict], domain: str, client, *, max_per_slide: int = 1) -> None:
    """Для слайдов с запросом img подбирает картинки и кладёт их в sl['images'] (list[bytes]).

    Выбор лучшей — зрением Claude (choose_slide_images). Параллельно, но с ограничением,
    чтобы не перегружать API и 1 ГБ памяти сервера."""
    from .ai import choose_slide_images

    targets = [sl for sl in slides if sl.get("img")]
    if not targets:
        return
    # определяем предмет по всей презентации → клинические источники вперёд + уточнение запроса,
    # чтобы фото были по предмету (не скучные) и реже пропускались
    hint, funcs = detect_photo_subject(
        " ".join((sl.get("title") or "") + " " + (sl.get("img") or "") for sl in targets))
    # обрабатываем слайды параллельно — фото главный тормоз; очередь генераций (limits) ограничивает
    # общее число одновременных генераций, поэтому тут можно взять побольше
    sem = asyncio.Semaphore(min(10, len(targets)))

    async def one(sl: dict) -> None:
        async with sem:
            cands = await gather_candidates(sl["img"], domain, client, limit=6,
                                            hint=hint, source_funcs=funcs)
            # иллюстрации из книг библиотеки (если включён флаг) — по теме слайда; идут впереди,
            # финально их, как и веб-фото, оценивает зрение (не по теме — отбросит)
            try:
                from . import services as _svc
                figs = await _svc.figure_candidates_for(sl.get("title") or sl.get("img") or "")
                cands = figs + cands
            except Exception:
                pass
            if not cands:
                sl["_approved"] = []
                return
            vb = [c["vb64"] for c in cands if c.get("vb64")]
            idx_map = [i for i, c in enumerate(cands) if c.get("vb64")]
            try:
                # зрение возвращает ВСЕ подходящие по рангу (а не только лучшее)
                chosen = await choose_slide_images(
                    sl.get("title") or "", sl.get("bullets") or [], vb, want=max_per_slide
                )
                picked = [idx_map[i] for i in chosen if 0 <= i < len(idx_map)]
            except Exception:
                picked = idx_map[:2]  # зрение недоступно — первые кандидаты как запас
            # picked ПУСТОЙ = зрение забраковало всё (не по теме) → слайд без фото (не «собака»).
            sl["_approved"] = [(cands[i]["data"], cands[i].get("ah")) for i in picked]

    # Общий лимит времени на фото-этап: медленный/мёртвый источник не должен растягивать
    # генерацию на минуты и подвешивать Mini App. По истечении бюджета слайды, что не успели,
    # просто останутся без фото — логика ВЫБОРА картинок при этом не меняется.
    try:
        await asyncio.wait_for(
            asyncio.gather(*(one(sl) for sl in targets), return_exceptions=True),
            timeout=max(15, settings.photo_budget_sec),
        )
    except asyncio.TimeoutError:
        log.warning("фото-этап прерван по бюджету %sс (слайдов=%s)", settings.photo_budget_sec, len(targets))

    # Распределяем по слайдам БЕЗ повторов: каждый слайд берёт свои лучшие одобренные фото,
    # пропуская те, что уже стоят на других слайдах (если лучшее занято — берёт следующее своё).
    used: list[int] = []
    for sl in targets:
        imgs = []
        for data, ah in sl.pop("_approved", []):
            if len(imgs) >= max_per_slide:
                break
            if ah is not None and any(_hamming(ah, h) <= 6 for h in used):
                continue  # это изображение уже на другом слайде — берём следующее
            if ah is not None:
                used.append(ah)
            imgs.append(data)
        if imgs:
            sl["images"] = imgs
