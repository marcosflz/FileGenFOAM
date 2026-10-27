@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creando entorno virtual con Python 3.12...
    py -3.12 -m venv .venv 2>nul || python -m venv .venv
    if errorlevel 1 goto :error
    echo Instalando dependencias...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :error
)

".venv\Scripts\python.exe" app.py
if errorlevel 1 goto :error
exit /b 0

:error
echo.
echo No se pudo iniciar FileGenFOAM Studio. Revisa los mensajes anteriores.
pause
exit /b 1
