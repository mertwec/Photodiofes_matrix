@echo off
REM Запуск live UART стрима: активация .venv + python cli.py stream
REM Доп. аргументы пробрасываются в cli.py (например: run.bat --port COM3)

REM Перейти в папку скрипта (чтобы пути работали при запуске из любого места)
cd /d "%~dp0"

REM 1) Активация виртуального окружения .venv
call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo [ОШИБКА] Не удалось активировать .venv. Проверьте, что окружение создано.
    pause
    exit /b 1
)

REM 2) Запуск стрима
py cli.py stream %*

REM Оставить окно открытым, чтобы увидеть вывод/ошибки
pause
