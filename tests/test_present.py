import base64
import io

import pytest

from app.present import PRESENT_EXAMPLE, _assemble, build_pptx, parse
from app.services import ServiceError

# минимальный валидный PNG 1x1 для проверки вставки картинки
PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def test_parse_structure():
    title, subtitle, slides = parse(PRESENT_EXAMPLE)
    assert title == "Анатомия сердца"
    assert subtitle == "Лекция для 2 курса"
    assert len(slides) == 3
    assert slides[0]["title"] == "Строение сердца"
    assert slides[0]["bullets"][0].startswith("4 камеры")  # «-» снято


def test_parse_img_query():
    title, _, slides = parse("Тема\n\n# Слайд\n- пункт\nIMG: human heart\n")
    assert slides[0]["img"] == "human heart"
    assert slides[0]["bullets"] == ["пункт"]  # строка IMG не попала в пункты


def test_assemble_with_image():
    slides = [{"title": "С фото", "bullets": ["пункт"], "img_bytes": PNG_1x1}]
    name, data = _assemble("Тест", "подзаголовок", slides)
    assert data[:2] == b"PK"
    from pptx import Presentation

    prs = Presentation(io.BytesIO(data))
    # 13 = PICTURE; исключаем фоновую картинку слайда (она в (0,0)) — считаем только контентные фото
    pics = [sh for sh in prs.slides[1].shapes if sh.shape_type == 13 and (sh.left, sh.top) != (0, 0)]
    assert len(pics) == 1


def test_build_pptx_bytes():
    name, data = build_pptx(PRESENT_EXAMPLE)
    assert name.endswith(".pptx")
    assert data[:2] == b"PK"  # zip-контейнер Office
    # титульный + 3 слайда
    from pptx import Presentation

    prs = Presentation(io.BytesIO(data))
    assert len(prs.slides) == 4


def test_build_pptx_empty_fails():
    with pytest.raises(ServiceError):
        build_pptx("   \n  \n")


async def test_ai_requires_key():
    from app import ai
    from app.config import settings

    settings.anthropic_api_key = ""
    with pytest.raises(ServiceError):
        await ai.generate_slides("Анатомия сердца")  # без ключа ИИ-режим недоступен
