@echo off
echo [INFO] Starting Video2Note Setup...

:: 1. Build Frontend
echo [INFO] Building Frontend...
cd frontend
call npm run build
if %errorlevel% neq 0 (
    echo [ERROR] Frontend build failed!
    pause
    exit /b %errorlevel%
)
cd ..

:: 2. Start Backend (which now serves Frontend)
echo [INFO] Starting Backend Server...
echo [INFO] Please visit: http://127.0.0.1:8000
echo.
cd backend
call .venv\Scripts\activate
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
pause
