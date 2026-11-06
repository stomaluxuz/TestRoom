import io

import pytest

from app import ai
from app.parsers import extract_document_text, pptx_to_text
from app.services import ServiceError


def _make_pptx_bytes() -> bytes:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    tb = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(2))
    tb.text_frame.text = "Кариес — разрушение твёрдых тканей зуба"
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def test_pptx_to_text_extracts_slide_text():
    text = pptx_to_text(_make_pptx_bytes())
    assert "Кариес" in text


def test_extract_document_text_dispatches_pptx():
    text = extract_document_text("lecture.pptx", _make_pptx_bytes())
    assert "разрушение" in text


CANNED = """1. Что такое кариес
+ разрушение твёрдых тканей зуба
- воспаление дёсен
- перелом челюсти
- опухоль языка
"""


async def test_generate_strict_uses_material_and_allows_empty_topic(monkeypatch):
    captured = {}

    async def fake_ask(system, prompt, max_tokens=4000):
        captured["prompt"] = prompt
        return CANNED

    monkeypatch.setattr(ai, "_ask", fake_ask)
    # строгий режим: тему можно не указывать, материал обязателен
    qs = await ai.generate_test_questions(
        "", count=1, context="Кариес — разрушение твёрдых тканей зуба.", strict=True
    )
    assert len(qs) == 1
    assert "СТРОГО" in captured["prompt"]          # промпт требует строго по материалу
    assert "РОВНО" not in captured["prompt"]        # не форсируем точное число
    assert "Кариес" in captured["prompt"]           # материал попал в запрос


async def test_generate_non_strict_still_requires_topic():
    with pytest.raises(ServiceError):
        await ai.generate_test_questions("", count=5)


async def test_generate_strict_caps_long_material(monkeypatch):
    captured = {}

    async def fake_ask(system, prompt, max_tokens=4000):
        captured["prompt"] = prompt
        return CANNED

    monkeypatch.setattr(ai, "_ask", fake_ask)
    huge = "кариес " * 10000  # заведомо длиннее лимита
    await ai.generate_test_questions("тема", count=1, context=huge, strict=True)
    # материал в промпте обрезан до лимита
    assert len(captured["prompt"]) < len(huge) + 2000
