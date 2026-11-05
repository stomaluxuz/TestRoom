"""Разбор файлов с тестами без нейросети.

Поддерживаемые форматы:

1) Простой («плюс-минус»), .docx или .txt:
       1. Самая длинная кость?
       + Бедренная
       - Плечевая
   Номер вопроса необязателен (автонумерация Word не попадает в текст — это нормально).

2) Формат систем тестирования (HEMIS и похожие):
       ++++
       Самая длинная кость?
       ====
       #Бедренная
       ====
       Плечевая

3) Excel (.xlsx): Вопрос | Вариант A | Вариант B | ... | Ответ
   Ответ — буква (A, B, ...), номер (1, 2, ...) или точный текст варианта.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

OPTION_RE = re.compile(r"^\s*([+\-−–])\s*(.*\S)\s*$")
# Буквенный формат: «A) вариант», правильный помечается звёздочкой перед буквой: «*B) вариант».
LETTER_OPTION_RE = re.compile(r"^\s*(\*?)\s*([A-Za-zА-Яа-яЁё])\s*[).]\s+(.*\S)\s*$")
NUMBER_RE = re.compile(r"^\s*\d{1,4}\s*[.)]\s*")
HEMIS_Q_SEP = re.compile(r"^\s*\+{4,}\s*$", re.M)
HEMIS_O_SEP = re.compile(r"^\s*={4,}\s*$", re.M)
LETTERS = "ABCDEFGHIJ"
CYR_LETTERS = "АБВГДЕЖЗИК"

MAX_OPTIONS = 10
MAX_TEXT = 2000


@dataclass
class ParsedQuestion:
    text: str
    options: list[str]
    correct: int  # индекс правильного; -1 — не отмечен


@dataclass
class ParseIssue:
    number: int
    preview: str
    message: str


@dataclass
class ParseResult:
    questions: list[ParsedQuestion] = field(default_factory=list)  # только корректные
    errors: list[ParseIssue] = field(default_factory=list)
    total_found: int = 0
    fmt: str = ""


class ParseFailed(Exception):
    """Файл вообще не удалось прочитать."""


def _preview(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= 60 else text[:57] + "..."


def validate(raw: list[tuple[str, list[str], list[int]]], fmt: str) -> ParseResult:
    """raw: [(текст, варианты, индексы отмеченных правильными)]"""
    res = ParseResult(total_found=len(raw), fmt=fmt)
    for n, (text, options, marked) in enumerate(raw, start=1):
        text = text.strip()
        options = [o.strip() for o in options]
        err = None
        if not text:
            err = "пустой текст вопроса"
        elif len(text) > MAX_TEXT:
            err = "слишком длинный вопрос"
        elif len(options) < 2:
            err = f"вариантов ответа: {len(options)}, нужно минимум 2"
        elif len(options) > MAX_OPTIONS:
            err = f"вариантов ответа: {len(options)}, максимум {MAX_OPTIONS}"
        elif any(not o for o in options):
            err = "есть пустой вариант ответа"
        elif len({o.lower() for o in options}) != len(options):
            err = "есть одинаковые варианты ответа"
        elif len(marked) == 0:
            err = "не отмечен правильный ответ"
        elif len(marked) > 1:
            err = f"отмечено {len(marked)} правильных ответа, нужен один"
        if err:
            res.errors.append(ParseIssue(n, _preview(text) or "(без текста)", err))
        else:
            res.questions.append(ParsedQuestion(text, options, marked[0]))
    return res


def parse_plus_minus(text: str) -> ParseResult:
    raw: list[tuple[str, list[str], list[int]]] = []
    q_lines: list[str] = []
    options: list[str] = []
    marked: list[int] = []

    def flush():
        if q_lines or options:
            raw.append(("\n".join(q_lines), list(options), list(marked)))

    for line in text.splitlines():
        if not line.strip():
            continue
        m = OPTION_RE.match(line)
        if m:
            if not q_lines and not options:
                # вариант без вопроса — пропускаем мусор в начале файла
                continue
            if m.group(1) == "+":
                marked.append(len(options))
            options.append(m.group(2))
            continue
        # строка не вариант → либо продолжение вопроса, либо новый вопрос
        numbered = bool(NUMBER_RE.match(line))
        if options:
            flush()
            q_lines, options, marked = [], [], []
        elif q_lines and numbered:
            # предыдущий блок без вариантов: в начале файла это заголовок, дальше — ошибка
            if raw:
                flush()
            q_lines, options, marked = [], [], []
        clean = NUMBER_RE.sub("", line, count=1) if not q_lines else line
        q_lines.append(clean.strip())
    flush()
    return validate(raw, "plus_minus")


def parse_hemis(text: str) -> ParseResult:
    raw = []
    for block in HEMIS_Q_SEP.split(text):
        if not block.strip():
            continue
        parts = HEMIS_O_SEP.split(block)
        question = NUMBER_RE.sub("", parts[0].strip(), count=1)
        options, marked = [], []
        for p in parts[1:]:
            p = p.strip()
            if not p:
                continue
            if p.startswith("#"):
                marked.append(len(options))
                p = p[1:].strip()
            options.append(p)
        raw.append((question, options, marked))
    return validate(raw, "hemis")


def parse_lettered(text: str) -> ParseResult:
    """Варианты с буквами: «A) …», правильный помечен «*» перед буквой: «*B) …».

    Неправильные варианты без знака. Вопрос — строки без буквенной пометки
    (номер «1.» в начале необязателен). Новый вопрос начинается, когда после
    вариантов снова идёт строка-вопрос (или пустая строка).
    """
    raw: list[tuple[str, list[str], list[int]]] = []
    q_lines: list[str] = []
    options: list[str] = []
    marked: list[int] = []

    def flush():
        if q_lines or options:
            raw.append(("\n".join(q_lines), list(options), list(marked)))

    for line in text.splitlines():
        if not line.strip():
            if options:
                flush()
                q_lines, options, marked = [], [], []
            continue
        m = LETTER_OPTION_RE.match(line)
        if m:
            if not q_lines and not options:
                continue  # вариант до вопроса — мусор в начале файла
            if m.group(1) == "*":
                marked.append(len(options))
            options.append(m.group(3).strip())
            continue
        # строка без буквенной пометки → продолжение вопроса либо новый вопрос
        if options:
            flush()
            q_lines, options, marked = [], [], []
        clean = NUMBER_RE.sub("", line, count=1) if not q_lines else line
        q_lines.append(clean.strip())
    flush()
    return validate(raw, "lettered")


def parse_text(text: str) -> ParseResult:
    text = text.replace("\r\n", "\n").replace("﻿", "")
    if HEMIS_Q_SEP.search(text) and HEMIS_O_SEP.search(text):
        return parse_hemis(text)
    if sum(1 for ln in text.splitlines() if LETTER_OPTION_RE.match(ln)) >= 2:
        return parse_lettered(text)
    return parse_plus_minus(text)


def docx_to_text(data: bytes) -> str:
    try:
        from docx import Document

        doc = Document(io.BytesIO(data))
    except Exception as e:  # повреждённый или не тот файл
        raise ParseFailed("Не удалось открыть Word-файл. Сохраните его как .docx и попробуйте снова.") from e
    lines: list[str] = []
    for p in doc.paragraphs:
        # переносы строк внутри абзаца (Shift+Enter) тоже считаем строками
        lines.extend(p.text.split("\n"))
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                lines.extend(cell.text.split("\n"))
    return "\n".join(lines)


def pdf_to_text(data: bytes) -> str:
    """Текст из PDF (pypdf). Для сканов без текстового слоя вернёт пусто — это нормально."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
    except Exception as e:
        raise ParseFailed("Не удалось открыть PDF-файл.") from e
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            pass
    return "\n".join(parts)


def extract_document_text_path(filename: str, path: str) -> str:
    """Как extract_document_text, но читает файл с диска (PDF — не загружая целиком в память)."""
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader

            reader = PdfReader(path)
        except Exception as e:
            raise ParseFailed("Не удалось открыть PDF-файл.") from e
        parts = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                pass
        return "\n".join(parts)
    with open(path, "rb") as f:  # docx/txt обычно небольшие
        return extract_document_text(filename, f.read())


def extract_document_text(filename: str, data: bytes) -> str:
    """Извлечь текст из документа библиотеки (.pdf / .docx / .txt). Для поиска и генерации."""
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        return pdf_to_text(data)
    if name.endswith(".docx"):
        return docx_to_text(data)
    if name.endswith((".txt", ".md")):
        for enc in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="ignore")
    raise ParseFailed("Поддерживаются файлы .pdf, .docx и .txt.")


def _answer_index(value, options: list[str]) -> int | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    up = s.upper().rstrip(").")
    if len(up) == 1 and up in LETTERS[: len(options)]:
        return LETTERS.index(up)
    if len(up) == 1 and up in CYR_LETTERS[: len(options)]:
        return CYR_LETTERS.index(up)
    if re.fullmatch(r"\d+(\.0)?", s):
        n = int(float(s))
        if 1 <= n <= len(options):
            return n - 1
    for i, o in enumerate(options):
        if o.strip().lower() == s.lower():
            return i
    return None


def parse_xlsx(data: bytes) -> ParseResult:
    try:
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:
        raise ParseFailed("Не удалось открыть Excel-файл (.xlsx).") from e
    ws = wb.worksheets[0]
    raw = []
    first = True
    for row in ws.iter_rows(values_only=True):
        cells = ["" if v is None else str(v).strip() for v in row]
        while cells and not cells[-1]:
            cells.pop()
        if not any(cells):
            continue
        if len(cells) < 2:
            raw.append((cells[0] if cells else "", [], []))
            continue
        question, middle, answer = cells[0], cells[1:-1], cells[-1]
        options = [c for c in middle if c]
        idx = _answer_index(answer, options)
        if first:
            first = False
            if idx is None and question.lower().startswith(("вопрос", "savol", "question")):
                continue  # строка заголовков
        raw.append((question, options, [] if idx is None else [idx]))
    wb.close()
    return validate(raw, "xlsx")


def parse_file(filename: str, data: bytes) -> ParseResult:
    name = filename.lower()
    if name.endswith(".xlsx"):
        return parse_xlsx(data)
    if name.endswith(".docx"):
        return parse_text(docx_to_text(data))
    if name.endswith(".txt"):
        for enc in ("utf-8", "cp1251"):
            try:
                return parse_text(data.decode(enc))
            except UnicodeDecodeError:
                continue
        raise ParseFailed("Не удалось прочитать кодировку .txt файла. Сохраните его в UTF-8.")
    if name.endswith(".doc"):
        raise ParseFailed("Старый формат .doc не поддерживается. Откройте файл в Word и сохраните как .docx.")
    raise ParseFailed("Поддерживаются файлы .docx, .xlsx и .txt.")


# ---------- шаблоны для учителей ----------

TEMPLATE_TXT = """1. Какая кость самая длинная в теле человека?
*A) Бедренная
B) Плечевая
C) Большеберцовая
D) Лучевая

2. Сколько камер в сердце человека?
A) 2
B) 3
*C) 4
D) 5
"""


def template_docx() -> bytes:
    from docx import Document

    doc = Document()
    doc.add_paragraph("Шаблон теста. Варианты помечайте буквами A) B) C)…, правильный — звёздочкой * перед буквой.")
    doc.add_paragraph("")
    for line in TEMPLATE_TXT.splitlines():
        doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def template_xlsx() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Тест"
    ws.append(["Вопрос", "Вариант A", "Вариант B", "Вариант C", "Вариант D", "Ответ"])
    ws.append(["Какая кость самая длинная в теле человека?", "Бедренная", "Плечевая", "Большеберцовая", "Лучевая", "A"])
    ws.append(["Сколько камер в сердце человека?", "2", "3", "4", "5", "C"])
    ws.column_dimensions["A"].width = 50
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
