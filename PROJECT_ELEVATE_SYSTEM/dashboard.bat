@echo off
REM United Brothers Co. - launch the PROJECT ELEVATE dashboard locally (Windows).
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 goto :nopython
if not exist ".venv\" python -m venv .venv
call .venv\Scripts\activate.bat
pip install -q -r requirements-dashboard.txt
echo ==^> Opening the dashboard in your browser...
streamlit run dashboard.py
goto :end
:nopython
echo ERROR: Python not found. Install from https://python.org/downloads
:end
pause
endlocal
