import hashlib

from sqlalchemy import func, select

from app import ai, embeddings, services as svc
from app.config import settings
from app.models import LibraryChunk, LibraryDoc


# ---- детерминированный фейковый эмбеддер (bag-of-words хэш в 64 измерения) ----
async def fake_embed(texts, input_type="document", client=None, max_retries=5, pace=0.0):
    out = []
    for t in texts:
        v = [0.0] * 64
        for w in (t or "").lower().split():
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1.0
        out.append(v)
    return out


CARIES = ("кариес кариес эмаль эмаль фтор фтор бактерии профилактика зубов деминерализация "
          "стрептококк налёт реминерализация герметизация " * 6)
ROME = ("рим рим сенат республика цезарь империя легион консул август форум колизей "
        "патриции плебеи " * 6)


# ---------------------------------------------------------------- юнит: нарезка/векторы

def test_chunk_text_splits_and_filters():
    assert embeddings.chunk_text("") == []
    assert embeddings.chunk_text("кор") == []  # короче 30 символов — отбрасываем
    long = ("Предложение раз. " * 400)  # ~6800 символов → несколько кусков
    chunks = embeddings.chunk_text(long, target_chars=2000)
    assert len(chunks) >= 3
    assert all(len(c) <= 2600 for c in chunks)  # target + небольшой нахлёст


def test_vector_pack_cosine():
    import math

    v = [3.0, 4.0] + [0.0] * 62
    blob = embeddings.pack(v)
    back = embeddings.unpack(blob)
    assert len(back) == 64
    # нормализован: длина = 1
    assert abs(math.sqrt(sum(x * x for x in back)) - 1.0) < 1e-5
    # косинус сам с собой = 1, с ортогональным = 0
    a = embeddings.normalize([1.0, 0.0, 0.0])
    b = embeddings.normalize([0.0, 1.0, 0.0])
    assert abs(embeddings.dot(a, a) - 1.0) < 1e-6
    assert abs(embeddings.dot(a, b)) < 1e-6


def test_is_enabled_toggles():
    old = settings.voyage_api_key
    try:
        settings.voyage_api_key = ""
        assert embeddings.is_enabled() is False
        settings.voyage_api_key = "k"
        assert embeddings.is_enabled() is True
    finally:
        settings.voyage_api_key = old


def test_context_block():
    assert ai._context_block("") == ""
    b = ai._context_block("выдержка про кариес")
    assert "МАТЕРИАЛЫ БИБЛИОТЕКИ" in b and "кариес" in b


# ---------------------------------------------------------------- интеграция: индекс + поиск

async def _mk_doc(db, title, text, subj=1):
    d = LibraryDoc(subject_id=subj, title=title, filename="f.txt", content_type="text/plain",
                   size=len(text), path="", text=text, uploaded_by=1, status="approved")
    db.add(d)
    await db.commit()
    return d


async def test_rag_index_search_delete(db, monkeypatch):
    settings.voyage_api_key = "test"
    monkeypatch.setattr(embeddings, "embed_texts", fake_embed)
    await svc.get_or_create_user(db, 1, "teacher")  # для FK uploaded_by

    da = await _mk_doc(db, "Кариес зубов", CARIES)
    dbo = await _mk_doc(db, "История Рима", ROME)

    # бэкофилл индексирует оба
    res = await svc.reindex_library(db)
    assert res["indexed"] == 2 and res["chunks"] >= 2

    # повторный бэкофилл — пропускает уже проиндексированные
    res2 = await svc.reindex_library(db)
    assert res2["indexed"] == 0 and res2["skipped"] == 2

    # запрос про кариес → источник «Кариес зубов» выше «Истории Рима»
    ctx = await svc.library_context(db, "кариес эмаль фтор профилактика", min_score=0.0)
    assert ctx["found"] is True
    assert ctx["sources"][0] == "Кариес зубов"

    # высокий порог → релевантного «нет»
    ctx_hi = await svc.library_context(db, "совершенно посторонняя тема про космос", min_score=0.99)
    assert ctx_hi["found"] is False

    # удаление документа убирает его куски
    await svc.delete_library_doc(db, da.id)
    cnt = await db.scalar(select(func.count()).select_from(LibraryChunk).where(LibraryChunk.doc_id == da.id))
    assert cnt == 0


async def test_rag_disabled_returns_empty(db):
    settings.voyage_api_key = ""  # RAG выключен
    ctx = await svc.library_context(db, "кариес")
    assert ctx == {"found": False, "context": "", "sources": [], "score": 0.0}


async def test_decide_library_doc_indexes_on_approve(db, monkeypatch):
    settings.voyage_api_key = "test"
    monkeypatch.setattr(embeddings, "embed_texts", fake_embed)
    await svc.get_or_create_user(db, 1, "teacher")
    d = LibraryDoc(subject_id=1, title="Пародонтит", filename="p.txt", content_type="text/plain",
                   size=len(CARIES), path="", text=CARIES, uploaded_by=1, status="pending")
    db.add(d)
    await db.commit()
    await svc.decide_library_doc(db, d.id, approve=True, admin_id=1)
    cnt = await db.scalar(select(func.count()).select_from(LibraryChunk).where(LibraryChunk.doc_id == d.id))
    assert cnt >= 1
