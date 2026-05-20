@echo off
:: Aether OCR — Start All Workers (Windows)
:: Run this AFTER starting Redis

echo.
echo ============================================================
echo  Aether OCR — Enterprise Worker Startup
echo ============================================================
echo.

cd /d %~dp0

:: Activate virtual environment
call venv\Scripts\activate.bat

echo [1/4] Starting Flask API Server...
start "Aether API" cmd /k "venv\Scripts\python.exe app.py"
timeout /t 3

echo [2/4] Starting OCR Worker (4 concurrent pages)...
start "Aether OCR Worker" cmd /k "venv\Scripts\celery -A celery_app worker -Q ocr -c 4 --loglevel=info -n ocr_worker@%%h"
timeout /t 2

echo [3/4] Starting LLM Worker (2 concurrent — API rate limit safe)...
start "Aether LLM Worker" cmd /k "venv\Scripts\celery -A celery_app worker -Q llm -c 2 --loglevel=info -n llm_worker@%%h"
timeout /t 2

echo [4/4] Starting Export Worker...
start "Aether Export Worker" cmd /k "venv\Scripts\celery -A celery_app worker -Q export -c 2 --loglevel=info -n export_worker@%%h"
timeout /t 2

echo.
echo ============================================================
echo  All workers started!
echo  API:     http://localhost:5000
echo  Monitor: http://localhost:5555  (Flower)
echo ============================================================
echo.

:: Start Flower monitoring (optional)
start "Flower Monitor" cmd /k "venv\Scripts\celery -A celery_app flower --port=5555"

pause
