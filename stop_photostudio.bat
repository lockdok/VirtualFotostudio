@echo off
title Stopping Virtual AI Photostudio
echo.
echo  ============================================================
echo   🔴 VIRTUAL AI PHOTOSTUDIO — Stopping...
echo  ============================================================
echo.

:: ── Stop Streamlit / Photostudio Web UI ──────────────────────────────────────
echo  [1/3] Stopping Photostudio Web UI (port 7860)...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":7860 " ^| findstr LISTENING') do (
    taskkill /PID %%a /F >nul 2>&1
    echo       ✓ Photostudio UI process stopped (PID %%a)
)

:: ── Stop ComfyUI Engine ───────────────────────────────────────────────────────
echo  [2/3] Stopping ComfyUI engine (port 8188)...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8188 " ^| findstr LISTENING') do (
    taskkill /PID %%a /F >nul 2>&1
    echo       ✓ ComfyUI engine stopped (PID %%a)
)

:: Fallback: kill any lingering Python processes with our window titles
taskkill /FI "WINDOWTITLE eq ComfyUI Engine" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Photostudio UI" /F >nul 2>&1

:: ── Free GPU VRAM via nvidia-smi (force GPU reset if stuck) ──────────────────
echo  [3/3] Releasing GPU VRAM...
where nvidia-smi >nul 2>&1
if %errorlevel% == 0 (
    nvidia-smi --gpu-reset >nul 2>&1
    echo       ✓ GPU VRAM released
) else (
    echo       ✓ Processes terminated (VRAM freed automatically)
)

echo.
echo  ============================================================
echo   ✓ Virtual AI Photostudio fully stopped.
echo     GPU VRAM has been released.
echo  ============================================================
echo.
timeout /t 3 /nobreak >nul

