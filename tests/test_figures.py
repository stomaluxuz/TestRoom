import pytest

from app import figjobs
from app import services as svc
from app.config import settings
from app.models import LibraryDoc


async def _make_pending_pdf(db, title="Книга"):
    await svc.get_or_create_user(db, 1, "t")
    d = LibraryDoc(subject_id=1, title=title, filename="b.pdf", content_type="application/pdf",
                   size=10, path="/tmp/b.pdf", text="x", uploaded_by=1, status="pending")
    db.add(d)
    await db.commit()
    return d


async def test_figures_disabled_by_default(db):
    # по умолчанию флаг выключен → фичи нет, обычное поведение
    assert settings.library_figures_enabled is False
    assert await svc.figure_candidates_for("кариес") == []
    await svc.get_or_create_user(db, 1, "t")
    d = LibraryDoc(subject_id=1, title="Книга", filename="b.pdf", content_type="application/pdf",
                   size=10, path="", text="x", uploaded_by=1, status="approved")
    db.add(d)
    await db.commit()
    assert await svc.index_doc_figures(db, d) == 0  # выключено → 0 фигур


async def test_figure_candidates_empty_when_no_figures(db, monkeypatch):
    monkeypatch.setattr(settings, "library_figures_enabled", True)
    monkeypatch.setattr(settings, "voyage_api_key", "test")

    async def fake_embed(texts, input_type="document", client=None, max_retries=5, pace=0.0):
        return [[0.0] * 8 for _ in texts]

    from app import embeddings
    monkeypatch.setattr(embeddings, "embed_texts", fake_embed)
    svc.invalidate_fig_cache()
    # фигур в БД нет → кандидатов нет
    assert await svc.figure_candidates_for("кариес") == []


async def test_approve_background_sets_pending_and_enqueues(db, monkeypatch):
    # режим background: одобрение помечает книгу pending и КЛАДЁТ в очередь (не режет синхронно)
    monkeypatch.setattr(settings, "library_figures_enabled", True)
    monkeypatch.setattr(settings, "library_figures_mode", "background")
    enq = []
    monkeypatch.setattr(figjobs, "enqueue", lambda doc_id: enq.append(doc_id))
    d = await _make_pending_pdf(db)
    out = await svc.decide_library_doc(db, d.id, approve=True, admin_id=1)
    assert out.status == "approved"
    assert out.figures_status == "pending"
    assert enq == [d.id]  # поставлено в очередь фоновому воркеру
    assert await svc.pending_figure_doc_ids(db) == [d.id]


async def test_approve_night_defers_without_enqueue(db, monkeypatch):
    # режим night: одобрение помечает pending, но в очередь НЕ ставит (ждёт ночного прогона)
    monkeypatch.setattr(settings, "library_figures_enabled", True)
    monkeypatch.setattr(settings, "library_figures_mode", "night")
    enq = []
    monkeypatch.setattr(figjobs, "enqueue", lambda doc_id: enq.append(doc_id))
    d = await _make_pending_pdf(db)
    out = await svc.decide_library_doc(db, d.id, approve=True, admin_id=1)
    assert out.figures_status == "pending"
    assert enq == []  # днём ничего не режем
    assert await svc.pending_figure_doc_ids(db) == [d.id]


async def test_approve_disabled_leaves_status_none(db, monkeypatch):
    # флаг выключен: одобрение не трогает figures_status (фичи нет)
    monkeypatch.setattr(settings, "library_figures_enabled", False)
    d = await _make_pending_pdf(db)
    out = await svc.decide_library_doc(db, d.id, approve=True, admin_id=1)
    assert out.figures_status is None
    assert await svc.pending_figure_doc_ids(db) == []


async def test_worker_processes_pending_to_done(db, monkeypatch):
    monkeypatch.setattr(settings, "library_figures_enabled", True)

    async def fake_index(db_, doc):
        return 3  # как будто вырезали 3 фигуры

    monkeypatch.setattr(svc, "index_doc_figures", fake_index)
    d = await _make_pending_pdf(db)
    d.status = "approved"
    d.figures_status = "pending"
    await db.commit()
    await figjobs._process_one(d.id)
    refreshed = await db.get(LibraryDoc, d.id)
    await db.refresh(refreshed)
    assert refreshed.figures_status == "done"


async def test_worker_marks_error_on_failure(db, monkeypatch):
    monkeypatch.setattr(settings, "library_figures_enabled", True)

    async def boom(db_, doc):
        raise RuntimeError("vision упал")

    monkeypatch.setattr(svc, "index_doc_figures", boom)
    d = await _make_pending_pdf(db)
    d.status = "approved"
    d.figures_status = "pending"
    await db.commit()
    await figjobs._process_one(d.id)
    refreshed = await db.get(LibraryDoc, d.id)
    await db.refresh(refreshed)
    assert refreshed.figures_status == "error"


async def test_reindex_only_pending(db, monkeypatch):
    monkeypatch.setattr(settings, "library_figures_enabled", True)
    monkeypatch.setattr(settings, "voyage_api_key", "test")  # is_enabled() → True

    seen = []

    async def fake_index(db_, doc):
        seen.append(doc.id)
        return 2

    monkeypatch.setattr(svc, "index_doc_figures", fake_index)
    await svc.get_or_create_user(db, 1, "t")
    done = LibraryDoc(subject_id=1, title="A", filename="a.pdf", content_type="application/pdf",
                      size=1, path="/tmp/a.pdf", text="x", uploaded_by=1, status="approved",
                      figures_status="done")
    pend = LibraryDoc(subject_id=1, title="B", filename="b.pdf", content_type="application/pdf",
                      size=1, path="/tmp/b.pdf", text="x", uploaded_by=1, status="approved",
                      figures_status="pending")
    db.add_all([done, pend])
    await db.commit()
    res = await svc.reindex_figures(db, only_pending=True)
    assert seen == [pend.id]  # обработана только ожидающая
    assert res["docs"] == 1 and res["figures"] == 2
    await db.refresh(pend)
    assert pend.figures_status == "done"
