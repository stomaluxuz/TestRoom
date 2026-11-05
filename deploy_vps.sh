#!/usr/bin/env bash
# Выгрузка новой версии TestRoom на VPS и перезапуск бота.
# Запуск из папки проекта:  bash deploy_vps.sh
# База данных на сервере (/var/lib/testroom/testbot.db) НЕ трогается — обновляется только код.
set -euo pipefail

SERVER="root@212.47.58.69"
KEY="${HOME}/.ssh/testroom_deploy"
SRC="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"
TAR="$TMP/upd.tar.gz"

# Ключ эмбеддингов (RAG) из локального .env: деплой НЕ синхронизирует .env, поэтому
# прокидываем VOYAGE_API_KEY на сервер отдельно. Пусто — ничего не меняем на сервере.
VKEY=""
[ -f "$SRC/.env" ] && VKEY="$(grep -E '^VOYAGE_API_KEY=' "$SRC/.env" | head -1 | cut -d= -f2-)"

echo ">> Собираю архив кода (app, webapp, requirements.txt, guide)…"
GUIDE=""
[ -d "$SRC/guide" ] && GUIDE="guide"
tar -czf "$TAR" -C "$SRC" --exclude='__pycache__' --exclude='*.pyc' app webapp requirements.txt $GUIDE

echo ">> Загружаю на сервер…"
scp -i "$KEY" -o StrictHostKeyChecking=no "$TAR" "$SERVER:/root/upd.tar.gz"

echo ">> Разворачиваю и перезапускаю…"
ssh -i "$KEY" -o StrictHostKeyChecking=no "$SERVER" "bash -s '$VKEY'" <<'REMOTE'
set -e
VKEY="${1:-}"
tar -xzf /root/upd.tar.gz -C /opt/testroom
/opt/testroom/.venv/bin/pip install -q -r /opt/testroom/requirements.txt
# Прописываем/обновляем ключ эмбеддингов в серверном .env (если передан)
if [ -n "$VKEY" ]; then
  touch /opt/testroom/.env
  sed -i '/^VOYAGE_API_KEY=/d' /opt/testroom/.env
  echo "VOYAGE_API_KEY=$VKEY" >> /opt/testroom/.env
fi
systemctl restart testroom
rm -f /root/upd.tar.gz
sleep 5
echo -n "health: "; curl -s -m 5 http://127.0.0.1:8080/health || echo "НЕТ ОТВЕТА"
echo; echo -n "service: "; systemctl is-active testroom
echo ">> Память сервера (МБ):"; free -m
# Бэкофилл RAG: индексируем ещё не проиндексированные одобренные материалы (ошибка не валит деплой)
if [ -n "$VKEY" ]; then
  echo ">> Бэкофилл RAG…"
  (cd /opt/testroom && /opt/testroom/.venv/bin/python -m app.reindex) || echo "reindex: пропущен (ошибка/лимит)"
fi
REMOTE

rm -rf "$TMP"
echo ">> Готово. Адрес прежний: https://212-47-58-69.sslip.io"
