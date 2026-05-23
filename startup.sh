#!/bin/bash
# GCP Cloud Run startup script

set -e

echo "=============================================="
echo " Aether OCR Platform - Starting on GCP"
echo " PORT: ${PORT:-8080}"
echo "=============================================="

# Initialize the SQLite database
echo "Initializing database..."
python -c "
from app import app, db
with app.app_context():
    db.create_all()
    print('Database initialized successfully.')
"

# Create required directories
mkdir -p /app/uploads /app/outputs /app/instance

# Start gunicorn on the PORT provided by Cloud Run (default 8080)
PORT="${PORT:-8080}"
echo "Starting gunicorn on port $PORT..."
exec gunicorn \
    --bind "0.0.0.0:$PORT" \
    --workers 2 \
    --threads 4 \
    --timeout 300 \
    --keep-alive 5 \
    --log-level info \
    --access-logfile - \
    --error-logfile - \
    "app:app"
