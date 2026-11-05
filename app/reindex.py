"""Бэкофилл RAG: проиндексировать уже одобренные материалы библиотеки.

Запуск (на сервере, где в .env есть VOYAGE_API_KEY):
    python -m app.reindex            # только те, у кого ещё нет кусков
    python -m app.reindex --all      # переиндексировать всё заново
    python -m app.reindex --stats    # только показать таблицу: у каких книг есть текст/куски
    python -m app.reindex --figures          # вырезать иллюстрации из всех одобренных PDF (LIBRARY_FIGURES=1)
    python -m app.reindex --figures-pending  # то же, но только ожидающие книги (для ночного крона)
"""
import asyncio
import sys


async def _print_stats() -> None:
    from sqlalchemy import func, select

    from . import db as dbmod
    from .models import LibraryChunk, LibraryDoc, LibrarySubject

    await dbmod.init_db()
    async with dbmod.SessionLocal() as s:
        subj = dict((await s.execute(select(LibrarySubject.id, LibrarySubject.name))).all())
        docs = (await s.scalars(select(LibraryDoc).where(LibraryDoc.status == "approved")
                                .order_by(LibraryDoc.subject_id))).all()
        print(f"{'ID':>3} {'текст,симв':>10} {'кусков':>7}  предмет / название")
        for d in docs:
            ch = await s.scalar(select(func.count()).select_from(LibraryChunk)
                                .where(LibraryChunk.doc_id == d.id))
            tlen = len(d.text or "")
            mark = "  ❗НЕТ ТЕКСТА (скан?)" if tlen == 0 else ""
            print(f"{d.id:>3} {tlen:>10} {ch:>7}  [{subj.get(d.subject_id,'?')}] {d.title[:50]}{mark}")


async def main() -> None:
    if "--stats" in sys.argv:
        await _print_stats()
        return

    if "--figures" in sys.argv or "--figures-pending" in sys.argv:
        # бэкофилл иллюстраций из книг (только при LIBRARY_FIGURES=1). Тяжело: vision на каждую фигуру.
        # --figures          — все одобренные PDF; --figures-pending — только ожидающие (ночной прогон).
        from . import db as dbmod
        from . import services as svc

        only_pending = "--figures-pending" in sys.argv
        await dbmod.init_db()
        async with dbmod.SessionLocal() as s:
            res = await svc.reindex_figures(s, only_pending=only_pending)
        scope = "ожидающие" if only_pending else "все одобренные"
        print(f"Фигуры ({scope}): книг={res.get('docs', 0)}, фигур={res.get('figures', 0)}"
              + (f", {res['note']}" if res.get('note') else ""))
        return

    from . import db as dbmod
    from . import services as svc
    from .embeddings import is_enabled

    if not is_enabled():
        print("VOYAGE_API_KEY не задан — RAG выключен, индексировать нечего.")
        return
    only_missing = "--all" not in sys.argv
    await dbmod.init_db()
    async with dbmod.SessionLocal() as s:
        res = await svc.reindex_library(s, only_missing=only_missing)
    print(f"Готово: документов проиндексировано={res['indexed']}, "
          f"кусков={res['chunks']}, пропущено={res['skipped']}"
          + (f", {res['note']}" if res.get('note') else ""))
    await _print_stats()


if __name__ == "__main__":
    asyncio.run(main())
