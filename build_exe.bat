@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Сборка TestRoom.exe (один файл со всеми зависимостями)...
call .venv\Scripts\activate.bat
python -m pip install --quiet pyinstaller
python -m PyInstaller --noconfirm --onefile --name TestRoom --console ^
  --distpath dist_exe --workpath build_exe --specpath build_exe ^
  --add-data "%~dp0webapp;webapp" ^
  --collect-submodules uvicorn ^
  --collect-submodules aiogram ^
  --collect-submodules sqlalchemy ^
  --collect-all docx ^
  --collect-all pptx ^
  --collect-submodules openpyxl ^
  --collect-submodules anthropic ^
  --collect-submodules httpx ^
  --hidden-import aiosqlite ^
  --hidden-import app.main --hidden-import app.bot --hidden-import app.api ^
  --hidden-import app.services --hidden-import app.parsers --hidden-import app.models ^
  --hidden-import app.auth --hidden-import app.db --hidden-import app.config --hidden-import app.universities --hidden-import app.present --hidden-import app.ai --hidden-import app.images ^
  --paths "%~dp0" ^
  standalone.py
echo.
echo Готово: dist_exe\TestRoom.exe
echo Положите рядом cloudflared.exe и .env — и можно запускать на любом ПК без Python.
pause
