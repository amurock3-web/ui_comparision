@echo off
rem One-time setup on Windows: creates .venv (main, paddle) and .venv-detector (YOLO),
rem installs the pinned requirements into each, then runs the setup doctor.
rem Safe to re-run: existing healthy venvs are kept and pip skips what is installed.
setlocal
cd /d "%~dp0"

echo Setting up UI Comparison in "%CD%"
echo Needs internet, about 10-20 min the first time; re-running is safe and fast.
echo.

rem --- Python 3.11 -------------------------------------------------------------
set "PY="
py -3.11 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY=py -3.11"
if defined PY goto :have_python
python -c "import sys; sys.exit(sys.version_info[:2] != (3, 11))" >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto :have_python
echo ERROR: Python 3.11 was not found.
echo Install Python 3.11 for Windows from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" in the installer, then run setup.bat again.
set "RC=1"
goto :end

:have_python
echo Using Python: %PY%

rem --- venvs -------------------------------------------------------------------
set "STEP=creating .venv"
call :ensure_venv .venv
if errorlevel 1 goto :fail
set "STEP=creating .venv-detector"
call :ensure_venv .venv-detector
if errorlevel 1 goto :fail

rem --- packages ----------------------------------------------------------------
set "STEP=upgrading pip in .venv"
echo.
echo [1/4] Upgrading pip in .venv
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :fail

set "STEP=installing requirements.txt into .venv"
echo.
echo [2/4] Installing requirements.txt into .venv
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

set "STEP=upgrading pip in .venv-detector"
echo.
echo [3/4] Upgrading pip in .venv-detector
".venv-detector\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :fail

set "STEP=installing requirements-detector.txt into .venv-detector"
echo.
echo [4/4] Installing requirements-detector.txt into .venv-detector
".venv-detector\Scripts\python.exe" -m pip install -r requirements-detector.txt
if errorlevel 1 goto :fail

rem --- doctor ------------------------------------------------------------------
echo.
echo Running the setup check
".venv\Scripts\python.exe" -m scripts.check_setup
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" echo Setup complete. Start the app with "UI Compare.bat".
if not "%RC%"=="0" echo Setup check reported problems, see above.
goto :end

:fail
echo.
echo ERROR: setup failed while %STEP%.
echo Fix the error above and run setup.bat again - it is safe to re-run.
set "RC=1"

:end
pause
exit /b %RC%

rem --- :ensure_venv <dir> --------------------------------------------------------
rem Keeps a healthy venv; recreates one whose python does not run
rem (e.g. copied from another machine) or is not 3.11.
:ensure_venv
if not exist "%~1\Scripts\python.exe" goto :create_venv
"%~1\Scripts\python.exe" -c "import sys, pip; sys.exit(sys.version_info[:2] != (3, 11))" >nul 2>&1
if not errorlevel 1 (
    echo %~1 is ready.
    exit /b 0
)
echo %~1 exists but its Python does not run here - copied from another machine? Recreating it.
rmdir /s /q "%~1"
if exist "%~1" (
    echo ERROR: could not delete %~1 - close any program using it and retry.
    exit /b 1
)
:create_venv
if exist "%~1" rmdir /s /q "%~1"
echo Creating %~1
%PY% -m venv "%~1"
exit /b %ERRORLEVEL%
