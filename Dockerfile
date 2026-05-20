# Aether OCR Platform — GCP Cloud Run Dockerfile
# Uses gunicorn + opencv-python-headless (no libGL needed)

FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-eng \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python dependencies (gunicorn + opencv-headless included)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy all application source files
COPY app.py .
COPY tasks.py .
COPY ocr_agent.py .
COPY ocr_router.py .
COPY ocr_engine.py .
COPY neural_structurer.py .
COPY document_classifier.py .
COPY case_builder.py .
COPY confidence_engine.py .
COPY blank_page_detector.py .
COPY form_mapper.py .
COPY draft_generator.py .
COPY excel_exporter.py .
COPY migrate_db.py .

# Copy web assets
COPY templates/ templates/
COPY static/ static/

# Create required runtime directories
RUN mkdir -p /app/uploads /app/outputs /app/instance

# Environment
ENV PYTHONUNBUFFERED=1 \
    TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata \
    FLASK_ENV=production

# GCP Cloud Run injects PORT=8080
EXPOSE 8080

# Start gunicorn on $PORT (injected by Cloud Run as 8080)
CMD exec gunicorn --bind "0.0.0.0:${PORT:-8080}" \
    --workers 2 \
    --threads 4 \
    --timeout 300 \
    --keep-alive 5 \
    --log-level info \
    app:app
