from app import ai
from app.parsers import ParsedQuestion


def test_outlier_detection():
    # правильный заметно длиннее → выброс
    out = ParsedQuestion("Q?", ["Короткий", "Ещё вариант", "Тоже краткий", "Очень длинный и подробный правильный ответ"], 3)
    assert ai._correct_is_long_outlier(out) is True
    # все примерно равны → не выброс
    bal = ParsedQuestion("Q?", ["Первый вариант тут", "Второй вариант тут", "Третий вариант тут", "Правильный вариант"], 2)
    assert ai._correct_is_long_outlier(bal) is False
    # правильный самый короткий → не выброс
    sc = ParsedQuestion("Q?", ["Длинный неправильный раз", "Длинный неправильный два", "Короткий", "Длинный неправильный три"], 2)
    assert ai._correct_is_long_outlier(sc) is False


async def test_balance_rewrites_long_correct(monkeypatch):
    q = ParsedQuestion(
        "Что это?",
        ["Коротко", "Ещё коротко", "Тоже кратко", "Очень длинный и подробный правильный ответ, который сразу видно"],
        3,
    )
    assert ai._correct_is_long_outlier(q) is True

    balanced = (
        "1. Что это?\n"
        "A) Первый вариант ответа тут\n"
        "B) Второй вариант ответа тут\n"
        "C) Третий вариант ответа тут\n"
        "*D) Правильный вариант ответа тут\n"
    )

    async def fake_ask(system, prompt, max_tokens=4000):
        return balanced

    monkeypatch.setattr(ai, "_ask", fake_ask)
    out = await ai._balance_long_answers([q], "ru")
    assert ai._correct_is_long_outlier(out[0]) is False          # длина выровнена
    assert out[0].options[out[0].correct] == "Правильный вариант ответа тут"
    assert out[0].text == "Что это?"                              # текст вопроса не трогаем


async def test_balance_noop_when_balanced(monkeypatch):
    q = ParsedQuestion("Q?", ["вар один тут", "вар два тут", "вар три тут", "вар четыре"], 1)
    called = {"v": False}

    async def fake_ask(*a, **k):
        called["v"] = True
        return ""

    monkeypatch.setattr(ai, "_ask", fake_ask)
    out = await ai._balance_long_answers([q], "ru")
    assert out == [q]
    assert called["v"] is False  # сбалансированный тест → модель не дёргаем
