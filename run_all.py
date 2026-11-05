"""Запуск в один клик: cloudflared-туннель + сервер Mini App + бот.

Весь вывод дублируется в файл run_all.log (для диагностики). Закрытие окна (Ctrl+C)
гасит и туннель, и сервер. Адрес *.trycloudflare.com новый при каждом запуске —
скрипт подставляет его автоматически в WEBAPP_URL.
"""
import os
import re
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = os.getenv("PORT", "8080")
CF = HERE / "cloudflared.exe"
VENV_PY = HERE / ".venv" / "Scripts" / "python.exe"
URL_RE = re.compile(r"https://[-a-z0-9]+\.trycloudflare\.com")
LOG = open(HERE / "run_all.log", "w", encoding="utf-8")


def log(msg=""):
    line = str(msg)
    print(line)
    try:
        LOG.write(line + "\n")
        LOG.flush()
    except Exception:
        pass


def _update_env(url: str):
    env_path = HERE / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    out, found = [], False
    for ln in lines:
        if ln.strip().startswith("WEBAPP_URL="):
            out.append(f"WEBAPP_URL={url}")
            found = True
        else:
            out.append(ln)
    if not found:
        out.append(f"WEBAPP_URL={url}")
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _drain(stream):
    for _ in stream:
        pass


def main():
    log(f"[{datetime.now():%H:%M:%S}] Старт. Папка: {HERE}")
    if not CF.exists():
        log("ОШИБКА: не найден cloudflared.exe рядом со скриптом.")
        return
    if not VENV_PY.exists():
        log(f"ВНИМАНИЕ: не найден {VENV_PY} — сначала запустите setup.bat.")

    log("Поднимаю туннель cloudflared…")
    try:
        cf = subprocess.Popen(
            [str(CF), "tunnel", "--url", f"http://localhost:{PORT}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
        )
    except Exception as e:
        log(f"ОШИБКА запуска cloudflared.exe: {e}")
        log("Возможно, файл заблокирован антивирусом/Windows. Разблокируйте cloudflared.exe в свойствах файла.")
        return

    url = None
    start = time.time()
    while time.time() - start < 45:
        line = cf.stdout.readline()
        if not line:
            if cf.poll() is not None:
                log("cloudflared завершился раньше времени (код %s)." % cf.returncode)
                break
            continue
        line = line.rstrip()
        if line:
            log("  cf| " + line)
        m = URL_RE.search(line)
        if m:
            url = m.group(0)
            break
    if not url:
        log("ОШИБКА: не удалось получить адрес туннеля за 45 c (см. строки 'cf|' выше).")
        log("Проверьте интернет и что cloudflared.exe не заблокирован.")
        try:
            cf.terminate()
        except Exception:
            pass
        return

    log("")
    log(f"  Адрес Mini App: {url}")
    log("")
    _update_env(url)
    threading.Thread(target=_drain, args=(cf.stdout,), daemon=True).start()

    env = os.environ.copy()
    env["WEBAPP_URL"] = url  # переопределяет значение из .env для дочернего процесса
    env["PYTHONUTF8"] = "1"
    python = str(VENV_PY) if VENV_PY.exists() else sys.executable

    log("Запускаю сервер и бота…  (Ctrl+C — остановить всё)")
    log("")
    server = subprocess.Popen(
        [python, "-m", "app.main"],
        cwd=str(HERE),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
    )
    try:
        for line in server.stdout:
            log(line.rstrip())
    except KeyboardInterrupt:
        pass
    finally:
        for p in (server, cf):
            try:
                p.terminate()
            except Exception:
                pass
    log("Остановлено.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("НЕОБРАБОТАННАЯ ОШИБКА:\n" + traceback.format_exc())
    finally:
        try:
            LOG.close()
        except Exception:
            pass
