@echo off
REM Simple helper to start the VMD Extractor CLI without opening the editor.

setlocal enabledelayedexpansion

REM Determine script directory (so we can run the same bat from anywhere)
set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%"

REM Prefer local venv python if it exists, otherwise fall back to system python.
set "VENV_PY=%SCRIPT_DIR%venv\Scripts\python.exe"
if exist "%VENV_PY%" (
    "%VENV_PY%" run.py %*
) else (
    python run.py %*
)

popd
endlocal














