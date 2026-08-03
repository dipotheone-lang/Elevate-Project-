@echo off
REM ---------------------------------------------------------------------------
REM United Brothers Co. - PROJECT ELEVATE - one-command launcher (Windows)
REM Double-click this file, or run it from PowerShell / Command Prompt.
REM
REM   run.bat          run the full pipeline
REM   run.bat test     run the test suite instead
REM
REM Uses single-line IFs and GOTO labels on purpose: parenthesized IF blocks
REM in .bat break on any literal "(" or ")" inside an echo (a classic
REM "... was unexpected at this time." error), so we avoid them entirely.
REM ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

REM Locate Python.
where python >nul 2>nul
if errorlevel 1 goto :nopython

for /f "delims=" %%v in ('python --version') do echo ==^> Using %%v

REM Create the virtual environment on first run.
if not exist ".venv\" echo ==^> Creating virtual environment .venv ...
if not exist ".venv\" python -m venv .venv

REM Activate it.
call .venv\Scripts\activate.bat

echo ==^> Installing dependencies ...
python -m pip install --upgrade pip >nul

if /i "%~1"=="test" goto :runtests

REM --- Full pipeline ---
pip install -q -r requirements.txt
echo ==^> Running the full PROJECT ELEVATE pipeline ...
python run_pipeline.py
echo.
echo ==^> Done. Open the results in the .\outputs\ folder:
echo        - boq_audit_report.md
echo        - site_daily_digest.md
echo        - gainsharing_result.md
echo        - UNITED_BROTHERS_ELEVATE_MASTER.xlsx  [open in Excel]
goto :end

:runtests
pip install -q -r requirements-dev.txt
echo ==^> Running test suite ...
python -m pytest tests/ -v
goto :end

:nopython
echo ERROR: Python not found. Install it from https://python.org/downloads
echo Make sure you tick "Add Python to PATH" during install.

:end
echo.
pause
endlocal
