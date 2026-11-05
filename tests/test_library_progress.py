from app import services as svc
from app.models import LibraryDoc


async def _make_doc(db, filename="book.pdf", text="полный текст книги"):
    await svc.get_or_create_user(db, 1, "t")
    d = LibraryDoc(subject_id=1, title="Книга", filename=filename, content_type="application/pdf",
                   size=10, path="/tmp/x", text=text, uploaded_by=1, status="approved")
    db.add(d)
    await db.commit()
    return d


async def test_pdf_doc_omits_heavy_text(db):
    # Для PDF текст не отдаём (он на мегабайты и не нужен — книга рисуется из файла).
    d = await _make_doc(db, filename="book.pdf", text="x" * 10000)
    info = await svc.get_library_doc(db, d.id)
    assert info["is_pdf"] is True
    assert info["text"] == ""


async def test_non_pdf_doc_keeps_text(db):
    d = await _make_doc(db, filename="lecture.txt", text="конспект")
    info = await svc.get_library_doc(db, d.id)
    assert info["is_pdf"] is False
    assert info["text"] == "конспект"


async def test_library_progress_remembers_page_per_user(db):
    d = await _make_doc(db)
    u1 = await svc.get_or_create_user(db, 101, "a")
    u2 = await svc.get_or_create_user(db, 102, "b")
    # пока ничего не сохранено
    assert await svc.get_library_progress(db, u1.id, d.id) == 0
    # сохраняем страницу для первого читателя
    await svc.set_library_progress(db, u1.id, d.id, 42)
    assert await svc.get_library_progress(db, u1.id, d.id) == 42
    # у второго — своя (независимая) позиция
    assert await svc.get_library_progress(db, u2.id, d.id) == 0
    # повторное сохранение обновляет ту же строку, а не плодит новые
    await svc.set_library_progress(db, u1.id, d.id, 55)
    assert await svc.get_library_progress(db, u1.id, d.id) == 55
