@echo off
REM SQLatte Startup Script for Windows
REM Makes it super easy to start SQLatte

echo ============================================================
echo SQLatte - Starting...
echo ============================================================
echo.

REM Check if in correct directory
if not exist "run.py" (
    echo ERROR: run.py not found!
    echo.
    echo Make sure you're in the sqlatte directory:
    echo   cd sqlatte
    echo.
    pause
    exit /b 1
)

REM Check if .env exists
if not exist ".env" (
    echo WARNING: .env file not found!
    echo.
    echo Creating .env from template...
    copy .env.example .env
    echo Created .env
    echo.
    echo IMPORTANT: Edit .env and add your API keys
    echo   notepad .env
    echo.
    pause
)

REM Check if venv exists
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
    echo Virtual environment created
)

REM Activate venv
echo Activating virtual environment...
call venv\Scripts\activate.bat

REM Install/upgrade packages
echo Installing dependencies...
pip install -q -r requirements.txt --upgrade

echo.
echo Running validation tests...
echo.

REM Test imports
python validate_imports.py
if errorlevel 1 (
    echo.
    echo Validation failed! Fix errors above.
    pause
    exit /b 1
)

echo.
echo Testing API key...
echo.

REM Test API key
python test_api_key.py
if errorlevel 1 (
    echo.
    echo API key test failed!
    echo.
    echo Fix your .env file:
    echo   notepad .env
    echo.
    echo Then run this script again.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo All checks passed! Starting SQLatte...
echo ============================================================
echo.
echo Opening browser in 3 seconds...
echo.

REM Start server
start /b python run.py

REM Wait a bit
timeout /t 3 /nobreak > nul

REM Open browser
start http://localhost:8000

echo.
echo ============================================================
echo SQLatte is running!
echo ============================================================
echo.
echo URL: http://localhost:8000
echo Stop: Press Ctrl+C
echo.
echo ============================================================
echo.

pause
