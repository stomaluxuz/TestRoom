"""Вырезание иллюстраций из PDF учебников библиотеки (для подбора фото на слайды).

Берём ТОЛЬКО встроенные растровые изображения (у текстовых PDF; у сканов вся страница — одна
картинка, их пропускаем). Мелочь (буквицы, иконки, линейки) отсекаем по размеру.
Включается флагом settings.library_figures_enabled. Это копирайтные материалы —
использование на усмотрение оператора.
"""
from __future__ import annotations

import io

# пороги, чтобы не тащить мусор (иконки, фрагменты, декоративные элементы)
_MIN_W, _MIN_H = 180, 180
_MIN_BYTES = 8000
_MAX_PER_DOC = 400       # предохранитель на огромные атласы
_FULLPAGE_RATIO = 0.92   # картинка почти во всю страницу → вероятно скан-страница, пропускаем


def render_pdf_cover(pdf_path: str, px: int = 700) -> bytes | None:
    """Рендерит ПЕРВУЮ страницу PDF в JPEG (обложка книги). None — если не PDF/ошибка.
    Тяжёлое (рендер) — вызывать в отдельном потоке."""
    try:
        import pymupdf

        doc = pymupdf.open(pdf_path)
        try:
            if doc.page_count == 0:
                return None
            page = doc.load_page(0)
            rect = page.rect
            scale = px / max(float(rect.width), float(rect.height), 1.0)
            scale = min(scale, 3.0)  # не раздуваем мелкие страницы
            pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            return pix.tobytes("jpeg", jpg_quality=82)
        finally:
            doc.close()
    except Exception:
        return None


def extract_pdf_figures(pdf_path: str) -> list[dict]:
    """Возвращает [{page, data(bytes jpeg), w, h}] — иллюстрации из PDF. Тяжёлое: вызывать в потоке."""
    try:
        from pypdf import PdfReader
        from PIL import Image
    except Exception:
        return []
    try:
        reader = PdfReader(pdf_path)
    except Exception:
        return []
    out: list[dict] = []
    for pi, page in enumerate(reader.pages, 1):
        try:
            pw = float(page.mediabox.width) or 1.0
            ph = float(page.mediabox.height) or 1.0
            images = list(page.images)
        except Exception:
            continue
        # если на странице одна гигантская картинка почти во весь лист — это скан, пропускаем
        if len(images) == 1:
            try:
                im0 = Image.open(io.BytesIO(images[0].data))
                if im0.width >= _FULLPAGE_RATIO * pw and im0.height >= _FULLPAGE_RATIO * ph:
                    continue
            except Exception:
                pass
        for im in images:
            try:
                data = im.data
                if len(data) < _MIN_BYTES:
                    continue
                pic = Image.open(io.BytesIO(data)).convert("RGB")
            except Exception:
                continue
            if pic.width < _MIN_W or pic.height < _MIN_H:
                continue
            buf = io.BytesIO()
            pic.save(buf, format="JPEG", quality=85)
            out.append({"page": pi, "data": buf.getvalue(), "w": pic.width, "h": pic.height})
            if len(out) >= _MAX_PER_DOC:
                return out
    return out


def vision_thumb_b64(data: bytes, px: int = 384) -> str | None:
    """Уменьшенная JPEG-копия в base64 — для подписи/оценки зрением."""
    try:
        import base64

        from PIL import Image

        im = Image.open(io.BytesIO(data)).convert("RGB")
        im.thumbnail((px, px))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=70)
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return None
