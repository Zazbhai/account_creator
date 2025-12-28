@echo off
echo Setting environment variables for Backend...
set FRONTEND_URL=https://creator.husan.shop
set CORS_ORIGINS=https://creator.husan.shop
set BACKEND_HOST=0.0.0.0
set BACKEND_PORT=6333
set FLASK_DEBUG=False
set SECRET_KEY=your-secret-key-change-this-in-production

echo.
echo Starting Backend Server...
echo.
python app_backend.py







