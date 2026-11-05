import io

from app.themes import THEMES, assemble_themed, detect_theme

PNG_1x1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


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
    slides = [{"title": "С фото", "bullets": ["пункт"], "images": [PNG_1x1]}]
    _, data = assemble_themed("Хирургия челюсти", "", slides)
    from pptx import Presentation
    prs = Presentation(io.BytesIO(data))
    pics = [sh for sh in prs.slides[1].shapes if sh.shape_type == 13]
    assert len(pics) == 1  # фото вставлено в карточку


def test_theme_override_ignores_detection():
    _, data = assemble_themed("Любая тема", "", [{"title": "A", "bullets": ["x"]}], theme="pharm")
    assert data[:2] == b"PK"
    assert "pharm" in THEMES
