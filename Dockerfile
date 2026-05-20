# Aether OCR Platform — GCP Cloud Run Dockerfile
# Optimized for production deployment

FROM python:3.11-slim

# Install system dependencies for OCR and PDF processing
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
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first (layer caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy all application files
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

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata \
    FLASK_ENV=production

# GCP Cloud Run: PORT is injected automatically (default 8080)
# app.py reads PORT env var via os.environ.get('PORT', 5000)
EXPOSE 8080

# Initialize DB and start the Flask server
CMD ["sh", "-c", "python -c 'from app import app, db; app.app_context().__enter__(); db.create_all()' && python app.py"]
