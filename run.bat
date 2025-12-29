@echo off
echo [INFO] Starting Video2Note System...

:: 1. Start Backend in a new window
echo [INFO] Launching Backend...
:: Note: .venv is in the ROOT directory, so we activate it from there, then cd backend to run the app
start "Video2Note Backend" cmd /k "call .venv\Scripts\activate && cd backend && python -m uvicorn app.main:app --reload"

:: 2. Start Frontend in a new window
echo [INFO] Launching Frontend...
start "Video2Note Frontend" cmd /k "cd frontend && npm run dev"

echo [SUCCESS] Both services are starting...
echo Backend: http://127.0.0.1:8000
echo Frontend: http://localhost:5173
echo.
pause
