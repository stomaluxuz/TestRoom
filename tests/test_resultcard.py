import io

from PIL import Image

from app.resultcard import _pick_tier, render_result_card


def test_tier_thresholds():
    assert _pick_tier(10, 10)[0] == "champion"
    assert _pick_tier(9, 10)[0] == "champion"
    assert _pick_tier(8, 10)[0] == "great"
    assert _pick_tier(7, 10)[0] == "great"
    assert _pick_tier(6, 10)[0] == "good"
    assert _pick_tier(5, 10)[0] == "good"
    assert _pick_tier(4, 10)[0] == "start"
    assert _pick_tier(0, 10)[0] == "start"
    assert _pick_tier(0, 0)[0] == "start"  # нет вопросов — не падаем


def test_render_all_tiers_and_langs():
    cases = [("ru", "Каримов Азиз", 10, 10), ("uz", "Yusupova Dilnoza", 6, 10),
             ("en", "John Smith", 3, 10), ("ru", "Пётр", 0, 0)]
    for lang, name, c, n in cases:
        data = render_result_card(lang, name, c, n, "Кариес зубов", "TestRoom_bot")
        assert data[:2] == b"\xff\xd8"  # валидный JPEG (для send_photo)
        im = Image.open(io.BytesIO(data))
        assert im.size == (1080, 1350)


def test_render_handles_long_name_and_unknown_lang():
    data = render_result_card("xx", "Очень-Очень Длинная Фамилия Имя Отчество Студента", 7, 12,
                              "Очень длинное название теста по хирургической стоматологии и осмотру", "b")
    assert data[:2] == b"\xff\xd8"  # не падает, язык по умолчанию ru
