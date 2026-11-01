@echo off
setlocal
title Stopping Virtual AI Photostudio
cd /d "%~dp0"

if "%COMFY_BASE_DIR%"=="" set "COMFY_BASE_DIR=%USERPROFILE%\Documents\ComfyUI"
if "%LOCALAPPDATA%"=="" set "LOCALAPPDATA=%USERPROFILE%\AppData\Local"
set "VENV_PYTHON=%COMFY_BASE_DIR%\.venv\Scripts\python.exe"
set "SERVICE_DIR=%LOCALAPPDATA%\VirtualFotostudio\services"

if not exist "%VENV_PYTHON%" (
    echo [ERROR] ComfyUI Python not found at: %VENV_PYTHON%
    echo         Cannot safely inspect or stop the services started by this launcher.
    exit /b 1
)

echo Stopping only services started and tracked by this launcher...
"%VENV_PYTHON%" "%~dp0scripts\manage_services.py" stop photostudio --pid-dir "%SERVICE_DIR%"
if errorlevel 1 exit /b 1
"%VENV_PYTHON%" "%~dp0scripts\manage_services.py" stop comfy --pid-dir "%SERVICE_DIR%"
if errorlevel 1 exit /b 1
echo Done. Services started outside this launcher were left untouched.
endlocal
