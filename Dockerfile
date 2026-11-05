# Образ для облачного хостинга (Railway и т.п.). Запускает сервер Mini App + бота.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    RUN_BOT=1 \
    HOST=0.0.0.0

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY webapp ./webapp
# seed.db — снимок базы для первого запуска (переносится на постоянный том, если он пуст).
COPY seed.db ./seed.db

# PORT задаёт сам хостинг; адрес Mini App берётся из RAILWAY_PUBLIC_DOMAIN автоматически.
CMD ["python", "-m", "app.main"]
