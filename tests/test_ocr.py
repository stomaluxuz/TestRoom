import io

import pytest

from app import ocr

_HAS_TESS = ocr.tesseract_available()


def _scanned_pdf(lines: list[str]) -> bytes:
    """Собрать PDF-'скан': текст нарисован картинкой (без текстового слоя)."""
    import pymupdf
    from PIL import Image, ImageDraw, ImageFont

    f = ImageFont.truetype("app/assets/fonts/DejaVuSans.ttf", 34)
    img = Image.new("RGB", (1000, 120 + 80 * len(lines)), "white")
    d = ImageDraw.Draw(img)
    for i, ln in enumerate(lines):
        d.text((40, 40 + i * 80), ln, font=f, fill="black")
    buf = io.BytesIO(); img.save(buf, "PNG")
    doc = pymupdf.open()
    page = doc.new_page(width=img.width, height=img.height)
    page.insert_image(pymupdf.Rect(0, 0, img.width, img.height), stream=buf.getvalue())
    return doc.tobytes()


def test_looks_scanned():
    assert ocr.looks_scanned("", 10) is True            # пусто на 10 страниц → скан
    assert ocr.looks_scanned("a" * 5000, 10) is False   # много текста → не скан
    assert ocr.looks_scanned("abc", 0) is False         # нет страниц → не трогаем


def test_pdf_page_count(tmp_path):
    pdf = _scanned_pdf(["Тест страница"])
    p = tmp_path / "s.pdf"; p.write_bytes(pdf)
    assert ocr.pdf_page_count(str(p)) == 1


@pytest.mark.skipif(not _HAS_TESS, reason="tesseract не установлен")
async def test_scanned_upload_flow(db, tmp_path):
    """Загрузка скана → помечается на OCR; ocr_doc распознаёт и заполняет текст книги."""
    from sqlalchemy import select

    from app import services as svc
    from app.models import LibraryDoc, LibrarySubject

    # преподаватель + предмет библиотеки (сид есть)
    u = await svc.get_or_create_user(db, 321)
    await svc.set_full_name(db, u, "Рахимова Нигора")
    await svc.request_teacher(db, u, "ТашМИ")
    teacher = await svc.decide_teacher(db, 321, True)
    subj = await db.scalar(select(LibrarySubject))

    pdf = _scanned_pdf(["Пульпит и его лечение", "Davolash usullari muhim"])
    src = tmp_path / "up.pdf"; src.write_bytes(pdf)
    doc = await svc.add_library_doc_from_path(
        db, teacher, subj.id, "Пульпит", "scan.pdf", "application/pdf", str(src), len(pdf)
    )
    assert doc.ocr_status == "pending"               # распознан как скан при загрузке
    assert len((doc.text or "").strip()) < 20         # текстового слоя нет

    # одобряем напрямую (без фоновой очереди) и распознаём
    doc.status = "approved"; await db.commit()
    n = await svc.ocr_doc(db, doc.id)
    assert n > 0
    d = await db.get(LibraryDoc, doc.id)
    assert d.ocr_status == "done"
    assert "пульпит" in (d.text or "").lower()        # текст из скана попал в книгу


@pytest.mark.skipif(not _HAS_TESS, reason="tesseract не установлен")
def test_ocr_reads_scanned_pdf(tmp_path):
    pdf = _scanned_pdf(["Кариес зубов и его профилактика", "Asosiy sabab bakteriyalar"])
    p = tmp_path / "scan.pdf"; p.write_bytes(pdf)
    # текстового слоя нет → это скан
    from pypdf import PdfReader
    assert len((PdfReader(str(p)).pages[0].extract_text() or "").strip()) < 20
    # OCR вытаскивает текст (и русский, и узбекскую латиницу)
    text = ocr.ocr_pdf(str(p))
    low = text.lower()
    assert "кариес" in low
    assert "bakteriyalar" in low or "sabab" in low
