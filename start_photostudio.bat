@echo off
title Virtual AI Photostudio
echo.
echo  ============================================================
echo   📸 VIRTUAL AI PHOTOSTUDIO — Starting...
echo  ============================================================
echo.

:: ── Set working directory to the VirtualFotostudio folder ────────────────────
cd /d "%~dp0"

:: ── Python executable in ComfyUI's managed venv ───────────────────────────────
if "%COMFY_BASE_DIR%"=="" set COMFY_BASE_DIR=%USERPROFILE%\Documents\ComfyUI
if "%COMFY_MAIN%"=="" set COMFY_MAIN=%LOCALAPPDATA%\Programs\ComfyUI\resources\ComfyUI\main.py
set VENV_PYTHON=%COMFY_BASE_DIR%\.venv\Scripts\python.exe
set COMFY_BASE=%COMFY_BASE_DIR%
set MODE=%~1
if "%MODE%"=="" set MODE=quiet
set RESERVE_VRAM=6.0
if /I "%MODE%"=="balanced" set RESERVE_VRAM=3.0
if /I "%MODE%"=="turbo" set RESERVE_VRAM=0.5

:: ── Check if ComfyUI is already running ──────────────────────────────────────
echo  [1/3] Checking ComfyUI engine status...
%VENV_PYTHON% -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8188/system_stats', timeout=2).read(); print('RUNNING')" 2>nul | findstr "RUNNING" >nul
if %errorlevel% == 0 (
    echo       ✓ ComfyUI already running on port 8188
) else (
    echo       → Starting ComfyUI headless engine...
    start "ComfyUI Engine" /belownormal /min %VENV_PYTHON% ^
        "%COMFY_MAIN%" ^
        --base-directory "%COMFY_BASE%" ^
        --listen 127.0.0.1 ^
        --port 8188 ^
        --disable-auto-launch ^
        --cuda-malloc ^
        --dont-print-server ^
        --reserve-vram %RESERVE_VRAM%
    echo       Waiting for ComfyUI to initialise...
    timeout /t 8 /nobreak >nul
    echo       ✓ ComfyUI engine started
)

:: ── Install required packages if missing ─────────────────────────────────────
echo  [2/3] Verifying Python dependencies...
%VENV_PYTHON% -c "import streamlit, websocket" 2>nul
if %errorlevel% NEQ 0 (
    echo       → Installing missing packages...
    %VENV_PYTHON% -m pip install streamlit websocket-client --quiet
    echo       ✓ Dependencies ready
) else (
    echo       ✓ All dependencies present
)

:: ── Launch Photostudio Web UI ─────────────────────────────────────────────────
echo  [3/3] Launching Virtual AI Photostudio Web UI...
echo.
echo  ============================================================
echo   Open your browser: http://localhost:7860
echo  ============================================================
echo.

:: Set process to Below Normal priority for background multitasking
start "Photostudio UI" /belownormal %VENV_PYTHON% -m streamlit run "%~dp0photostudio_app.py" ^
    --server.port 7860 ^
    --server.headless false ^
    --browser.gatherUsageStats false ^
    --theme.base dark

:: Open browser after short delay
timeout /t 4 /nobreak >nul
start http://localhost:7860

echo  Virtual AI Photostudio is running!
echo  Press any key in this window only to exit the launcher (does NOT stop services).
pause >nul

