import io

from PIL import Image

from app.themes import THEMES, assemble_themed, detect_theme


def _img(w=400, h=300, color=(90, 140, 180)) -> bytes:
    b = io.BytesIO(); Image.new("RGB", (w, h), color).save(b, "JPEG"); return b.getvalue()


def test_detect_theme_by_topic():
    assert detect_theme("Острый одонтогенный остеомиелит челюсти") == "surgery"
    assert detect_theme("Кариес зуба: пульпит и пломбирование") == "therapy"
    assert detect_theme("Гистологическое строение эмали: клетки и ткани") == "histology"
    assert detect_theme("Коронки и мостовидные протезы") == "prosth"
    assert detect_theme("Фармакокинетика местных анестетиков") == "pharm"
    # нет совпадений → нейтральная тема
    assert detect_theme("Разное про всё подряд") == "default"


def test_assemble_themed_builds_pptx():
    slides = [{"title": "Слайд", "bullets": ["пункт один", "пункт два"]}]
    name, data = assemble_themed("Кариес зуба", "подзаголовок", slides)
    assert name.endswith(".pptx")
    assert data[:2] == b"PK"
    from pptx import Presentation
    prs = Presentation(io.BytesIO(data))
    assert len(prs.slides) == 2  # титул + 1 слайд


def test_assemble_themed_with_image_has_picture():
    slides = [{"title": "С фото", "bullets": ["пункт"], "images": [_img()]}]
    _, data = assemble_themed("Хирургия челюсти", "", slides)
    from pptx import Presentation
    prs = Presentation(io.BytesIO(data))
    pics = [sh for sh in prs.slides[1].shapes if sh.shape_type == 13]
    assert len(pics) == 1  # фото вставлено в карточку


def test_assemble_themed_bad_image_no_empty_card():
    """Битая картинка → слайд БЕЗ фото и БЕЗ пустой белой рамки (не пустая карточка)."""
    from pptx.util import Emu

    slides = [{"title": "Битое фото", "bullets": ["текст"], "images": [b"garbage-not-image"]}]
    _, data = assemble_themed("Хирургия", "", slides)
    from pptx import Presentation
    prs = Presentation(io.BytesIO(data))
    s = prs.slides[1]
    pics = [sh for sh in s.shapes if sh.shape_type == 13]
    assert len(pics) == 0  # фото нет
    # нет белой карточки-рамки в правой части (AUTO_SHAPE правее 7 дюймов)
    cards = [sh for sh in s.shapes
             if sh.shape_type == 1 and sh.left and sh.left > Emu(int(7 * 914400)) and sh.width
             and sh.width > Emu(int(2 * 914400))]
    assert len(cards) == 0  # пустой рамки быть не должно


def test_theme_override_ignores_detection():
    _, data = assemble_themed("Любая тема", "", [{"title": "A", "bullets": ["x"]}], theme="pharm")
    assert data[:2] == b"PK"
    assert "pharm" in THEMES
