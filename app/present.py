"""Генерация презентации (.pptx) из простого текста.

Формат текста:
  • Первые строки до первого «#» — титульный слайд: 1-я строка = заголовок,
    2-я (если есть) = подзаголовок.
  • Строка, начинающаяся с «#», открывает новый слайд (текст после # — его заголовок).
  • Остальные строки под слайдом — пункты (можно с «-», «•», «*» в начале).

Пример см. в PRESENT_EXAMPLE.
"""
from __future__ import annotations

import io
import os

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.util import Inches, Pt

# Цвета оформления
_DARK = RGBColor(0x1A, 0x2B, 0x45)   # тёмно-синий — заголовки
_GRAY = RGBColor(0x55, 0x5B, 0x66)   # серый — подзаголовок
_ACCENT = RGBColor(0x24, 0x81, 0xCC)  # акцент — линия/полоса
_BODY = RGBColor(0x22, 0x26, 0x2E)   # основной текст

# Палитра карточек под пункты: мягкий фон + цветная рамка (циклично)
_CARD_TINTS = [
    RGBColor(0xE8, 0xF0, 0xFE), RGBColor(0xE6, 0xF4, 0xEA), RGBColor(0xFD, 0xF0, 0xE1),
    RGBColor(0xF1, 0xE9, 0xFB), RGBColor(0xE2, 0xF5, 0xF3), RGBColor(0xFC, 0xE9, 0xEC),
]
_CARD_ACCENTS = [
    RGBColor(0x24, 0x81, 0xCC), RGBColor(0x2E, 0x9E, 0x5B), RGBColor(0xD6, 0x8A, 0x1E),
    RGBColor(0x7A, 0x4F, 0xC0), RGBColor(0x1C, 0x9C, 0x92), RGBColor(0xCC, 0x3F, 0x5B),
]


# Стиль «Современный яркий»: цветная шапка + воздушные карточки с акцентной полосой слева
_HEADER = RGBColor(0x1F, 0x4E, 0xA8)   # насыщенный синий — шапка слайда
_SOFT = RGBColor(0xF2, 0xF5, 0xFA)     # мягкий фон карточек
_WHITE = RGBColor(0xFF, 0xFF, 0xFF)


def _fit_font(text: str, width_in: float, height_in: float, lo: int = 10, hi: int = 18) -> int:
    """Подбирает размер шрифта, при котором текст ГАРАНТИРОВАННО влезает в карточку
    (оценка по числу строк) — чтобы ничего не вылезало за рамку."""
    import math

    usable_w = max(1.0, width_in - 0.55)   # минус полоска слева и поля
    for fs in range(hi, lo - 1, -1):
        char_w = (fs * 0.50) / 72.0        # средняя ширина символа
        cpl = max(8, int(usable_w / char_w))
        lines = max(1, math.ceil(len(text) / cpl))
        need = lines * (fs * 1.26) / 72.0 + 0.1   # высота строк + вертикальные поля
        if need <= height_in:
            return fs
    return lo


def _render_cards_modern(slide, left: float, top: float, width: float, height: float, bullets: list[str]) -> None:
    """Воздушные цветные карточки (пастель по кругу) с цветной полоской слева, авто-размер шрифта."""
    n = max(1, len(bullets))
    gap = 0.16
    card_h = max(0.42, (height - gap * (n - 1)) / n)
    y = top
    for i, b in enumerate(bullets):
        tint = _CARD_TINTS[i % len(_CARD_TINTS)]
        acc = _CARD_ACCENTS[i % len(_CARD_ACCENTS)]
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                      Inches(left), Inches(y), Inches(width), Inches(card_h))
        card.fill.solid(); card.fill.fore_color.rgb = tint
        card.line.fill.background()
        card.shadow.inherit = False
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(left), Inches(y), Inches(0.1), Inches(card_h))
        bar.fill.solid(); bar.fill.fore_color.rgb = acc
        bar.line.fill.background(); bar.shadow.inherit = False
        tf = card.text_frame
        tf.word_wrap = True
        tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        tf.margin_left = Inches(0.3); tf.margin_right = Inches(0.16)
        tf.margin_top = Inches(0.05); tf.margin_bottom = Inches(0.05)
        p = tf.paragraphs[0]
        r = p.add_run(); r.text = b
        r.font.size = Pt(_fit_font(b, width, card_h)); r.font.color.rgb = _BODY
        y += card_h + gap


def _render_bullets(slide, left: float, top: float, width: float, height: float, bullets: list[str]) -> None:
    """Чистый список пунктов (без плашек-рамок): цветной маркер «•» + тёмный текст, авто-ужатие."""
    tb = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE  # если не влезает — PowerPoint ужмёт
    n = max(1, len(bullets))
    size = 20 if n <= 4 else (18 if n <= 5 else (16 if n <= 7 else 14))
    for i, b in enumerate(bullets):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(10)
        try:
            p.line_spacing = 1.05
        except Exception:
            pass
        r1 = p.add_run(); r1.text = "•  "
        r1.font.size = Pt(size); r1.font.bold = True; r1.font.color.rgb = _ACCENT
        r2 = p.add_run(); r2.text = b
        r2.font.size = Pt(size); r2.font.color.rgb = _BODY


def _render_cards(slide, left: float, top: float, width: float, height: float, bullets: list[str]) -> None:
    """Рисует каждый пункт отдельной скруглённой цветной карточкой, стопкой по вертикали."""
    n = max(1, len(bullets))
    gap = 0.12
    card_h = max(0.4, (height - gap * (n - 1)) / n)
    y = top
    for i, b in enumerate(bullets):
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                      Inches(left), Inches(y), Inches(width), Inches(card_h))
        card.fill.solid(); card.fill.fore_color.rgb = _CARD_TINTS[i % len(_CARD_TINTS)]
        card.line.color.rgb = _CARD_ACCENTS[i % len(_CARD_ACCENTS)]
        card.line.width = Pt(1.25)
        card.shadow.inherit = False  # без тяжёлой тени
        tf = card.text_frame
        tf.word_wrap = True
        tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE  # ужать текст, если не влезает
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        tf.margin_left = Inches(0.2); tf.margin_right = Inches(0.14)
        tf.margin_top = Inches(0.04); tf.margin_bottom = Inches(0.04)
        p = tf.paragraphs[0]
        r = p.add_run(); r.text = b
        r.font.size = Pt(_fit_font(b, width, card_h)); r.font.color.rgb = _BODY
        y += card_h + gap

PRESENT_EXAMPLE = (
    "Анатомия сердца\n"
    "Лекция для 2 курса\n"
    "\n"
    "# Строение сердца\n"
    "- 4 камеры: 2 предсердия и 2 желудочка\n"
    "- Разделено перегородкой на левую и правую половины\n"
    "\n"
    "# Клапаны сердца\n"
    "- Митральный и трёхстворчатый\n"
    "- Аортальный и лёгочный\n"
    "\n"
    "# Круги кровообращения\n"
    "- Большой: левый желудочек → тело\n"
    "- Малый: правый желудочек → лёгкие"
)

_BULLET_CHARS = "-•*–—·"


def _clean(line: str) -> str:
    line = line.strip()
    while line and line[0] in _BULLET_CHARS:
        line = line[1:].strip()
    return line


def parse(text: str) -> tuple[str, str, list[dict]]:
    """Возвращает (заголовок, подзаголовок, [{'title': ..., 'bullets': [...]}, ...])."""
    title, subtitle = "", ""
    slides: list[dict] = []
    intro: list[str] = []  # строки до первого «#»
    cur: dict | None = None
    for raw in (text or "").splitlines():
        s = raw.strip()
        if s.startswith("#"):
            cur = {"title": s.lstrip("#").strip(), "bullets": []}
            slides.append(cur)
        elif cur is not None:
            if not s:
                continue
            if s.lower().startswith("img:"):  # запрос фото для слайда
                cur["img"] = s[4:].strip()
            else:
                cur["bullets"].append(_clean(raw))
        else:
            if s:
                intro.append(s)
    if intro:
        title = intro[0]
        subtitle = " ".join(intro[1:]) if len(intro) > 1 else ""
    # Нет ни одного «#»: соберём один слайд из вступления (кроме заголовка).
    if not slides and len(intro) > 1:
        slides.append({"title": title, "bullets": intro[1:]})
        subtitle = ""
    return title or "Презентация", subtitle, slides


PW, PH = 13.333, 7.5  # размеры слайда (16:9), дюймы


# Фоновая картинка слайдов (светлый мед-фон). Лежит в пакете, уезжает с деплоем.
_BG_PATH = os.path.join(os.path.dirname(__file__), "assets", "bg.jpg")


def _add_bg(slide) -> None:
    """Кладёт фоновую картинку во весь слайд ПЕРВОЙ (под всем содержимым). Нет файла — пропускаем."""
    if not os.path.exists(_BG_PATH):
        return
    try:
        slide.shapes.add_picture(_BG_PATH, Inches(0), Inches(0), width=Inches(PW), height=Inches(PH))
    except Exception:
        pass


def _textbox(slide, left, top, width, height):
    tb = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tf = tb.text_frame
    tf.word_wrap = True
    return tb, tf


def _set(p, text, size, color, bold=False, align=PP_ALIGN.LEFT):
    p.alignment = align
    r = p.add_run()
    r.text = text
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.color.rgb = color


def _assemble(title: str, subtitle: str, slides: list[dict], sources: list[str] | None = None,
              style: str = "modern") -> tuple[str, bytes]:
    prs = Presentation()
    prs.slide_width = Inches(PW)   # широкоформат 16:9
    prs.slide_height = Inches(PH)
    blank = prs.slide_layouts[6]   # пустой макет — размещаем всё сами, без наездов
    sources = [s for s in (sources or []) if s]

    # ---- титульный слайд ----
    s0 = prs.slides.add_slide(blank)
    # _add_bg(s0)  # фон временно отключён — вернём, когда определимся со стилем
    band = s0.shapes.add_shape(1, Inches(0), Inches(3.4), Inches(PW), Inches(0.06))  # акцентная полоса
    band.fill.solid(); band.fill.fore_color.rgb = _ACCENT; band.line.fill.background()
    # размер заголовка подстраиваем под длину, чтобы не вылезал
    tlen = len(title)
    tsize = 40 if tlen <= 45 else (32 if tlen <= 90 else 26)
    _, tf = _textbox(s0, 0.9, 1.1, PW - 1.8, 2.2)
    tf.vertical_anchor = MSO_ANCHOR.BOTTOM
    _set(tf.paragraphs[0], title, tsize, _DARK, bold=True, align=PP_ALIGN.CENTER)
    if subtitle:
        ssize = 22 if len(subtitle) <= 70 else 16
        _, tf2 = _textbox(s0, 0.9, 3.65, PW - 1.8, 2.0)
        tf2.vertical_anchor = MSO_ANCHOR.TOP
        _set(tf2.paragraphs[0], subtitle, ssize, _GRAY, align=PP_ALIGN.CENTER)
    # строка источника на титульном: по каким материалам библиотеки сделано
    if sources:
        src_line = "📚 По материалам: " + "; ".join(sources[:3])
        _, tfs = _textbox(s0, 0.9, 5.9, PW - 1.8, 1.3)
        tfs.vertical_anchor = MSO_ANCHOR.TOP
        _set(tfs.paragraphs[0], src_line, 13, _GRAY, align=PP_ALIGN.CENTER)

    # ---- содержательные слайды ----
    for sl in slides:
        slide = prs.slides.add_slide(blank)
        # _add_bg(slide)  # фон временно отключён — вернём, когда определимся со стилем
        images = [b for b in (sl.get("images") or []) if b]
        if not images and sl.get("img_bytes"):
            images = [sl["img_bytes"]]
        body_w = 6.9 if images else (PW - 1.2)
        bullets = [b for b in (sl.get("bullets") or []) if b.strip()] or [" "]

        if style == "modern":
            # цветная шапка во всю ширину + крупный белый заголовок
            band = slide.shapes.add_shape(1, Inches(0), Inches(0), Inches(PW), Inches(1.25))
            band.fill.solid(); band.fill.fore_color.rgb = _HEADER
            band.line.fill.background(); band.shadow.inherit = False
            _, tft = _textbox(slide, 0.6, 0.0, PW - 1.2, 1.25)
            tft.vertical_anchor = MSO_ANCHOR.MIDDLE
            _set(tft.paragraphs[0], sl.get("title") or " ", 26, _WHITE, bold=True)
            # пункты — чистым списком (без цветных плашек поверх текста)
            _render_bullets(slide, 0.6, 1.55, body_w, 5.25, bullets)
        else:  # "cards" — цветные плашки под пункты
            _, tft = _textbox(slide, 0.6, 0.35, PW - 1.2, 1.0)
            tft.vertical_anchor = MSO_ANCHOR.MIDDLE
            _set(tft.paragraphs[0], sl.get("title") or " ", 28, _DARK, bold=True)
            line = slide.shapes.add_shape(1, Inches(0.6), Inches(1.4), Inches(3.2), Inches(0.05))
            line.fill.solid(); line.fill.fore_color.rgb = _ACCENT; line.line.fill.background()
            _render_cards(slide, 0.6, 1.7, body_w, 5.1, bullets)

        # правая колонка под 1–2 фото: одно крупное или два в стопку
        left, box_w = 7.9, 4.9
        boxes = [(1.7, 5.2)] if len(images) <= 1 else [(1.7, 2.5), (4.4, 2.5)]
        for img, (top, box_h) in zip(images, boxes):
            try:
                pic = slide.shapes.add_picture(io.BytesIO(img), Inches(left), Inches(top), width=Inches(box_w))
                if pic.height > Inches(box_h):  # высокое фото — ужимаем по высоте
                    scale = Inches(box_h) / pic.height
                    pic.width = int(pic.width * scale)
                    pic.height = int(Inches(box_h))
                pic.left = int(Inches(left) + (Inches(box_w) - pic.width) / 2)      # центр по X
                pic.top = int(Inches(top) + (Inches(box_h) - pic.height) / 2)       # центр по Y
            except Exception:
                pass

        # сноска-источник внизу слайда (по каким материалам библиотеки)
        if sources:
            foot = "📚 " + "; ".join(sources[:2])
            _, tff = _textbox(slide, 0.6, PH - 0.5, PW - 1.2, 0.4)
            _set(tff.paragraphs[0], foot[:120], 10, _GRAY)

    buf = io.BytesIO()
    prs.save(buf)
    safe = "".join(ch for ch in title if ch.isalnum() or ch in " -_").strip() or "presentation"
    return f"{safe[:50]}.pptx", buf.getvalue()


def _need_slides(text: str):
    title, subtitle, slides = parse(text)
    if not slides:
        from .services import ServiceError

        raise ServiceError(
            "Не разобрал ни одного слайда. Отправьте заголовок, затем слайды через «#». "
            "Посмотрите пример: /present_example"
        )
    return title, subtitle, slides


def build_pptx(text: str, *, style: str = "modern") -> tuple[str, bytes]:
    """Без фото (режим «из текста»). Оформление — тематическое (цвет авто по теме + бренд)."""
    from . import themes

    title, subtitle, slides = _need_slides(text)
    return themes.assemble_themed(title, subtitle, slides)


def build_test_docx(title: str, questions: list[dict]) -> tuple[str, bytes]:
    """Собирает тест в Word (.docx) в «буквенном» формате: правильный помечен звёздочкой."""
    from docx import Document

    doc = Document()
    doc.add_heading(title or "Тест", level=1)
    for i, q in enumerate(questions, 1):
        doc.add_paragraph(f"{i}. {q['text']}")
        for j, opt in enumerate(q["options"]):
            mark = "*" if j == q["correct"] else ""
            doc.add_paragraph(f"{mark}{chr(65 + j)}) {opt}")
        doc.add_paragraph("")
    buf = io.BytesIO()
    doc.save(buf)
    safe = "".join(ch for ch in (title or "test") if ch.isalnum() or ch in " -_").strip() or "test"
    return f"{safe[:50]}.docx", buf.getvalue()


def build_doc_docx(title: str, text: str) -> tuple[str, bytes]:
    """Оформляет произвольный текст (статья/реферат/конспект) в Word (.docx)."""
    from docx import Document

    doc = Document()
    if title:
        doc.add_heading(title, level=1)
    for para in (text or "").split("\n"):
        doc.add_paragraph(para)
    buf = io.BytesIO()
    doc.save(buf)
    safe = "".join(ch for ch in (title or "document") if ch.isalnum() or ch in " -_").strip() or "document"
    return f"{safe[:50]}.docx", buf.getvalue()


async def build_presentation(
    text: str, *, domain: str | None = None, max_per_slide: int = 1,
    sources: list[str] | None = None, style: str = "modern"
) -> tuple[str, bytes]:
    """С фото: для слайдов с запросом IMG собирает кандидатов из нескольких источников
    (по сфере темы) и выбирает лучшую картинку зрением Claude. Источник выверенных,
    переиспользуемых изображений — только CC/public domain (презентации раздаются студентам).

    domain: 'medical' | 'humanities' | 'general'; None — определить автоматически по тексту.
    max_per_slide: сколько фото максимум на слайд (1–2).
    sources: названия материалов библиотеки (RAG) — проставятся на слайдах как источник."""
    import httpx

    from .images import detect_domain, illustrate_slides

    title, subtitle, slides = _need_slides(text)
    if any(sl.get("img") for sl in slides):
        if domain is None:
            probe = " ".join([title] + [sl.get("title", "") for sl in slides]
                             + [sl.get("img", "") for sl in slides])
            domain = detect_domain(probe)
        async with httpx.AsyncClient(follow_redirects=True) as client:
            await illustrate_slides(slides, domain, client, max_per_slide=max_per_slide)
    from . import themes  # тематическое оформление: цвет подбирается авто по теме + бренд TestRoom
    return themes.assemble_themed(title, subtitle, slides, sources=sources)
