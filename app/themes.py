"""Тематическое оформление презентаций: единый «дорогой» макет, но свой акцентный цвет
под предмет. Предмет определяется АВТОМАТИЧЕСКИ по словам в теме (detect_theme) — писать
предмет не нужно. Промах классификатора = просто нейтральная тема, презентацию не ломает.

Макет (как в образце «бордо»): чистый тёплый фон, боковая акцентная полоса, эйбрау с
разрядкой, крупный заголовок с акцентной линией, воздушный список без «плашек», фото в
белой карточке с мягкой тенью, цветной блок на титуле. Шрифт Segoe UI (у всех Windows).
Остаётся редактируемым .pptx.
"""
from __future__ import annotations

import io

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

PW, PH = 13.333, 7.5
HEAD, SANS = "Segoe UI Semibold", "Segoe UI"

# Общие нейтрали (одинаковы во всех темах — меняется только акцент)
BG    = RGBColor(0xFB, 0xFA, 0xF9)
INK   = RGBColor(0x24, 0x1A, 0x1C)
BODY  = RGBColor(0x41, 0x39, 0x3A)
MUTED = RGBColor(0x8A, 0x7E, 0x80)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
HAIR  = RGBColor(0xEC, 0xE6, 0xE6)

# Темы: ключ → (акцентный цвет, подпись-эйбрау). Нейтрали общие.
THEMES = {
    "surgery":   (RGBColor(0x86, 0x26, 0x33), "ХИРУРГИЧЕСКАЯ СТОМАТОЛОГИЯ"),
    "therapy":   (RGBColor(0x1F, 0x5A, 0xA8), "ТЕРАПЕВТИЧЕСКАЯ СТОМАТОЛОГИЯ"),
    "prosth":    (RGBColor(0x0E, 0x7C, 0x86), "ОРТОПЕДИЯ · ОРТОДОНТИЯ"),
    "anatomy":   (RGBColor(0x1E, 0x7A, 0x4D), "АНАТОМИЯ"),
    "histology": (RGBColor(0x6D, 0x4A, 0xA6), "ГИСТОЛОГИЯ"),
    "pharm":     (RGBColor(0x39, 0x49, 0xAB), "ФАРМАКОЛОГИЯ"),
    "default":   (RGBColor(0x3A, 0x3F, 0x47), "УЧЕБНАЯ ПРЕЗЕНТАЦИЯ"),
}

# Ключевые слова для авто-определения предмета по теме (корни, регистр не важен).
_KW = {
    "surgery": ("хирург", "удал", "остеомиел", "периостит", "абсцесс", "флегмон", "имплант",
                "резекц", "челюст", "перелом", "вывих", "экстракц", "гнойн", "одонтоген",
                "чло", "лоскут", "секвестр", "операц", "альвеолит"),
    "therapy": ("терап", "кариес", "пульпит", "периодонтит", "эндодонт", "пломб", "реставрац",
                "депульп", "корнев", "гиперестез", "некариозн"),
    "prosth":  ("ортопед", "коронк", "протез", "мостовид", "вкладк", "винир", "ортодонт",
                "брекет", "прикус", "элайнер", "окклюз", "артикул", "съёмн"),
    "anatomy": ("анатом", "строение зуб", "костн", "мышц", "сосуд", "нерв", "сустав", "череп",
                "топограф", "связк", "скелет"),
    "histology": ("гистолог", "клетк", "ткан", "эпители", "эмбриолог", "цитолог", "органелл",
                  "мембран", "дентиногенез", "амелогенез"),
    "pharm":   ("фармаколог", "лекарств", "доза", "дозир", "фармакокинет", "фармакодинам",
                "антибиотик", "анальгетик", "анестетик", "побочн", "НПВС", "антисептик"),
}


def detect_theme(topic: str) -> str:
    """Определяет предмет по словам в теме → ключ темы оформления. Не нашли — 'default'."""
    low = " ".join((topic or "").lower().split())
    best, score = "default", 0
    for key, kws in _KW.items():
        c = sum(1 for w in kws if w.lower() in low)
        if c > score:
            best, score = key, c
    return best


# ------------------------------------------------------------------ низкоуровневые помощники

def _bg(slide):
    slide.background.fill.solid(); slide.background.fill.fore_color.rgb = BG


def _font(run, name, size, color, bold=False):
    run.font.name = name; run.font.size = Pt(size); run.font.bold = bold; run.font.color.rgb = color


def _track(run, pts):
    run._r.get_or_add_rPr().set("spc", str(int(pts * 100)))


def _tb(slide, l, t, w, h, anchor=MSO_ANCHOR.TOP):
    tf = slide.shapes.add_textbox(Inches(l), Inches(t), Inches(w), Inches(h)).text_frame
    tf.word_wrap = True; tf.vertical_anchor = anchor
    return tf


def _rect(slide, l, t, w, h, color, shape=MSO_SHAPE.RECTANGLE, round_adj=None):
    sh = slide.shapes.add_shape(shape, Inches(l), Inches(t), Inches(w), Inches(h))
    sh.fill.solid(); sh.fill.fore_color.rgb = color
    sh.line.fill.background(); sh.shadow.inherit = False
    if round_adj is not None:
        try:
            sh.adjustments[0] = round_adj
        except Exception:
            pass
    return sh


def _soft_shadow(shape, blur=95000, dist=40000, alpha=22000):
    spPr = shape._element.spPr
    for el in spPr.findall(qn("a:effectLst")):
        spPr.remove(el)
    eff = spPr.makeelement(qn("a:effectLst"), {})
    shd = eff.makeelement(qn("a:outerShdw"),
                          {"blurRad": str(blur), "dist": str(dist), "dir": "5400000", "rotWithShape": "0"})
    clr = shd.makeelement(qn("a:srgbClr"), {"val": "000000"})
    al = clr.makeelement(qn("a:alpha"), {"val": str(alpha)})
    clr.append(al); shd.append(clr); eff.append(shd); spPr.append(eff)


def _eyebrow(tf, text, accent):
    r = tf.paragraphs[0].add_run(); r.text = text.upper(); _font(r, SANS, 11, accent, bold=True); _track(r, 2.2)


def _bullets(slide, l, t, w, h, items, accent):
    tf = _tb(slide, l, t, w, h); tf.auto_size = MSO_AUTO_SIZE.NONE
    size = 18 if len(items) <= 4 else (16 if len(items) <= 5 else 14)
    for i, b in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(16); p.line_spacing = 1.12
        r1 = p.add_run(); r1.text = "—  "; _font(r1, HEAD, size, accent, bold=True)
        r2 = p.add_run(); r2.text = b; _font(r2, SANS, size, BODY)


def _photo_card(slide, l, t, w, h, img_bytes):
    card = _rect(slide, l, t, w, h, WHITE, MSO_SHAPE.ROUNDED_RECTANGLE, round_adj=0.055)
    _soft_shadow(card)
    pad = 0.18
    try:
        pic = slide.shapes.add_picture(io.BytesIO(img_bytes), Inches(l + pad), Inches(t + pad),
                                       width=Inches(w - 2 * pad))
        maxh = Inches(h - 2 * pad)
        if pic.height > maxh:
            sc = maxh / pic.height
            pic.width = int(pic.width * sc); pic.height = int(maxh)
        pic.left = int(Inches(l) + (Inches(w) - pic.width) / 2)
        pic.top = int(Inches(t) + (Inches(h) - pic.height) / 2)
    except Exception:
        pass


# ------------------------------------------------------------------ сборка

def assemble_themed(title: str, subtitle: str, slides: list[dict],
                    sources: list[str] | None = None, theme: str | None = None) -> tuple[str, bytes]:
    # Авто-подбор ЦВЕТА по теме (подпись предмета не показываем — чтобы промахи не вылезали текстом).
    key = theme or detect_theme(" ".join([title] + [s.get("title", "") for s in slides]))
    accent = THEMES.get(key, THEMES["default"])[0]
    sources = [s for s in (sources or []) if s]

    prs = Presentation()
    prs.slide_width = Inches(PW); prs.slide_height = Inches(PH)
    blank = prs.slide_layouts[6]

    # ---- титул ----
    s0 = prs.slides.add_slide(blank); _bg(s0)
    # бренд: квадрат-марка + «TestRoom» (Test — чернила, Room — акцент)
    _rect(s0, 0.9, 1.22, 0.42, 0.42, accent, MSO_SHAPE.ROUNDED_RECTANGLE, round_adj=0.2)
    wm = _tb(s0, 1.48, 1.27, 5.0, 0.5, MSO_ANCHOR.MIDDLE)
    w1 = wm.paragraphs[0].add_run(); w1.text = "Test"; _font(w1, HEAD, 18, INK, bold=True)
    w2 = wm.paragraphs[0].add_run(); w2.text = "Room"; _font(w2, HEAD, 18, accent, bold=True)
    tf = _tb(s0, 0.9, 2.4, PW - 2.4, 2.1)
    tf.paragraphs[0].line_spacing = 1.04
    r = tf.paragraphs[0].add_run(); r.text = title
    _font(r, HEAD, 40 if len(title) <= 46 else (32 if len(title) <= 90 else 26), INK, bold=True)
    _rect(s0, 0.92, 4.7, 1.4, 0.08, accent, MSO_SHAPE.ROUNDED_RECTANGLE, round_adj=0.5)
    if subtitle:
        sr = _tb(s0, 0.9, 5.0, PW - 3.5, 0.9).paragraphs[0].add_run()
        sr.text = subtitle; _font(sr, SANS, 19 if len(subtitle) <= 80 else 15, MUTED)
    # нижний акцентный блок (только цвет; без подписи предмета и без «ИИ»); источник — если есть
    _rect(s0, 0, PH - 1.1, PW, 1.1, accent)
    if sources:
        btf = _tb(s0, 0.9, PH - 0.95, PW - 1.8, 0.65, MSO_ANCHOR.MIDDLE)
        br = btf.paragraphs[0].add_run()
        br.text = "По материалам: " + "; ".join(sources[:2]); _font(br, SANS, 12, WHITE); _track(br, 0.4)

    # ---- содержательные ----
    for sl in slides:
        s = prs.slides.add_slide(blank); _bg(s)
        _rect(s, 0, 0, 0.14, PH, accent)  # боковая акцентная полоса
        imgs = [b for b in (sl.get("images") or []) if b] or ([sl["img_bytes"]] if sl.get("img_bytes") else [])
        body_w = 6.9 if imgs else 10.5
        htf = _tb(s, 0.7, 0.62, body_w, 1.0, MSO_ANCHOR.MIDDLE)
        hr = htf.paragraphs[0].add_run(); hr.text = sl.get("title") or " "; _font(hr, HEAD, 28, INK, bold=True)
        _rect(s, 0.72, 1.68, 1.1, 0.07, accent, MSO_SHAPE.ROUNDED_RECTANGLE, round_adj=0.5)
        bl = [b for b in (sl.get("bullets") or []) if b.strip()] or [" "]
        _bullets(s, 0.7, 2.05, body_w, 4.55, bl, accent)
        if imgs:
            _photo_card(s, 8.0, 1.9, 4.6, 4.2, imgs[0])
        _rect(s, 0.7, PH - 0.62, PW - 1.4, 0.012, HAIR)
        ft = _tb(s, 0.7, PH - 0.55, PW - 1.4, 0.4).paragraphs[0].add_run()
        ft.text = "TestRoom"; _font(ft, SANS, 9, MUTED)

    buf = io.BytesIO(); prs.save(buf)
    safe = "".join(ch for ch in title if ch.isalnum() or ch in " -_").strip() or "presentation"
    return f"{safe[:50]}.pptx", buf.getvalue()
