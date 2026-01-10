@echo off
echo Starting both Backend and Frontend servers...
echo.

REM Set all environment variables
set FRONTEND_URL=https://creator.husan.shop
set CORS_ORIGINS=https://creator.husan.shop
set BACKEND_HOST=0.0.0.0
set BACKEND_PORT=6333
set FLASK_DEBUG=False
set SECRET_KEY=your-secret-key-change-this-in-production
set VITE_FRONTEND_PORT=7333
set VITE_BACKEND_URL=https://creator.husan.shop
set VITE_ALLOWED_HOSTS=creator.husan.shop

echo Starting Backend in new window...
start "Backend Server" cmd /k "python app_backend.py"

timeout /t 2 /nobreak >nul

echo Starting Frontend in new window...
start "Frontend Server" cmd /k "npm run dev"

echo.
echo Both servers are starting in separate windows...
echo Close this window or press any key to exit.
pause >nul








