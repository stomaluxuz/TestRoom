"""Карточка результата теста (PNG) для отправки студенту и репоста в соцсети.

render_result_card(lang, full_name, correct, total, test_title, bot_username) -> bytes (PNG).
Текст — на языке студента (uz/ru/en). Иконка и градиент — по уровню результата.
Шрифты и иконки вшиты в app/assets (на проде гарантированно есть)."""
from __future__ import annotations

import io
import os

from PIL import Image, ImageDraw, ImageFont

_ASSETS = os.path.join(os.path.dirname(__file__), "assets")
_FONTS = os.path.join(_ASSETS, "fonts")
_ICONS = os.path.join(_ASSETS, "result")

W, H = 1080, 1350  # портрет 4:5 — удобно для соцсетей

# Уровни: (порог доли, ключ, иконка, верхний цвет, нижний цвет)
_TIERS = [
    (0.90, "champion", "trophy.png", (247, 183, 51), (252, 74, 26)),   # золото
    (0.70, "great",    "star.png",   (17, 153, 142), (56, 239, 125)),  # зелёный
    (0.50, "good",     "arrow.png",  (33, 147, 176), (109, 213, 237)),  # синий
    (0.00, "start",    "rocket.png", (127, 83, 172), (100, 125, 238)),  # фиолетовый
]

# Тексты карточки (uz/ru/en). {x},{n} — число правильных и всего.
_T = {
    "champion": {
        "title": {"ru": "Чемпион!", "uz": "Chempion!", "en": "Champion!"},
        "sub": {
            "ru": "Ты знаешь тему на отлично. Так держать!",
            "uz": "Mavzuni a'lo bilasan. Shu zayilda davom et!",
            "en": "You know this topic perfectly. Keep it up!",
        },
    },
    "great": {
        "title": {"ru": "Отличная работа!", "uz": "Ajoyib natija!", "en": "Great job!"},
        "sub": {
            "ru": "Крепкие знания. Ещё чуть-чуть до вершины!",
            "uz": "Bilimlaring mustahkam. Cho'qqiga ozgina qoldi!",
            "en": "Solid knowledge. Almost at the top!",
        },
    },
    "good": {
        "title": {"ru": "Хороший старт!", "uz": "Yaxshi boshlanish!", "en": "Good start!"},
        "sub": {
            "ru": "Движешься верно. Повтори тему — и будет отлично!",
            "uz": "To'g'ri yo'ldasan. Mavzuni takrorla — a'lo bo'ladi!",
            "en": "You're on the right track. Review and you'll ace it!",
        },
    },
    "start": {
        "title": {"ru": "Всё впереди!", "uz": "Hammasi oldinda!", "en": "It's just the start!"},
        "sub": {
            "ru": "Каждый эксперт начинал с нуля. Повтори и попробуй снова!",
            "uz": "Har bir mutaxassis noldan boshlagan. Takrorlab, yana urinib ko'r!",
            "en": "Every expert started somewhere. Review and try again!",
        },
    },
}
_SCORE = {"ru": "Правильных: {x} из {n}", "uz": "To'g'ri: {x} / {n}", "en": "Correct: {x} of {n}"}
_TESTLBL = {"ru": "Тест: {t}", "uz": "Test: {t}", "en": "Test: {t}"}
# без эмодзи: вшитый шрифт DejaVu их не рисует (вышли бы «квадраты-тофу»)
_CTA = {"ru": "Пройди и ты тоже!", "uz": "Sen ham sinab ko'r!", "en": "Try it too!"}


def _blend(a, b, t):
    """Смешать цвета a и b (t: 0→a, 1→b)."""
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _pick_tier(correct: int, total: int):
    ratio = (correct / total) if total else 0.0
    for thr, key, icon, c1, c2 in _TIERS:
        if ratio >= thr:
            return key, icon, c1, c2
    return _TIERS[-1][1], _TIERS[-1][2], _TIERS[-1][3], _TIERS[-1][4]


def _font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(os.path.join(_FONTS, name), size)
    except Exception:
        return ImageFont.load_default()


def _gradient(c1, c2) -> Image.Image:
    """Вертикальный градиент c1→c2 (сверху вниз)."""
    base = Image.new("RGB", (1, H))
    px = base.load()
    for y in range(H):
        t = y / (H - 1)
        px[0, y] = tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))
    return base.resize((W, H))


def _fit(text: str, draw, font_bold, size: int, max_w: int) -> ImageFont.FreeTypeFont:
    """Подбирает размер шрифта так, чтобы строка влезла по ширине."""
    s = size
    while s > 14:
        f = _font(font_bold, s)
        if draw.textlength(text, font=f) <= max_w:
            return f
        s -= 2
    return _font(font_bold, 14)


def _wrap(text: str, draw, font, max_w: int) -> list[str]:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines


def _center_text(draw, cy, text, font, fill, max_w=None):
    w = draw.textlength(text, font=font)
    draw.text(((W - w) / 2, cy), text, font=font, fill=fill)
    bbox = draw.textbbox((0, 0), text, font=font)
    return cy + (bbox[3] - bbox[1])


def render_result_card(lang: str, full_name: str, correct: int, total: int,
                       test_title: str, bot_username: str = "") -> bytes:
    lang = lang if lang in ("ru", "uz", "en") else "ru"
    correct = max(0, int(correct)); total = max(0, int(total))
    key, icon_name, c1, c2 = _pick_tier(correct, total)

    img = _gradient(c1, c2).convert("RGBA")
    d = ImageDraw.Draw(img)
    white = (255, 255, 255, 255)
    pad = 90
    inner = W - 2 * pad

    # иконка (белая, по центру сверху)
    y = 150
    try:
        icon = Image.open(os.path.join(_ICONS, icon_name)).convert("RGBA")
        icon = icon.resize((300, 300))
        img.paste(icon, ((W - 300) // 2, y), icon)
    except Exception:
        pass
    y += 300 + 30

    # заголовок уровня
    title = _T[key]["title"][lang]
    tf = _fit(title, d, True, 84, inner)
    y = _center_text(d, y, title, tf, white) + 26

    # ФИО студента + подчёркивание
    name = " ".join((full_name or "").split()) or "—"
    nf = _fit(name, d, True, 58, inner)
    nw = d.textlength(name, font=nf)
    y2 = _center_text(d, y, name, nf, white)
    d.line([((W - nw) / 2, y2 + 8), ((W + nw) / 2, y2 + 8)], fill=(255, 255, 255, 150), width=3)
    y = y2 + 40

    # «пилюля» со счётом. Pillow не компонует альфу (при convert в RGB полупрозрачная
    # белая заливка стала бы СПЛОШНОЙ белой и скрыла белый текст). Поэтому считаем цвет
    # фона на этой высоте и рисуем СПЛОШНУЮ осветлённую плашку — белый текст читается.
    score = _SCORE[lang].format(x=correct, n=total)
    sf = _font(True, 50)
    sw = d.textlength(score, font=sf)
    ph = 92; pw = int(sw) + 90
    pill_x = (W - pw) / 2
    grad_here = _blend(c1, c2, (y + ph / 2) / H)
    pill_bg = _blend(grad_here, (255, 255, 255), 0.26)  # как полупрозрачная белая поверх фона
    d.rounded_rectangle([pill_x, y, pill_x + pw, y + ph], radius=ph // 2, fill=pill_bg)
    d.text(((W - sw) / 2, y + (ph - 60) / 2 - 4), score, font=sf, fill=white)
    y += ph + 44

    # мотивационная подпись (перенос по словам)
    sub = _T[key]["sub"][lang]
    subf = _font(False, 44)
    for line in _wrap(sub, d, subf, inner)[:3]:
        y = _center_text(d, y, line, subf, (255, 255, 255, 240)) + 12
    y += 18

    # название теста
    tl = _TESTLBL[lang].format(t=" ".join((test_title or "").split()))
    tlf = _fit(tl, d, False, 38, inner)
    _center_text(d, y, tl, tlf, (255, 255, 255, 210))

    # низ: ссылка на бота + призыв
    if bot_username:
        link = f"t.me/{bot_username}"
        lf = _font(True, 46)
        _center_text(d, H - 170, link, lf, white)
        cf = _font(False, 36)
        _center_text(d, H - 108, _CTA[lang], cf, (255, 255, 255, 220))
    else:
        bf = _font(True, 40)
        _center_text(d, H - 130, "TestRoom", bf, (255, 255, 255, 230))

    out = io.BytesIO()
    img.convert("RGB").save(out, "PNG")
    return out.getvalue()
