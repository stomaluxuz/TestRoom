@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === start.bat запущен: %DATE% %TIME% === > startbat_ran.txt
echo Текущая папка: %CD% >> startbat_ran.txt
echo Запуск TestRoom. Если окно сразу закроется - значит ошибка, смотри startbat_ran.txt
echo.
if not exist ".venv\Scripts\python.exe" (
  echo НЕ НАЙДЕН .venv\Scripts\python.exe >> startbat_ran.txt
  echo ОШИБКА: не найден .venv\Scripts\python.exe. Запустите setup.bat, потом start.bat.
  pause
  exit /b 1
)
echo python найден, запускаю run_all.py >> startbat_ran.txt
".venv\Scripts\python.exe" run_all.py > startbat.log 2>&1
echo === start.bat завершился: %DATE% %TIME% === >> startbat_ran.txt
echo.
echo --- Процесс завершился. Это окно можно закрыть. ---
pause
