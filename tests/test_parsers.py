import io

import pytest
from docx import Document
from openpyxl import Workbook

from app.parsers import (
    TEMPLATE_TXT,
    ParseFailed,
    parse_file,
    parse_text,
    template_docx,
    template_xlsx,
)


def test_plus_minus_basic():
    text = "1. Какая кость самая длинная?\n+ Бедренная\n- Плечевая\n- Большеберцовая\n- Лучевая\n"
    r = parse_text(text)
    assert r.fmt == "plus_minus"
    assert len(r.questions) == 1 and not r.errors
    q = r.questions[0]
    assert q.text == "Какая кость самая длинная?"
    assert q.options == ["Бедренная", "Плечевая", "Большеберцовая", "Лучевая"]
    assert q.correct == 0


def test_lettered_template():
    r = parse_text(TEMPLATE_TXT)
    assert r.fmt == "lettered"
    assert len(r.questions) == 2 and not r.errors
    assert r.questions[0].text == "Какая кость самая длинная в теле человека?"
    assert r.questions[0].options == ["Бедренная", "Плечевая", "Большеберцовая", "Лучевая"]
    assert r.questions[0].correct == 0
    assert r.questions[1].correct == 2


def test_lettered_no_blank_lines_and_star_before_letter():
    # как в реальном файле: вопросы подряд без пустых строк, правильный «*B)»
    text = (
        "1. Первый вопрос?\nA) красный\n*B) зелёный\nC) синий\nD) жёлтый\n"
        "2. Второй вопрос?\n*A) один\nB) два\nC) три\n"
    )
    r = parse_text(text)
    assert not r.errors and len(r.questions) == 2
    assert r.questions[0].correct == 1 and r.questions[0].options[1] == "зелёный"
    assert r.questions[1].correct == 0


def test_lettered_errors():
    text = (
        "1. Без правильного\nA) a\nB) b\n"
        "2. Два правильных\n*A) a\n*B) b\n"
        "3. Нормальный\nA) a\n*B) b\n"
    )
    r = parse_text(text)
    assert len(r.questions) == 1
    msgs = {e.number: e.message for e in r.errors}
    assert "не отмечен" in msgs[1]
    assert "2 правильных" in msgs[2]


def test_plus_minus_without_numbers_and_multiline():
    text = """Вопрос без номера
вторая строка вопроса
- нет
+ да

1) Второй вопрос?
+ A
- B
"""
    r = parse_text(text)
    assert not r.errors
    assert r.questions[0].text == "Вопрос без номера\nвторая строка вопроса"
    assert r.questions[0].correct == 1
    assert r.questions[1].text == "Второй вопрос?"


def test_plus_minus_errors_reported_with_numbers():
    text = """1. Без правильного
- a
- b
2. Два правильных
+ a
+ b
3. Один вариант
+ a
4. Нормальный
+ a
- b
5. Одинаковые
+ a
- A
"""
    r = parse_text(text)
    assert len(r.questions) == 1
    msgs = {e.number: e.message for e in r.errors}
    assert "не отмечен" in msgs[1]
    assert "2 правильных" in msgs[2]
    assert "минимум 2" in msgs[3]
    assert "одинаковые" in msgs[5]


def test_header_text_before_first_question_is_ignored():
    text = "Тест по анатомии, 2 курс\n1. Вопрос?\n+ да\n- нет\n"
    r = parse_text(text)
    assert not r.errors and len(r.questions) == 1
    assert r.questions[0].text == "Вопрос?"


def test_question_without_options_in_middle_is_error():
    text = "1. A?\n+ a\n- b\n2. Пустой вопрос\n3. C?\n+ x\n- y\n"
    r = parse_text(text)
    assert len(r.questions) == 2
    assert r.errors[0].number == 2


def test_dash_variants():
    r = parse_text("Q?\n+ да\n– нет\n− тоже нет\n")
    assert r.questions[0].options == ["да", "нет", "тоже нет"]


def test_hemis_format():
    text = """++++
Самая длинная кость?
====
#Бедренная
====
Плечевая
====
Лучевая
++++
Сколько камер в сердце?
====
2
====
#4
++++
Без ответа
====
a
====
b
"""
    r = parse_text(text)
    assert r.fmt == "hemis"
    assert len(r.questions) == 2
    assert r.questions[0].correct == 0 and r.questions[0].options[0] == "Бедренная"
    assert r.questions[1].correct == 1
    assert r.errors[0].number == 3


def _docx(lines, table=None):
    d = Document()
    for line in lines:
        d.add_paragraph(line)
    if table:
        t = d.add_table(rows=len(table), cols=1)
        for i, v in enumerate(table):
            t.cell(i, 0).text = v
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_docx():
    data = _docx(["1. Вопрос?", "+ да", "- нет", "2. Второй?", "- x", "+ y"])
    r = parse_file("test.docx", data)
    assert len(r.questions) == 2 and not r.errors


def test_docx_table_content():
    data = _docx([], table=["Вопрос в таблице?", "+ да", "- нет"])
    r = parse_file("t.docx", data)
    assert len(r.questions) == 1


def test_templates_parse_cleanly():
    r1 = parse_file("t.docx", template_docx())
    r2 = parse_file("t.xlsx", template_xlsx())
    assert len(r1.questions) == 2 and not r1.errors
    assert len(r2.questions) == 2 and not r2.errors


def test_xlsx_answer_variants():
    wb = Workbook()
    ws = wb.active
    ws.append(["Вопрос", "A", "B", "C", "Ответ"])
    ws.append(["Буква?", "x", "y", "z", "B"])
    ws.append(["Цифра?", "x", "y", "z", 3])
    ws.append(["Текст?", "x", "y", "z", "x"])
    ws.append(["Кириллица?", "x", "y", "z", "В"])
    ws.append(["Плохой ответ?", "x", "y", "z", "Q"])
    ws.append(["Два варианта", "x", "y", None, "1"])
    buf = io.BytesIO()
    wb.save(buf)
    r = parse_file("t.xlsx", buf.getvalue())
    # кириллическая «В» — третья буква (А, Б, В), латинская «B» — вторая
    assert [q.correct for q in r.questions] == [1, 2, 0, 2, 0]
    assert r.questions[-1].options == ["x", "y"]
    assert len(r.errors) == 1 and r.errors[0].number == 5


def test_txt_cp1251():
    r = parse_file("t.txt", "Вопрос?\n+ да\n- нет\n".encode("cp1251"))
    assert r.questions[0].options == ["да", "нет"]


def test_bad_files():
    with pytest.raises(ParseFailed):
        parse_file("x.docx", b"not a docx")
    with pytest.raises(ParseFailed):
        parse_file("x.xlsx", b"not xlsx")
    with pytest.raises(ParseFailed):
        parse_file("x.doc", b"...")
    with pytest.raises(ParseFailed):
        parse_file("x.pdf", b"...")


def test_large_file_performance():
    import time

    text = "\n".join(f"{i}. Вопрос номер {i}?\n+ верно\n- нет\n- тоже нет\n- мимо" for i in range(1, 2001))
    t = time.perf_counter()
    r = parse_text(text)
    assert len(r.questions) == 2000
    assert time.perf_counter() - t < 2
