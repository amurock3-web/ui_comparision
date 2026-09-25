@echo off
rem Double-click launcher for the drag-and-drop UI (python -m src.app).
rem Arguments pass through, e.g.  "UI Compare.bat" --port 8800 --no-browser
cd /d "%~dp0"
if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"
rem UI_DETECTOR_PYTHON=C:\path\to\python.exe in a local .env (gitignored) points at the YOLO venv.
if exist ".env" for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do (
    if /i "%%a"=="UI_DETECTOR_PYTHON" set "UI_DETECTOR_PYTHON=%%~b"
)
python -m src.app %*
if errorlevel 1 pause
