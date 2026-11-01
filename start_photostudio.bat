@echo off
setlocal
title Virtual AI Photostudio
cd /d "%~dp0"

if "%COMFY_BASE_DIR%"=="" set "COMFY_BASE_DIR=%USERPROFILE%\Documents\ComfyUI"
if "%LOCALAPPDATA%"=="" set "LOCALAPPDATA=%USERPROFILE%\AppData\Local"
if "%COMFY_MAIN%"=="" set "COMFY_MAIN=%LOCALAPPDATA%\Programs\ComfyUI\resources\ComfyUI\main.py"
set "VENV_PYTHON=%COMFY_BASE_DIR%\.venv\Scripts\python.exe"
set "SERVICE_DIR=%LOCALAPPDATA%\VirtualFotostudio\services"
set "LOG_DIR=%LOCALAPPDATA%\VirtualFotostudio\logs"
set "MODE=%~1"
if "%MODE%"=="" set "MODE=quiet"
set "RESERVE_VRAM=6.0"
if /I "%MODE%"=="balanced" set "RESERVE_VRAM=3.0"
if /I "%MODE%"=="turbo" set "RESERVE_VRAM=0.5"
if /I not "%MODE%"=="quiet" if /I not "%MODE%"=="balanced" if /I not "%MODE%"=="turbo" (
    echo [ERROR] Unknown mode "%MODE%". Choose quiet, balanced, or turbo.
    exit /b 2
)

if not exist "%VENV_PYTHON%" (
    echo [ERROR] Python not found at: %VENV_PYTHON%
    echo         Set COMFY_BASE_DIR to your ComfyUI folder and try again.
    pause
    exit /b 1
)

echo [1/3] Checking ComfyUI ^(mode: %MODE%, reserve %RESERVE_VRAM% GB^)...
call :comfy_up
if errorlevel 1 (
    if not exist "%COMFY_MAIN%" (
        echo [ERROR] ComfyUI entry point not found: %COMFY_MAIN%
        exit /b 1
    )
    "%VENV_PYTHON%" "%~dp0scripts\manage_services.py" start comfy ^
        --pid-dir "%SERVICE_DIR%" --log-dir "%LOG_DIR%" --cwd "%COMFY_BASE%" ^
        --match "%COMFY_MAIN%" --match "--port 8188" -- ^
        "%VENV_PYTHON%" "%COMFY_MAIN%" ^
        --base-directory "%COMFY_BASE%" --listen 127.0.0.1 --port 8188 ^
        --disable-auto-launch --cuda-malloc --dont-print-server --reserve-vram %RESERVE_VRAM%
    if errorlevel 1 (
        echo [ERROR] Could not start ComfyUI. Check %LOG_DIR%\comfy.log
        exit /b 1
    )
    echo         Waiting for ComfyUI to initialise ^(up to 2 minutes^)...
    set "TRIES=0"
    call :wait_for_comfy
    if errorlevel 1 (
        echo [ERROR] ComfyUI did not respond. Check %LOG_DIR%\comfy.log
        exit /b 1
    )
) else (
    echo         ComfyUI already running; it will not be stopped unless this launcher started it.
)

echo [2/3] Verifying Python dependencies...
"%VENV_PYTHON%" -c "import streamlit, websocket" 2>nul
if errorlevel 1 (
    "%VENV_PYTHON%" -m pip install -r "%~dp0requirements.txt" --quiet
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed.
        exit /b 1
    )
)

echo [3/3] Starting Virtual AI Photostudio...
call :photostudio_up
if errorlevel 1 (
    "%VENV_PYTHON%" "%~dp0scripts\manage_services.py" start photostudio ^
        --pid-dir "%SERVICE_DIR%" --log-dir "%LOG_DIR%" --cwd "%~dp0" ^
        --match "%~dp0photostudio_app.py" --match "--server.port 7860" -- ^
        "%VENV_PYTHON%" -m streamlit run "%~dp0photostudio_app.py" ^
        --server.port 7860 --server.address 127.0.0.1 --server.headless true ^
        --browser.gatherUsageStats false --theme.base dark
    if errorlevel 1 (
        echo [ERROR] Could not start the UI. Check %LOG_DIR%\photostudio.log
        exit /b 1
    )
) else (
    echo         Port 7860 is already in use; leaving the existing service untouched.
)

set "TRIES=0"
call :wait_for_photostudio
if errorlevel 1 (
    echo [ERROR] The web UI did not start. Check %LOG_DIR%\photostudio.log
    exit /b 1
)
start http://127.0.0.1:7860
echo Virtual AI Photostudio is starting at http://127.0.0.1:7860
echo Logs: %LOG_DIR%
pause
endlocal
exit /b 0

:comfy_up
"%VENV_PYTHON%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8188/system_stats', timeout=2).read()" >nul 2>nul
exit /b %errorlevel%

:photostudio_up
"%VENV_PYTHON%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/_stcore/health', timeout=2).read()" >nul 2>nul
exit /b %errorlevel%

:wait_for_photostudio
call :photostudio_up
if not errorlevel 1 exit /b 0
set /a TRIES+=1
if %TRIES% GEQ 15 exit /b 1
timeout /t 2 /nobreak >nul
goto wait_for_photostudio

:wait_for_comfy
call :comfy_up
if not errorlevel 1 exit /b 0
set /a TRIES+=1
if %TRIES% GEQ 60 exit /b 1
timeout /t 2 /nobreak >nul
goto wait_for_comfy
