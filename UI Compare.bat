@echo off
rem Double-click launcher for the drag-and-drop UI (python -m src.app).
rem Arguments pass through, e.g.  "UI Compare.bat" --port 8800 --no-browser
cd /d "%~dp0"
rem setup.bat creates .venv (main) and .venv-detector (YOLO); both must exist.
if not exist ".venv\Scripts\python.exe" goto :nosetup
if not exist ".venv-detector\" goto :nosetup
".venv\Scripts\python.exe" -c "import sys" >nul 2>&1
if errorlevel 1 goto :badvenv
rem The detector python is found automatically (.venv-detector). Optional override:
rem UI_DETECTOR_PYTHON=C:\path\to\python.exe in a local .env (gitignored).
if exist ".env" for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do (
    if /i "%%a"=="UI_DETECTOR_PYTHON" set "UI_DETECTOR_PYTHON=%%~b"
)
".venv\Scripts\python.exe" -m src.app %*
if errorlevel 1 pause
exit /b %errorlevel%

:nosetup
echo.
echo Setup has not been run on this computer.
echo Double-click setup.bat (needs internet, ~10-20 min once), then start UI Compare again.
echo.
pause
exit /b 1

:badvenv
echo.
echo The .venv folder does not work here: the .venv was made on another computer.
echo Run setup.bat again (needs internet, ~10-20 min once), then start UI Compare again.
echo.
pause
exit /b 1
