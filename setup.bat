@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Создаю виртуальное окружение...
python -m venv .venv
if errorlevel 1 (
  echo Не найден Python. Установите Python 3.11+ с python.org и отметьте "Add Python to PATH".
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
echo Устанавливаю библиотеки...
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
if not exist .env copy .env.example .env
echo.
echo Готово! Откройте файл .env, впишите BOT_TOKEN, ADMIN_IDS и WEBAPP_URL, затем запустите run.bat
pause
