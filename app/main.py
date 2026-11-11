"""Точка входа: запускает сервер Mini App, Telegram-бота и фоновую задачу закрытия тестов.

WEB_WORKERS=N (только Linux) — запустить N процессов веб-сервера на одном порту,
чтобы использовать все ядра процессора. Бот и фоновая задача работают в главном процессе.
"""
import asyncio
import logging
import multiprocessing as mp
import os
import signal
import socket
import threading
import time

import uvicorn

from . import db as dbmod
from . import services as svc
from .api import bot_ref, create_app
from .config import settings

log = logging.getLogger("main")
WEB_WORKERS = int(os.getenv("WEB_WORKERS", "1"))


async def closer_loop(bot=None, interval: int = 5):
    """Каждые несколько секунд закрывает тесты, у которых вышло время."""
    while True:
        try:
            async with dbmod.SessionLocal() as db:
                closed = await svc.close_expired_sessions(db)
            if closed and bot is not None:
                from .bot import notify_finished

                await notify_finished(bot, closed)
        except Exception:
            log.exception("Ошибка в фоновой задаче")
        await asyncio.sleep(interval)


def _multi() -> bool:
    return WEB_WORKERS > 1 and hasattr(socket, "SO_REUSEPORT")


def _make_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if _multi():
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)  # ядро делит соединения между процессами
    sock.bind((settings.host, settings.port))
    sock.listen(2048)
    sock.setblocking(False)
    return sock


def _server() -> uvicorn.Server:
    return uvicorn.Server(
        uvicorn.Config(
            create_app(),
            log_level="warning",
            proxy_headers=True,
            forwarded_allow_ips="*",
            timeout_keep_alive=75,  # студент думает над вопросом дольше 5 секунд — соединение не рвём
        )
    )


async def _web_only():
    if settings.run_bot and settings.bot_token:
        from .bot import create_bot

        bot_ref.bot, _ = create_bot()  # только для отправки файлов, без приёма сообщений
    await _server().serve(sockets=[_make_socket()])


def _die_with_parent(parent_pid: int):
    """Дочерний процесс не должен пережить главный (иначе он продолжит занимать порт)."""
    try:  # Linux: ядро само пришлёт SIGTERM, когда главный процесс умрёт
        import ctypes

        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG
    except Exception:
        pass

    def watch():
        while True:
            if os.getppid() != parent_pid:
                os._exit(0)
            time.sleep(1)

    threading.Thread(target=watch, daemon=True).start()


def _web_worker(parent_pid: int):
    logging.basicConfig(level=logging.WARNING)
    _die_with_parent(parent_pid)
    try:
        asyncio.run(_web_only())
    except KeyboardInterrupt:
        pass


async def run():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    await dbmod.init_db()

    workers = []
    if _multi():
        ctx = mp.get_context("spawn")
        for _ in range(WEB_WORKERS - 1):
            p = ctx.Process(target=_web_worker, args=(os.getpid(),), daemon=True)
            p.start()
            workers.append(p)
        log.info("Процессов веб-сервера: %s", WEB_WORKERS)
    elif WEB_WORKERS > 1:
        log.warning("WEB_WORKERS > 1 работает только на Linux, запускаю один процесс.")

    web = _server()
    web_task = asyncio.create_task(web.serve(sockets=[_make_socket()]), name="web")
    tasks = [web_task]
    bot = None
    if settings.run_bot:
        if not settings.bot_token:
            raise SystemExit("Укажите BOT_TOKEN в файле .env")
        from .bot import create_bot, setup_bot

        bot, dp = create_bot()
        bot_ref.bot = bot
        await setup_bot(bot)
        tasks.append(asyncio.create_task(dp.start_polling(bot, handle_signals=False), name="bot"))
        log.info("Бот запущен")
        from .backup import backup_loop

        tasks.append(asyncio.create_task(backup_loop(bot), name="backup"))
    tasks.append(asyncio.create_task(closer_loop(bot), name="closer"))
    if settings.library_figures_enabled:
        from . import figjobs

        figjobs.start()  # фоновый воркер резки иллюстраций из книг
        if settings.library_figures_mode != "night":
            await figjobs.enqueue_pending()  # возобновить задания, прерванные рестартом
        tasks.append(asyncio.create_task(figjobs.night_loop(), name="figures-night"))
        log.info("Иллюстрации из книг: включены, режим=%s", settings.library_figures_mode)
    if settings.ocr_enabled:
        from . import ocr as ocrmod
        from . import ocrjobs

        if ocrmod.tesseract_available():
            ocrjobs.start()  # фоновый воркер распознавания сканов (OCR)
            n = await ocrjobs.enqueue_pending()  # возобновить прерванные рестартом
            log.info("OCR сканов: включён (tesseract найден); в очереди книг=%s", n)
        else:
            log.warning("OCR сканов: включён в настройках, но tesseract не найден — сканы не распознаются.")
    log.info("Сервер Mini App: http://%s:%s", settings.host, settings.port)

    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):  # Windows
            pass
    tasks.append(asyncio.create_task(stop.wait(), name="stop"))

    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        web.should_exit = True  # мягкая остановка: дождаться текущих запросов
        for t in pending:
            if t is not web_task:
                t.cancel()
        if not web_task.done():
            try:
                await asyncio.wait_for(web_task, 10)
            except asyncio.TimeoutError:
                web_task.cancel()
        for t in done:
            if t.get_name() != "stop" and t.exception():
                raise t.exception()
    finally:
        for p in workers:
            p.terminate()
        for p in workers:
            p.join(5)
        if bot is not None:
            await bot.session.close()
        log.info("Сервер остановлен")


def main():
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
