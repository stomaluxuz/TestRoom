"""Нагрузочный тест: N студентов одновременно проходят тест через API Mini App.

Запуск (сервер уже должен работать):
    python loadtest/load_test.py --url http://127.0.0.1:8080 --students 300 --questions 25

BOT_TOKEN и ADMIN_IDS берутся из .env — скрипт подписывает запросы так же, как Telegram.
Первый ID из ADMIN_IDS используется как преподаватель (у админа нет лимитов бесплатного тарифа).

--think N — пауза между ответами в секундах (0 — стресс-тест на пределе).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.auth import make_init_data  # noqa: E402
from app.config import settings  # noqa: E402

LAT: dict[str, list[float]] = defaultdict(list)
ERRORS: dict[str, int] = defaultdict(int)
ERROR_SAMPLES: list[str] = []
ERROR_KINDS: Counter = Counter()
RETRIES: Counter = Counter()


_HEADERS: dict[int, dict] = {}


def h(uid: int) -> dict:
    if uid not in _HEADERS:
        _HEADERS[uid] = {"X-Init-Data": make_init_data(settings.bot_token, {"id": uid, "first_name": "Load"})}
    return _HEADERS[uid]


async def call(client: aiohttp.ClientSession, name: str, method: str, url: str, files=None, data=None, **kw):
    if files:
        form = aiohttp.FormData()
        for k, v in (data or {}).items():
            form.add_field(k, str(v))
        for k, (fname, content, ctype) in files.items():
            form.add_field(k, content, filename=fname, content_type=ctype)
        kw["data"] = form
    t = time.perf_counter()
    for attempt in range(3):  # как в приложении: повтор при обрыве связи
        try:
            async with client.request(method, url, **kw) as r:
                body = await r.read()
                status = r.status
            break
        except (aiohttp.ServerDisconnectedError, aiohttp.ClientOSError) as e:
            if attempt == 2 or files:
                ERRORS[name] += 1
                ERROR_KINDS[f"{name}: {type(e).__name__}"] += 1
                return None
            RETRIES[name] += 1
            await asyncio.sleep(0.4 * (attempt + 1))
        except Exception as e:
            ERRORS[name] += 1
            ERROR_KINDS[f"{name}: {type(e).__name__}"] += 1
            return None
    LAT[name].append(time.perf_counter() - t)
    if status >= 400:
        ERRORS[name] += 1
        try:
            detail = json.loads(body).get("detail", "")
        except Exception:
            detail = body[:80].decode(errors="replace")
        ERROR_KINDS[f"{name}: {status} {detail}"] += 1
        return None
    return json.loads(body)


async def setup(client, teacher_id: int, n_questions: int, n_students: int) -> tuple[int, str]:
    T = h(teacher_id)
    await call(client, "setup", "POST", "/api/me/name", headers=T, json={"full_name": "Нагрузочный Учитель"})
    subj = await call(client, "setup", "POST", "/api/teacher/subjects", headers=T, json={"name": "Нагрузка"})
    text = "\n".join(
        f"{i}. Вопрос номер {i}, достаточно длинный текст, как в настоящем тесте по анатомии?\n"
        f"+ Верный ответ {i}\n- Неверный вариант {i}a\n- Неверный вариант {i}b\n- Неверный вариант {i}c"
        for i in range(1, n_questions * 2 + 1)
    )
    up = await call(
        client,
        "setup",
        "POST",
        "/api/teacher/tests/upload",
        headers=T,
        data={"subject_id": subj["id"], "title": f"Нагрузка {int(time.time())}"},
        files={"file": ("load.txt", text.encode(), "text/plain")},
    )
    if not up or not up.get("saved"):
        raise SystemExit(f"Не удалось загрузить тест: {up} {dict(ERROR_KINDS)}")
    sess = await call(
        client,
        "setup",
        "POST",
        "/api/teacher/sessions",
        headers=T,
        json={
            "test_id": up["test_id"],
            "group_name": "LOAD",
            "duration_min": 120,
            "question_count": n_questions,
            "max_leaves": 0,
            "max_students": 0,
        },
    )
    return sess["id"], sess["code"]


async def student(client, uid: int, code: str, think: float, start_evt: asyncio.Event, done: list):
    H = h(uid)
    await call(client, "name", "POST", "/api/me/name", headers=H, json={"full_name": f"Студент Нагрузочный {uid}"})
    await start_evt.wait()  # все входят одновременно — как после слов учителя «код такой-то»
    st = await call(client, "join", "POST", "/api/student/join", headers=H, json={"code": code})
    if not st:
        return
    while st and st.get("status") == "active":
        if think:
            await asyncio.sleep(random.uniform(think * 0.5, think * 1.5))
        n = len(st["question"]["options"])
        st = await call(
            client,
            "answer",
            "POST",
            f"/api/student/attempts/{st['attempt_id']}/answer",
            headers=H,
            json={"question_id": st["question"]["id"], "option_index": random.randrange(n)},
        )
    if st and st.get("status") == "finished":
        done.append(uid)


async def teacher_poll(client, teacher_id: int, session_id: int, stop: asyncio.Event):
    T = h(teacher_id)
    while not stop.is_set():
        await call(client, "teacher_live", "GET", f"/api/teacher/sessions/{session_id}/live", headers=T)
        try:
            await asyncio.wait_for(stop.wait(), 3)
        except asyncio.TimeoutError:
            pass


def pct(values, p):
    if not values:
        return 0
    values = sorted(values)
    k = min(len(values) - 1, int(round(p / 100 * (len(values) - 1))))
    return values[k]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8080")
    ap.add_argument("--students", type=int, default=100)
    ap.add_argument("--questions", type=int, default=25)
    ap.add_argument("--think", type=float, default=0.0)
    ap.add_argument("--uid-base", type=int, default=10_000_000)
    args = ap.parse_args()

    if not settings.bot_token or not settings.admin_ids:
        raise SystemExit("Нужны BOT_TOKEN и ADMIN_IDS в .env (те же, что у сервера).")
    teacher_id = sorted(settings.admin_ids)[0]

    connector = aiohttp.TCPConnector(limit=0)
    timeout = aiohttp.ClientTimeout(total=120)
    async with aiohttp.ClientSession(base_url=args.url, connector=connector, timeout=timeout) as client:
        session_id, code = await setup(client, teacher_id, args.questions, args.students)
        LAT.clear()
        ERRORS.clear()
        print(f"Запуск {session_id}, код {code}. Студентов: {args.students}, вопросов: {args.questions}")

        start_evt, stop = asyncio.Event(), asyncio.Event()
        done: list[int] = []
        base = args.uid_base + random.randrange(10**6) * 1000
        tasks = [
            asyncio.create_task(student(client, base + i, code, args.think, start_evt, done))
            for i in range(args.students)
        ]
        await asyncio.sleep(1.0)  # все успели указать ФИО
        LAT.pop("name", None)
        poller = asyncio.create_task(teacher_poll(client, teacher_id, session_id, stop))
        t0 = time.perf_counter()
        start_evt.set()
        await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - t0
        stop.set()
        await poller

        live = await call(client, "check", "GET", f"/api/teacher/sessions/{session_id}/live", headers=h(teacher_id))

    total_req = sum(len(v) for k, v in LAT.items() if k in ("join", "answer", "teacher_live"))
    print(f"\nВремя: {elapsed:.1f} с   Запросов: {total_req}   Пропускная способность: {total_req / elapsed:.0f} запросов/с")
    print(f"Завершили тест: {len(done)} из {args.students}   (сервер видит: {live and live['finished_count']})")
    print(f"\n{'операция':<14}{'кол-во':>8}{'p50, мс':>10}{'p95, мс':>10}{'p99, мс':>10}{'макс, мс':>10}{'ошибок':>8}")
    for name in ("join", "answer", "teacher_live"):
        v = LAT.get(name, [])
        if not v and not ERRORS.get(name):
            continue
        print(
            f"{name:<14}{len(v):>8}{pct(v, 50) * 1000:>10.0f}{pct(v, 95) * 1000:>10.0f}"
            f"{pct(v, 99) * 1000:>10.0f}{(max(v) if v else 0) * 1000:>10.0f}{ERRORS.get(name, 0):>8}"
        )
    if RETRIES:
        print(f"\nПовторов после обрыва связи: {sum(RETRIES.values())} (все прошли успешно, если ошибок 0)")
    if ERROR_KINDS:
        print("\nОшибки:")
        for k, v in ERROR_KINDS.most_common(8):
            print(f"  {v} × {k}")
    ans = LAT.get("answer", [])
    return {
        "students": args.students,
        "elapsed": elapsed,
        "rps": total_req / elapsed if elapsed else 0,
        "answer_p50": pct(ans, 50),
        "answer_p95": pct(ans, 95),
        "join_p95": pct(LAT.get("join", []), 95),
        "errors": sum(ERRORS.values()),
        "done": len(done),
    }


if __name__ == "__main__":
    asyncio.run(main())
