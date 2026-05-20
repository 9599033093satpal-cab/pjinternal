# Enterprise OCR Agent - Deployment Guide

## Production Deployment Options

### Option 1: Docker Deployment (Recommended)

#### Quick Start with Docker

1. **Build the image:**
```bash
docker build -t ocr-agent:latest .
```

2. **Run a single OCR job:**
```bash
docker run --rm \
  -v $(pwd)/input:/app/input \
  -v $(pwd)/output:/app/output \
  ocr-agent:latest \
  python ocr_agent.py /app/input/document.pdf --output /app/output/
```

3. **Using docker-compose:**
```bash
# Place your PDF in ./input/document.pdf
docker-compose up ocr-agent
```

#### Advanced Docker Usage

**With custom configuration:**
```bash
docker run --rm \
  -v $(pwd)/input:/app/input \
  -v $(pwd)/output:/app/output \
  -e OCR_ENGINE=easyocr \
  -e OCR_DPI=600 \
  -e OCR_WORKERS=8 \
  ocr-agent:latest \
  python ocr_agent.py /app/input/large_document.pdf \
    --output /app/output/ \
    --engine easyocr \
    --dpi 600 \
    --workers 8
```

**Batch processing multiple files:**
```bash
docker run --rm \
  -v $(pwd)/pdfs:/app/input \
  -v $(pwd)/results:/app/output \
  ocr-agent:latest \
  bash -c 'for pdf in /app/input/*.pdf; do \
    python ocr_agent.py "$pdf" --output /app/output/$(basename "$pdf" .pdf)/; \
  done'
```

### Option 2: Kubernetes Deployment

#### Sample Kubernetes Job

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: ocr-processing-job
spec:
  template:
    spec:
      containers:
      - name: ocr-agent
        image: your-registry/ocr-agent:latest
        resources:
          limits:
            memory: "8Gi"
            cpu: "4"
          requests:
            memory: "4Gi"
            cpu: "2"
        volumeMounts:
        - name: input-volume
          mountPath: /app/input
        - name: output-volume
          mountPath: /app/output
        env:
        - name: OCR_ENGINE
          value: "tesseract"
        - name: OCR_DPI
          value: "300"
        args: ["python", "ocr_agent.py", "/app/input/document.pdf", "--output", "/app/output/"]
      volumes:
      - name: input-volume
        persistentVolumeClaim:
          claimName: ocr-input-pvc
      - name: output-volume
        persistentVolumeClaim:
          claimName: ocr-output-pvc
      restartPolicy: OnFailure
  backoffLimit: 3
```

#### Kubernetes CronJob for Scheduled Processing

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: ocr-batch-processor
spec:
  schedule: "0 2 * * *"  # Run daily at 2 AM
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: ocr-agent
            image: your-registry/ocr-agent:latest
            args: ["python", "batch_process.py"]
            volumeMounts:
            - name: shared-storage
              mountPath: /app/storage
          volumes:
          - name: shared-storage
            persistentVolumeClaim:
              claimName: shared-pvc
          restartPolicy: OnFailure
```

### Option 3: AWS ECS Deployment

#### ECS Task Definition (JSON)

```json
{
  "family": "ocr-agent-task",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "4096",
  "memory": "8192",
  "containerDefinitions": [
    {
      "name": "ocr-agent",
      "image": "your-ecr-repo/ocr-agent:latest",
      "essential": true,
      "environment": [
        {
          "name": "OCR_ENGINE",
          "value": "tesseract"
        },
        {
          "name": "OCR_DPI",
          "value": "300"
        }
      ],
      "mountPoints": [
        {
          "sourceVolume": "efs-storage",
          "containerPath": "/app/storage"
        }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/ocr-agent",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "ocr"
        }
      }
    }
  ],
  "volumes": [
    {
      "name": "efs-storage",
      "efsVolumeConfiguration": {
        "fileSystemId": "fs-xxxxxx",
        "transitEncryption": "ENABLED"
      }
    }
  ]
}
```

### Option 4: Serverless (AWS Lambda + EFS)

#### Lambda Function Structure

```python
# lambda_handler.py
import json
import os
from ocr_agent import OCRAgent

def lambda_handler(event, context):
    """
    Lambda handler for OCR processing
    Event format: {
        "pdf_path": "s3://bucket/document.pdf",
        "output_bucket": "output-bucket"
    }
    """
    
    # Download PDF from S3
    import boto3
    s3 = boto3.client('s3')
    
    pdf_path = event['pdf_path']
    bucket = pdf_path.split('/')[2]
    key = '/'.join(pdf_path.split('/')[3:])
    
    local_pdf = f"/tmp/{os.path.basename(key)}"
    s3.download_file(bucket, key, local_pdf)
    
    # Process with OCR
    agent = OCRAgent(
        pdf_path=local_pdf,
        output_dir="/tmp/ocr_output/",
        engine="tesseract",
        dpi=300,
        num_workers=2  # Lambda has CPU limits
    )
    
    output_files = agent.run()
    
    # Upload results to S3
    output_bucket = event['output_bucket']
    s3_urls = []
    
    for output_file in output_files:
        filename = os.path.basename(output_file)
        s3_key = f"ocr-results/{filename}"
        s3.upload_file(output_file, output_bucket, s3_key)
        s3_urls.append(f"s3://{output_bucket}/{s3_key}")
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'output_files': s3_urls
        })
    }
```

## Performance Optimization

### 1. Resource Allocation

**Small PDFs (< 50 pages):**
- CPU: 2 cores
- RAM: 2GB
- Workers: 2

**Medium PDFs (50-200 pages):**
- CPU: 4 cores
- RAM: 4GB
- Workers: 4

**Large PDFs (200-500 pages):**
- CPU: 8 cores
- RAM: 8GB
- Workers: 8

**Very Large PDFs (500+ pages):**
- CPU: 16 cores
- RAM: 16GB
- Workers: 12-16

### 2. Caching Strategy

Cache OCR results to avoid reprocessing:

```python
import hashlib
import json
from pathlib import Path

def get_file_hash(filepath):
    """Generate SHA256 hash of file"""
    sha256 = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for block in iter(lambda: f.read(4096), b''):
            sha256.update(block)
    return sha256.hexdigest()

def process_with_cache(pdf_path, cache_dir="cache/"):
    """Process PDF with caching"""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(exist_ok=True)
    
    # Generate cache key
    file_hash = get_file_hash(pdf_path)
    cache_file = cache_dir / f"{file_hash}.json"
    
    # Check cache
    if cache_file.exists():
        print(f"Using cached results for {pdf_path}")
        with open(cache_file, 'r') as f:
            return json.load(f)
    
    # Process with OCR
    agent = OCRAgent(pdf_path=pdf_path)
    output_files = agent.run()
    
    # Save to cache
    cache_data = {
        'pdf_path': str(pdf_path),
        'file_hash': file_hash,
        'output_files': output_files
    }
    
    with open(cache_file, 'w') as f:
        json.dump(cache_data, f)
    
    return cache_data
```

### 3. Horizontal Scaling

For processing large volumes of PDFs:

**Queue-based Processing:**
```python
# Using Redis Queue (RQ)
from rq import Queue
from redis import Redis
from ocr_agent import OCRAgent

# Setup
redis_conn = Redis(host='redis', port=6379)
q = Queue(connection=redis_conn)

# Enqueue jobs
for pdf_path in pdf_list:
    q.enqueue(process_pdf, pdf_path)

def process_pdf(pdf_path):
    agent = OCRAgent(pdf_path=pdf_path)
    return agent.run()

# Worker command
# rq worker --with-scheduler
```

**Celery-based Processing:**
```python
from celery import Celery
from ocr_agent import OCRAgent

app = Celery('ocr_tasks', broker='redis://localhost:6379')

@app.task
def process_pdf_task(pdf_path):
    agent = OCRAgent(pdf_path=pdf_path)
    return agent.run()

# Usage
result = process_pdf_task.delay('document.pdf')
```

## Monitoring & Logging

### 1. Application Metrics

```python
# metrics.py
from prometheus_client import Counter, Histogram, start_http_server

# Define metrics
pdf_processed_total = Counter(
    'pdf_processed_total',
    'Total PDFs processed',
    ['engine', 'status']
)

processing_duration = Histogram(
    'pdf_processing_duration_seconds',
    'Time spent processing PDFs',
    ['engine']
)

# In OCRAgent.run()
with processing_duration.labels(engine=self.engine).time():
    pages = self.process_pdf()
    # ... rest of processing

pdf_processed_total.labels(
    engine=self.engine,
    status='success'
).inc()

# Start metrics server
start_http_server(8000)
```

### 2. Structured Logging

```python
import structlog

logger = structlog.get_logger()

logger.info(
    "ocr_processing_started",
    pdf_path=str(self.pdf_path),
    engine=self.engine,
    dpi=self.dpi,
    total_pages=len(images)
)
```

### 3. Alerting

**Prometheus Alert Rules:**
```yaml
groups:
- name: ocr_alerts
  rules:
  - alert: HighOCRFailureRate
    expr: rate(pdf_processed_total{status="error"}[5m]) > 0.1
    for: 5m
    annotations:
      summary: "High OCR failure rate detected"
  
  - alert: SlowOCRProcessing
    expr: pdf_processing_duration_seconds > 3600
    annotations:
      summary: "OCR processing taking too long"
```

## Security Best Practices

### 1. Input Validation

```python
def validate_pdf(pdf_path):
    """Validate PDF before processing"""
    from pypdf import PdfReader
    
    # Check file size
    max_size = 500 * 1024 * 1024  # 500MB
    if os.path.getsize(pdf_path) > max_size:
        raise ValueError("PDF too large")
    
    # Check if valid PDF
    try:
        reader = PdfReader(pdf_path)
        if len(reader.pages) > 2000:
            raise ValueError("Too many pages")
    except Exception as e:
        raise ValueError(f"Invalid PDF: {e}")
    
    return True
```

### 2. Sandboxing

Run OCR in isolated containers with resource limits:

```yaml
# docker-compose with security
services:
  ocr-agent:
    security_opt:
      - no-new-privileges:true
    read_only: true
    tmpfs:
      - /tmp
    cap_drop:
      - ALL
```

### 3. Access Control

```python
# API with authentication
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBearer

app = FastAPI()
security = HTTPBearer()

@app.post("/ocr")
async def ocr_endpoint(
    file: UploadFile,
    token: str = Depends(security)
):
    # Validate token
    if not validate_token(token):
        raise HTTPException(status_code=401)
    
    # Process
    # ...
```

## Cost Optimization

### AWS Cost Calculator

**ECS Fargate (4 vCPU, 8GB RAM):**
- Cost per hour: ~$0.20
- 500-page PDF processing: ~45 minutes
- Cost per PDF: ~$0.15

**Lambda (3GB RAM, 15 min timeout):**
- Cost per invocation: ~$0.08
- Best for: < 100 page PDFs
- Limitations: 15 min timeout, /tmp storage limit

**EC2 (c5.2xlarge):**
- Cost per hour: ~$0.34
- Reserved instance (1 year): ~$0.21/hour
- Best for: Continuous processing

### Recommendations

1. **Small volumes (< 100 PDFs/day):** Use Lambda or Fargate
2. **Medium volumes (100-1000 PDFs/day):** Use ECS with auto-scaling
3. **Large volumes (> 1000 PDFs/day):** Use dedicated EC2 with Spot instances
4. **Batch processing:** Schedule during off-peak hours

## Troubleshooting Production Issues

### Common Issues

**1. Out of Memory Errors**
- Reduce `--dpi` value
- Decrease `--workers`
- Process in smaller batches

**2. Slow Processing**
- Increase `--workers`
- Use GPU acceleration
- Consider PaddleOCR or Tesseract instead of EasyOCR

**3. Poor Accuracy**
- Increase `--dpi` to 600
- Use EasyOCR engine
- Preprocess images (deskew, denoise)

**4. Container Crashes**
- Check memory limits
- Review logs: `docker logs ocr-agent`
- Verify input PDF is valid

## Support & Maintenance

- Check logs: `tail -f ocr_agent.log`
- Monitor metrics: Prometheus/Grafana dashboard
- Update dependencies: `pip install -U -r requirements.txt`
- Regular backups of output files
- Version control for configuration

---

For additional help, refer to README.md or open an issue.
