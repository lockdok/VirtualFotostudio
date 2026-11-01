@echo off
setlocal
title Virtual AI Photostudio - Download Models
cd /d "%~dp0"
set "RESULT=0"

if "%COMFY_BASE_DIR%"=="" set "COMFY_BASE_DIR=%USERPROFILE%\Documents\ComfyUI"
set "VENV_PYTHON=%COMFY_BASE_DIR%\.venv\Scripts\python.exe"

echo ============================================================
echo  VIRTUAL AI PHOTOSTUDIO - MODEL DOWNLOADER
echo ============================================================
echo.
echo Models will be saved under:
echo   %COMFY_BASE_DIR%\models
echo.
echo The default checkpoint and identity models need about 12.3 GB.
echo Existing complete files are skipped; incomplete files are replaced.
echo.

if not exist "%VENV_PYTHON%" (
    echo [ERROR] ComfyUI Python was not found:
    echo         %VENV_PYTHON%
    echo Set COMFY_BASE_DIR to your ComfyUI installation folder and retry.
    goto failed
)

"%VENV_PYTHON%" -c "import huggingface_hub" >nul 2>nul
if errorlevel 1 (
    echo Installing the downloader dependency into the ComfyUI environment...
    "%VENV_PYTHON%" -m pip install "huggingface-hub>=0.26"
    if errorlevel 1 (
        echo [ERROR] Could not install huggingface-hub.
        goto failed
    )
)

echo Starting model downloads. Large files may take a while...
echo.
"%VENV_PYTHON%" "%~dp0scripts\download_models.py" %*
if errorlevel 1 (
    echo.
    echo [ERROR] Model download failed. Review the error above.
    echo If Hugging Face requires access, accept the model terms and configure
    echo your Hugging Face login in this Windows account, then retry.
    goto failed
)

echo.
echo [OK] All requested model downloads completed.
echo Restart ComfyUI if it was already running.
goto finished

:failed
set "RESULT=1"
echo.
echo See README.md for model links and setup instructions.

:finished
echo.
pause
endlocal & exit /b %RESULT%
