import base64
import io

import pytest

from app import ai, images
from app.config import settings
from app.present import _assemble

# минимальный валидный PNG 1x1
PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def test_detect_domain():
    assert images.detect_domain("Анатомия сердца человека") == "medical"
    assert images.detect_domain("dental caries diagnosis") == "medical"
    assert images.detect_domain("История Древнего Рима") == "humanities"
    assert images.detect_domain("Renaissance painting and art") == "humanities"
    # ни то, ни другое — общий источник
    assert images.detect_domain("Основы программирования на Python") == "general"


def test_variants_shrink():
    v = images._variants("human heart anatomy cross section detail")
    assert v[0] == "human heart anatomy cross section detail"
    assert "human heart anatomy cross" in v  # укорочен до 4 слов
    assert "human heart" in v


def test_assemble_two_images():
    slides = [{"title": "Два фото", "bullets": ["пункт"], "images": [PNG_1x1, PNG_1x1]}]
    _, data = _assemble("Тест", "", slides)
    from pptx import Presentation

    prs = Presentation(io.BytesIO(data))
    pics = [sh for sh in prs.slides[1].shapes if sh.shape_type == 13 and (sh.left, sh.top) != (0, 0)]
    assert len(pics) == 2


def test_assemble_legacy_img_bytes_still_works():
    slides = [{"title": "Старый формат", "bullets": ["п"], "img_bytes": PNG_1x1}]
    _, data = _assemble("Т", "", slides)
    from pptx import Presentation

    prs = Presentation(io.BytesIO(data))
    pics = [sh for sh in prs.slides[1].shapes if sh.shape_type == 13 and (sh.left, sh.top) != (0, 0)]
    assert len(pics) == 1


async def test_choose_without_key_returns_first():
    old = settings.anthropic_api_key
    settings.anthropic_api_key = ""
    try:
        res = await ai.choose_slide_images("t", ["b"], ["aGVsbG8=", "d29ybGQ=", "eA=="], want=2)
        assert res == [0, 1]
        assert await ai.choose_slide_images("t", [], [], want=1) == []
    finally:
        settings.anthropic_api_key = old


async def test_illustrate_slides_uses_vision_pick(monkeypatch):
    async def fake_gather(query, domain, client, limit=6, hint=None, source_funcs=None):
        return [
            {"url": "u1", "source": "s", "data": b"A", "vb64": "QQ=="},
            {"url": "u2", "source": "s", "data": b"B", "vb64": "Qg=="},
            {"url": "u3", "source": "s", "data": b"C", "vb64": "Qw=="},
        ]

    async def fake_choose(title, bullets, cands, want=1):
        return [2]  # выбираем третий кандидат

    monkeypatch.setattr(images, "gather_candidates", fake_gather)
    monkeypatch.setattr(ai, "choose_slide_images", fake_choose)
    slides = [{"title": "T", "bullets": ["b"], "img": "query"}, {"title": "No img", "bullets": []}]
    await images.illustrate_slides(slides, "general", client=None, max_per_slide=1)
    assert slides[0]["images"] == [b"C"]
    assert "images" not in slides[1]  # слайд без img не трогаем


async def test_illustrate_slides_skips_when_vision_rejects_all(monkeypatch):
    async def fake_gather(query, domain, client, limit=6, hint=None, source_funcs=None):
        return [{"url": "u1", "source": "s", "data": b"X", "vb64": "WA==", "ah": 1}]

    async def fake_choose(title, bullets, cands, want=1):
        return []  # зрение забраковало всё (не по теме)

    monkeypatch.setattr(images, "gather_candidates", fake_gather)
    monkeypatch.setattr(ai, "choose_slide_images", fake_choose)
    slides = [{"title": "T", "bullets": ["b"], "img": "q"}]
    await images.illustrate_slides(slides, "medical", client=None, max_per_slide=1)
    # лучше без фото, чем случайная «собака»
    assert "images" not in slides[0]


async def test_illustrate_slides_dedup_across_slides(monkeypatch):
    # обе темы дают одну и ту же картинку (одинаковый ah) → на второй слайд не ставим
    async def fake_gather(query, domain, client, limit=6, hint=None, source_funcs=None):
        return [{"url": "u", "source": "s", "data": b"SAME", "vb64": "WA==", "ah": 42}]

    async def fake_choose(title, bullets, cands, want=1):
        return [0]

    monkeypatch.setattr(images, "gather_candidates", fake_gather)
    monkeypatch.setattr(ai, "choose_slide_images", fake_choose)
    slides = [{"title": "A", "bullets": ["x"], "img": "q1"},
              {"title": "B", "bullets": ["y"], "img": "q2"}]
    await images.illustrate_slides(slides, "general", client=None, max_per_slide=1)
    assert slides[0]["images"] == [b"SAME"]
    assert "images" not in slides[1]  # дубль между слайдами убран


async def test_illustrate_slides_no_photo_on_vision_error(monkeypatch):
    """Зрение недоступно → слайд остаётся БЕЗ фото (лучше, чем картинка «не в тему»)."""
    async def fake_gather(query, domain, client, limit=6, hint=None, source_funcs=None):
        return [{"url": "u1", "source": "s", "data": b"X", "vb64": "WA=="}]

    async def fake_choose(title, bullets, cands, want=1):
        raise RuntimeError("vision down")

    monkeypatch.setattr(images, "gather_candidates", fake_gather)
    monkeypatch.setattr(ai, "choose_slide_images", fake_choose)
    slides = [{"title": "T", "bullets": ["b"], "img": "q"}]
    await images.illustrate_slides(slides, "medical", client=None, max_per_slide=1)
    assert "images" not in slides[0]  # картинку вслепую не ставим
