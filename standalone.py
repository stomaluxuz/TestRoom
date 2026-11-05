"""Единая точка входа для сборки в один .exe (PyInstaller).

Внутри exe уже есть Python и все библиотеки. Рядом с exe должны лежать:
  • cloudflared.exe — туннель (если нет, Mini App поднимется без публичного адреса);
  • .env          — настройки (BOT_TOKEN, ADMIN_IDS; WEBAPP_URL впишется сам);
а база testbot.db создаётся/хранится там же.

В отличие от run_all.py здесь всё работает в ОДНОМ процессе: нельзя запускать
дочерний python.exe, которого в собранном exe нет.
"""
import multiprocessing
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path


def app_dir() -> Path:
    """Папка рядом с exe (при обычном запуске — папка скрипта)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def start_tunnel(base: Path) -> tuple[subprocess.Popen | None, str | None]:
    cf = base / "cloudflared.exe"
    port = os.getenv("PORT", "8080")
    if not cf.exists():
        print("cloudflared.exe рядом не найден — запускаю без туннеля (кнопка приложения не появится).")
        return None, None
    print("Поднимаю туннель cloudflared…")
    try:
        proc = subprocess.Popen(
            [str(cf), "tunnel", "--url", f"http://localhost:{port}"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, encoding="utf-8", errors="replace",
        )
    except Exception as e:
        print(f"Не удалось запустить cloudflared.exe: {e}")
        return None, None
    rx = re.compile(r"https://[-a-z0-9]+\.trycloudflare\.com")
    url, start = None, time.time()
    while time.time() - start < 45:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            continue
        m = rx.search(line)
        if m:
            url = m.group(0)
            break
    if url:
        threading.Thread(target=lambda: [None for _ in proc.stdout], daemon=True).start()
        print(f"Адрес Mini App: {url}")
    else:
        print("Не удалось получить адрес туннеля за 45 c — сервер и бот всё равно запустятся.")
    return proc, url


def main():
    base = app_dir()
    os.chdir(base)  # .env и testbot.db — рядом с exe
    os.environ.setdefault("PYTHONUTF8", "1")

    proc, url = start_tunnel(base)
    if url:
        os.environ["WEBAPP_URL"] = url  # важно задать ДО импорта app (config читает env при импорте)

    # Импорт только теперь — чтобы config увидел WEBAPP_URL.
    from app.main import main as app_main
    try:
        app_main()
    finally:
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    multiprocessing.freeze_support()  # защита для собранного exe
    main()
