#!/usr/bin/env python3
"""
Aether OCR Platform — Production Backend
"""

import os
os.environ["DISABLE_SQLALCHEMY_CEXT_RUNTIME"] = "1"
import sys
import collections
import platform
# Monkeypatch platform universally to bypass Windows WMI query hangs across all packages (like SQLAlchemy, pypdfium2, OpenAI, etc.)
uname_result = collections.namedtuple("uname_result", ["system", "node", "release", "version", "machine", "processor"])
platform.uname = lambda: uname_result("Windows", "localhost", "10", "10.0.19045", "AMD64", "Intel64 Family 6 Model 158 Stepping 10, GenuineIntel")
platform.machine = lambda: "AMD64"
platform.system = lambda: "Windows"
platform.platform = lambda *args, **kwargs: "Windows-10-10.0.19045-SP0"
platform.python_implementation = lambda: "CPython"
platform.python_version = lambda: "3.12.3"

# Dynamic injection of virtualenv site-packages to bypass Windows virtualenv launcher shim hangs
venv_site = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv12", "Lib", "site-packages")
if os.path.exists(venv_site):
    sys.path.insert(0, venv_site)
import uuid
import json
import glob
import shutil
import threading
import logging
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, send_file, session, Response, redirect, url_for
from flask_cors import CORS
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
import io
import pypdfium2 as pdfium

from ocr_engine import OCREngine
from form_mapper import DynamicFormMapper

# ── Celery (optional — falls back to threading if Redis not available) ──
USE_CELERY = False

# --- Mock SMS Vendor / OTP Handler ---
class MockSMSGateway:
    """
    Simulates a real SMS vendor like Twilio or Vonage.
    In a real app, you would use their Python SDK here.
    """
    def __init__(self):
        self.active_otps = {} # { phone: otp }
        
    def send_otp(self, phone: str):
        import random
        otp = str(random.randint(100000, 999999))
        self.active_otps[phone] = otp
        
        # LOG TO CONSOLE (Mimics receiving an SMS)
        print("\n" + "="*40)
        print(f"  [SMS GATEWAY] To: +91 {phone}")
        print(f"  [SMS GATEWAY] Message: Your Aether AI verification code is: {otp}")
        print("="*40 + "\n")
        return True

    def verify_otp(self, phone: str, otp: str):
        if phone in self.active_otps and self.active_otps[phone] == otp:
            del self.active_otps[phone]
            return True
        return False

sms_gateway = MockSMSGateway()


class TerminalFormatter(logging.Formatter):
    """Enhanced formatter that makes ERROR/WARNING stand out in terminal."""
    FORMATS = {
        logging.ERROR:   '\n' + '='*60 + '\n  ❌ ERROR: %(message)s\n  [%(asctime)s]\n' + '='*60,
        logging.WARNING: '\n⚠️  WARNING: %(message)s  [%(asctime)s]',
        logging.INFO:    '%(asctime)s - INFO - %(message)s',
    }
    def format(self, record):
        fmt = self.FORMATS.get(record.levelno, '%(asctime)s - %(levelname)s - %(message)s')
        formatter = logging.Formatter(fmt, datefmt='%H:%M:%S')
        return formatter.format(record)

handler = logging.StreamHandler()
handler.setFormatter(TerminalFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler])
logger = logging.getLogger(__name__)

# Load environment variables (API Keys, etc.)
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'aether-ocr-2035-secret'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['OUTPUT_FOLDER'] = 'outputs'
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024  # 1 GB for massive 2000-page PDFs
CORS(app)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///aether_ocr.db')
# Fix for Heroku/Render PostgreSQL URLs (postgres:// vs postgresql://)
if app.config['SQLALCHEMY_DATABASE_URI'].startswith("postgres://"):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Database Models
class Template(db.Model):
    __tablename__ = 'ocr_templates'
    id = db.Column(db.String(36), primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    schema = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'schema': self.schema,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class Case(db.Model):
    """
    A 'Case' represents a legal matter or a batch of related documents.
    """
    __tablename__ = 'cases'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    case_name = db.Column(db.String(255), nullable=False)
    client_id = db.Column(db.String(50), nullable=True)
    status = db.Column(db.String(50), default='active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    documents = db.relationship('Document', backref='case', lazy=True, cascade="all, delete-orphan")

    def to_dict(self):
        return {
            'id': self.id,
            'case_name': self.case_name,
            'client_id': self.client_id,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'document_count': len(self.documents)
        }

class Document(db.Model):
    """
    A 'Document' belongs to a Case and can have multiple processing Jobs.
    """
    __tablename__ = 'documents'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id = db.Column(db.String(36), db.ForeignKey('cases.id'), nullable=True)
    filename = db.Column(db.String(255), nullable=False)
    doc_type = db.Column(db.String(100), default='unknown') # Classified type
    total_pages = db.Column(db.Integer, default=0)
    upload_path = db.Column(db.String(512), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    jobs = db.relationship('Job', backref='document', lazy=True, cascade="all, delete-orphan")

    def to_dict(self):
        return {
            'id': self.id,
            'case_id': self.case_id,
            'filename': self.filename,
            'doc_type': self.doc_type,
            'total_pages': self.total_pages,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'job_count': len(self.jobs)
        }

class Job(db.Model):
    __tablename__ = 'ocr_jobs'
    job_id = db.Column(db.String(36), primary_key=True)
    document_id = db.Column(db.String(36), db.ForeignKey('documents.id'), nullable=True)
    template_id = db.Column(db.String(36), db.ForeignKey('ocr_templates.id'), nullable=True)
    filename = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(50), default='queued')
    progress = db.Column(db.Integer, default=0)
    current_page = db.Column(db.Integer, default=0)
    total_pages = db.Column(db.Integer, default=0)
    output_files = db.Column(db.JSON, default=list)
    error = db.Column(db.Text, nullable=True)
    language = db.Column(db.String(50), default='eng')
    dpi = db.Column(db.Integer, default=200)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    accuracy_score = db.Column(db.Float, nullable=True)
    is_locked = db.Column(db.Boolean, default=False)
    audit_summary = db.Column(db.JSON, default=dict)
    verified_json = db.Column(db.JSON, nullable=True)

    def to_dict(self):
        return {
            'job_id': self.job_id,
            'document_id': self.document_id,
            'template_id': self.template_id,
            'filename': self.filename,
            'status': self.status,
            'progress': self.progress,
            'current_page': self.current_page,
            'total_pages': self.total_pages,
            'output_files': self.output_files or [],
            'error': self.error,
            'language': self.language,
            'dpi': self.dpi,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'accuracy_score': self.accuracy_score,
            'is_locked': self.is_locked,
            'audit_summary': self.audit_summary or {},
        }

class DemoRequest(db.Model):
    __tablename__ = 'demo_requests'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), nullable=False)
    contact = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.String(50), default=lambda: datetime.now().isoformat())

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'email': self.email,
            'contact': self.contact,
            'created_at': self.created_at
        }

with app.app_context():
    db.create_all()

# Helper function to get job safely (since we use threading)
def get_job_by_id(job_id):
    with app.app_context():
        return Job.query.get(job_id)


def run_ocr_job(job_id: str, pdf_path: str, output_dir: str, language: str, dpi: int, workers: int):
    """
    Enterprise Threading Fallback (used if Redis is offline).
    Identical logic to tasks.py run_ocr_celery.
    """
    import gc
    from ocr_router import route_page
    from document_classifier import DocumentClassifier
    from case_builder import MasterCaseBuilder
    from neural_structurer import NeuralStructurer

    with app.app_context():
        job = Job.query.get(job_id)
        if not job: return
        
        try:
            # ── Step 1: Validate PDF ──
            job.status = 'processing'
            doc = pdfium.PdfDocument(pdf_path)
            total_pages = len(doc)
            job.total_pages = total_pages
            doc.close()
            db.session.commit()
            logger.info(f"Job {job_id}: {total_pages} pages detected (Threaded)")

            # ── Step 1.5: Setup Azure DI Client ──
            try:
                from azure.core.credentials import AzureKeyCredential
                from azure.ai.documentintelligence import DocumentIntelligenceClient
                endpoint = os.environ.get("AZURE_DI_ENDPOINT", "")
                key = os.environ.get("AZURE_DI_KEY", "")
                azure_client = DocumentIntelligenceClient(endpoint=endpoint, credential=AzureKeyCredential(key))
                logger.info("Azure Document Intelligence Client initialized successfully (Threaded)")
            except Exception as e:
                logger.error(f"Failed to initialize Azure DI Client (Threaded): {e}")
                azure_client = None

            # ── Step 2: Process Pages ──
            all_pages = []
            for page_index in range(total_pages):
                try:
                    page_result = route_page(
                        pdf_path=pdf_path,
                        page_index=page_index,
                        dpi=dpi,
                        language=language,
                        azure_client=azure_client
                    )
                    all_pages.append(page_result)
                    
                    # Update progress
                    job.current_page = page_index + 1
                    job.progress = int(((page_index + 1) / total_pages) * 100)
                    db.session.commit()
                    
                    if (page_index + 1) % 10 == 0: gc.collect()
                    
                except Exception as e:
                    logger.error(f"  Page {page_index+1} failed: {e}")
                    all_pages.append({"page_num": page_index + 1, "text": f"[Error: {e}]", "engine": "error", "is_blank": False})

            # ── Step 3: Classify & Structure ──
            job.status = 'classifying'
            db.session.commit()
            classifier = DocumentClassifier()
            for page in all_pages:
                if not page.get('is_blank') and page.get('text', '').strip():
                    page['classification'] = classifier.classify_page(page['text'], page['page_num'])
                else:
                    page['classification'] = {"type": "blank_page", "confidence": 1.0}

            # ── Step 4: Semantic JSON (Legacy support) ──
            job.status = 'refining'
            db.session.commit()
            full_text = "\n".join(p.get('text', '') for p in all_pages)
            
            schema_template = None
            if job.template_id:
                tmpl = Template.query.get(job.template_id)
                if tmpl: schema_template = tmpl.schema

            structurer = NeuralStructurer()
            refined_data = structurer.process(full_text, schema_template)
            
            pdf_stem = Path(job.filename).stem
            semantic_path = os.path.join(output_dir, f"{pdf_stem}_semantic.json")
            with open(semantic_path, 'w', encoding='utf-8') as f:
                json.dump(refined_data, f, indent=2, ensure_ascii=False)

            # ── Step 5: Build Master Case ──
            job.status = 'building_case'
            db.session.commit()
            builder = MasterCaseBuilder()
            builder.build(job_id, job.filename, all_pages, output_dir)

            # ── Step 6: Finalize ──
            output_files = [f"{pdf_stem}_semantic.json", "master_case.json"]
            # Add text file
            txt_path = os.path.join(output_dir, f"{pdf_stem}.txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                for p in all_pages:
                    f.write(f"\nPAGE {p['page_num']}\n{p.get('text', '')}\n")
            output_files.append(f"{pdf_stem}.txt")

            job.output_files = output_files
            job.status = 'completed'
            job.completed_at = datetime.utcnow()
            db.session.commit()
            logger.info(f"Job {job_id} completed via thread.")

        except Exception as e:
            with app.app_context():
                j = Job.query.get(job_id)
                if j:
                    j.status = 'failed'
                    j.error = str(e)
                    j.completed_at = datetime.utcnow()
                    db.session.commit()
            logger.error(f"Job {job_id} failed: {e}")


# ── Routes ──

@app.route('/')
def landing():
    return render_template('landing.html')


@app.route('/login')
def login_page():
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('landing'))


@app.route('/dashboard')
def dashboard():
    return render_template('index.html')


@app.route('/api/send_otp', methods=['POST'])
def send_otp_api():
    data = request.get_json() or {}
    phone = data.get('phone')
    if not phone or len(phone) != 10:
        return jsonify({'error': 'Invalid phone number'}), 400
    
    sms_gateway.send_otp(phone)
    return jsonify({'success': True, 'message': 'OTP sent successfully'})


@app.route('/api/login', methods=['POST'])
def login_api():
    data = request.get_json() or {}
    phone = data.get('phone', '9876543210') # Default for trial
    otp = data.get('otp')
    role = data.get('role', 'user')
    
    # In trial mode, we accept 123456 or the real mock OTP
    is_valid = sms_gateway.verify_otp(phone, otp) or otp == '123456'
    
    if is_valid:
        session['logged_in'] = True
        session['role'] = role
        session['phone'] = phone
        # Extract a name from phone for greeting
        session['user_name'] = f"User-{phone[-4:]}"
        return jsonify({
            'success': True, 
            'redirect': '/dashboard',
            'user_name': session['user_name']
        })
    
    return jsonify({'error': 'Invalid OTP'}), 401


@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400

    if not file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'Only PDF files are supported'}), 400

    job_id = str(uuid.uuid4())
    filename = secure_filename(file.filename)
    pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_id}_{filename}")
    file.save(pdf_path)
    import gc; gc.collect()

    language = request.form.get('language', 'eng')
    dpi = int(request.form.get('dpi', 200))
    workers = int(request.form.get('workers', 4))
    template_id = request.form.get('template_id')
    case_name = request.form.get('case_name') # Optional case name
    
    if template_id == '': template_id = None

    # ── 1. Handle Case ──
    case = None
    if case_name:
        case = Case.query.filter_by(case_name=case_name).first()
        if not case:
            case = Case(case_name=case_name)
            db.session.add(case)
            db.session.flush()

    # ── 2. Create Document ──
    doc = Document(
        case_id=case.id if case else None,
        filename=filename,
        upload_path=pdf_path
    )
    db.session.add(doc)
    db.session.flush()

    # ── 3. Create Job ──
    job = Job(
        job_id=job_id,
        document_id=doc.id,
        filename=filename,
        language=language,
        dpi=dpi,
        template_id=template_id
    )
    db.session.add(job)
    db.session.commit()

    output_dir = os.path.join(app.config['OUTPUT_FOLDER'], job_id)
    os.makedirs(output_dir, exist_ok=True)

    # ── Dispatch to Celery queue OR thread fallback ──
    if USE_CELERY:
        from tasks import run_ocr_celery
        run_ocr_celery.apply_async(
            args=[job_id, pdf_path, output_dir, language, dpi, workers],
            queue="ocr"
        )
        logger.info(f"Job {job_id} queued via Celery: {filename}")
    else:
        thread = threading.Thread(
            target=run_ocr_job,
            args=(job_id, pdf_path, output_dir, language, dpi, workers),
            daemon=True
        )
        thread.start()
        logger.info(f"Job {job_id} started via thread: {filename}")

    return jsonify({'job_id': job_id, 'filename': filename, 'message': 'Processing started', 'mode': 'celery' if USE_CELERY else 'thread'})


@app.route('/api/status/<job_id>')
def get_status(job_id):
    job = Job.query.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    return jsonify(job.to_dict())


@app.route('/api/jobs')
def list_jobs():
    jobs_list = Job.query.order_by(Job.started_at.desc()).all()
    return jsonify([j.to_dict() for j in jobs_list])


@app.route('/api/stats')
def get_stats():
    jobs = Job.query.all()
    total_jobs = len(jobs)
    completed_jobs = [j for j in jobs if j.status in ['ready_for_export', 'exported', 'completed']]
    total_pages = sum(j.total_pages for j in jobs if j.total_pages)
    
    avg_accuracy = 0
    if completed_jobs:
        valid_acc = [j.accuracy_score for j in completed_jobs if j.accuracy_score is not None]
        if valid_acc:
            avg_accuracy = round(sum(valid_acc) / len(valid_acc), 1)
            
    avg_duration_sec = 0
    durations = []
    for j in completed_jobs:
        if j.started_at and j.completed_at:
            try:
                start = datetime.fromisoformat(j.started_at)
                end = datetime.fromisoformat(j.completed_at)
                durations.append((end - start).total_seconds())
            except Exception:
                pass
    if durations:
        avg_duration_sec = sum(durations) / len(durations)
        
    return jsonify({
        'total_jobs': total_jobs,
        'completed_jobs': len(completed_jobs),
        'total_pages': total_pages,
        'avg_accuracy': avg_accuracy,
        'avg_duration_sec': round(avg_duration_sec)
    })


@app.route('/api/download/<job_id>/<filename>')
def download_file(job_id, filename):
    job = Job.query.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    file_path = os.path.join(app.config['OUTPUT_FOLDER'], job_id, filename)
    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404
    return send_file(file_path, as_attachment=True)


@app.route('/api/download_pdf/<job_id>')
def download_pdf(job_id):
    job = Job.query.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_id}_{job.filename}")
    if not os.path.exists(pdf_path):
        return jsonify({'error': 'Original PDF not found'}), 404
    return send_file(pdf_path, as_attachment=True, download_name=job.filename)


# ── HITL Validation APIs ──

@app.route('/api/semantic_data/<job_id>', methods=['GET'])
def get_semantic_data(job_id):
    job = Job.query.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
        
    filename = job.filename
    pdf_stem = Path(filename).stem
    semantic_path = os.path.join(app.config['OUTPUT_FOLDER'], job_id, f"{pdf_stem}_semantic.json")
    
    if not os.path.exists(semantic_path):
        return jsonify({'error': 'Semantic JSON not found. Was neural refinement successful?'}), 404
        
    with open(semantic_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return jsonify(data)

@app.route('/api/semantic_data/<job_id>', methods=['POST'])
def save_semantic_data(job_id):
    job = Job.query.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
        
    updated_data = request.get_json()
    if not updated_data:
        return jsonify({'error': 'Invalid JSON data'}), 400
        
    filename = job.filename
    pdf_stem = Path(filename).stem
    output_dir = os.path.join(app.config['OUTPUT_FOLDER'], job_id)
    original_path = os.path.join(output_dir, f"{pdf_stem}_semantic.json")
    verified_path = os.path.join(output_dir, f"{pdf_stem}_verified.json")
    
    # Calculate Accuracy vs Original
    original_data = {}
    if os.path.exists(original_path):
        with open(original_path, 'r', encoding='utf-8') as f:
            original_data = json.load(f)
    
    # Flatten comparison logic
    def flatten(d, parent_key='', sep='.'):
        items = []
        if isinstance(d, dict):
            for k, v in d.items():
                new_key = f"{parent_key}{sep}{k}" if parent_key else k
                if isinstance(v, dict) or isinstance(v, list):
                    items.extend(flatten(v, new_key, sep=sep).items())
                else:
                    items.append((new_key, str(v)))
        elif isinstance(d, list):
            for i, v in enumerate(d):
                new_key = f"{parent_key}[{i}]"
                if isinstance(v, dict) or isinstance(v, list):
                    items.extend(flatten(v, new_key, sep=sep).items())
                else:
                    items.append((new_key, str(v)))
        return dict(items)

    flat_orig = flatten(original_data)
    flat_updated = flatten(updated_data)
    
    total_fields = len(flat_orig)
    matches = 0
    audit_trail = []
    
    for k, v in flat_orig.items():
        upd_val = flat_updated.get(k)
        if upd_val == v:
            matches += 1
            audit_trail.append({
                'field': k,
                'machine': v,
                'human': upd_val,
                'status': 'matched',
                'accuracy': 100
            })
        else:
            audit_trail.append({
                'field': k,
                'machine': v,
                'human': upd_val,
                'status': 'corrected',
                'accuracy': 0
            })

    current_edit_count = job.audit_summary.get('edit_count', 0) if job.audit_summary else 0
    
    accuracy = (matches / total_fields * 100) if total_fields > 0 else 100
    job.accuracy_score = round(accuracy, 2)
    job.audit_summary = {
        'total_fields': total_fields,
        'matches': matches,
        'corrections': total_fields - matches,
        'trail': audit_trail,
        'edit_count': current_edit_count + 1
    }
    
    job.verified_json = updated_data
    job.status = 'ready_for_export'
    db.session.commit()

    with open(verified_path, 'w', encoding='utf-8') as f:
        json.dump(updated_data, f, ensure_ascii=False, indent=2)
        
    return jsonify({
        'success': True, 
        'message': 'JSON Verified and Audit Log Created',
        'accuracy': job.accuracy_score,
        'audit': job.audit_summary
    })

@app.route('/api/audit/<job_id>')
def get_audit_trail(job_id):
    job = Job.query.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    return jsonify(job.audit_summary)

@app.route('/api/download_verified/<job_id>')
def download_verified(job_id):
    job = Job.query.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
        
    filename = job.filename
    pdf_name = Path(filename).stem
    verified_path = os.path.join(app.config['OUTPUT_FOLDER'], job_id, f"{pdf_name}_verified.json")
    
    if not os.path.exists(verified_path):
        return jsonify({'error': 'Verified JSON not found. Please click "Save Verified Data" first.'}), 404
        
    return send_file(verified_path, as_attachment=True, download_name=f"{pdf_name}_verified.json")

@app.route('/api/download_raw/<job_id>')
def download_raw(job_id):
    job = Job.query.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
        
    filename = job.filename
    pdf_name = Path(filename).stem
    
    # In the new architecture, master_case.json is the full raw output.
    raw_path = os.path.join(app.config['OUTPUT_FOLDER'], job_id, "master_case.json")
    if not os.path.exists(raw_path):
        raw_path = os.path.join(app.config['OUTPUT_FOLDER'], job_id, f"{pdf_name}_combined.json")
        
    if not os.path.exists(raw_path):
        return jsonify({'error': 'Raw JSON not found'}), 404
        
    return send_file(raw_path, as_attachment=True, download_name=f"{pdf_name}_raw.json")

@app.route('/api/download_semantic/<job_id>')
def download_semantic(job_id):
    job = Job.query.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
        
    filename = job.filename
    pdf_name = Path(filename).stem
    semantic_path = os.path.join(app.config['OUTPUT_FOLDER'], job_id, f"{pdf_name}_semantic.json")
        
    if not os.path.exists(semantic_path):
        return jsonify({'error': 'Semantic JSON not found'}), 404
        
    return send_file(semantic_path, as_attachment=True, download_name=f"{pdf_name}_semantic.json")

@app.route('/api/raw_text/<job_id>')
def get_raw_text(job_id):
    job = Job.query.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
        
    filename = job.filename
    pdf_stem = Path(filename).stem
    txt_path = os.path.join(app.config['OUTPUT_FOLDER'], job_id, f"{pdf_stem}.txt")
    
    if not os.path.exists(txt_path):
        return jsonify({'error': 'Raw text file not found'}), 404
        
    with open(txt_path, 'r', encoding='utf-8') as f:
        content = f.read()
        
    return jsonify({'raw_text': content})

@app.route('/api/file_image/<job_id>/<int:page_num>')
def get_file_image(job_id, page_num):
    job = Job.query.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
        
    filename = job.filename
    # Note: original pdf is saved as {job_id}_{filename}
    pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_id}_{filename}")
    
    if not os.path.exists(pdf_path):
        return jsonify({'error': 'Original PDF not found'}), 404
        
    try:
        doc = pdfium.PdfDocument(pdf_path)
        if page_num < 1 or page_num > len(doc):
            return jsonify({'error': 'Invalid page number'}), 400
            
        page = doc[page_num - 1] # 0-indexed
        bitmap = page.render(scale=2.0) # Render at a decent scale for validation
        pil_image = bitmap.to_pil()
        page.close()
        doc.close()
        
        # Save to memory and serve
        img_io = io.BytesIO()
        pil_image.save(img_io, 'JPEG', quality=85)
        img_io.seek(0)
        return send_file(img_io, mimetype='image/jpeg')
    except Exception as e:
        logger.error(f"Error rendering PDF image: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/delete/<job_id>', methods=['DELETE'])
def delete_job(job_id):
    job = Job.query.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    try:
        for f in glob.glob(os.path.join(app.config['UPLOAD_FOLDER'], f"{job_id}_*")):
            os.remove(f)
        out_dir = os.path.join(app.config['OUTPUT_FOLDER'], job_id)
        if os.path.exists(out_dir):
            shutil.rmtree(out_dir)
        db.session.delete(job)
        db.session.commit()
        return jsonify({'message': 'Job deleted'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/jobs/bulk_delete', methods=['POST'])
def bulk_delete_jobs():
    data = request.get_json() or {}
    job_ids = data.get('job_ids', [])
    if not job_ids:
        return jsonify({'error': 'No job_ids provided'}), 400
        
    deleted_count = 0
    errors = []
    
    for job_id in job_ids:
        job = Job.query.get(job_id)
        if not job:
            continue
        try:
            for f in glob.glob(os.path.join(app.config['UPLOAD_FOLDER'], f"{job_id}_*")):
                try:
                    os.remove(f)
                except Exception as e:
                    logger.error(f"Failed to remove upload file {f}: {e}")
            out_dir = os.path.join(app.config['OUTPUT_FOLDER'], job_id)
            if os.path.exists(out_dir):
                try:
                    shutil.rmtree(out_dir)
                except Exception as e:
                    logger.error(f"Failed to remove output dir {out_dir}: {e}")
            db.session.delete(job)
            deleted_count += 1
        except Exception as e:
            logger.error(f"Failed to delete job {job_id} in bulk: {e}")
            errors.append(f"{job_id}: {str(e)}")
            
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Database transaction failed: {str(e)}'}), 500
        
    return jsonify({
        'message': f'Successfully deleted {deleted_count} job(s).',
        'failed_count': len(errors),
        'errors': errors
    })


@app.route('/health')
def health():
    active_jobs = Job.query.filter_by(status='processing').count()
    total_jobs = Job.query.count()
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'active_jobs': active_jobs,
        'total_jobs': total_jobs
    })

# ── Templates API ──

def extract_schema(data):
    """Recursively extracts the schema (keys and structure) from a JSON object, replacing values with empty strings or nulls."""
    if isinstance(data, dict):
        return {k: extract_schema(v) for k, v in data.items()}
    elif isinstance(data, list):
        if len(data) > 0:
            return [extract_schema(data[0])]  # Keep the structure of the first item
        return []
    else:
        return ""

@app.route('/api/templates', methods=['GET'])
def get_templates():
    templates = Template.query.order_by(Template.created_at.desc()).all()
    return jsonify([t.to_dict() for t in templates])

@app.route('/api/templates', methods=['POST'])
def save_template():
    data = request.json
    name = data.get('name')
    job_id = data.get('source_job_id')
    
    if not name or not job_id:
        return jsonify({'error': 'Name and source_job_id required'}), 400
        
    job = Job.query.get(job_id)
    if not job or not job.verified_json:
        return jsonify({'error': 'Job not found or not verified yet'}), 404
        
    schema = extract_schema(job.verified_json)
    
    template_id = str(uuid.uuid4())
    template = Template(id=template_id, name=name, schema=schema)
    db.session.add(template)
    db.session.commit()
    
    return jsonify({'success': True, 'template_id': template_id})


# ── DYNAMIC FORM MAPPING ──

TARGET_FORMS = {
    "hr_ats_form": {
        "name": "Standard HR ATS Form",
        "schema": {
            "candidate_profile": {
                "full_name": "",
                "contact_info": {"email": "", "phone": ""},
                "current_location": ""
            },
            "experience_timeline": [{"employer": "", "job_role": "", "duration": ""}],
            "top_technical_skills": [],
            "application_metadata": {"source": "Aether OCR", "processed_date": datetime.now().strftime("%Y-%m-%d")}
        }
    },
    "salesforce_lead": {
        "name": "Salesforce Candidate Lead",
        "schema": {
            "FirstName": "",
            "LastName": "",
            "Email": "",
            "MobilePhone": "",
            "Current_Company__c": "",
            "Technical_Skills__c": "",
            "LeadSource": "AI Extraction"
        }
    },
    "verification_report": {
        "name": "Background Verification Schema",
        "schema": {
            "subject_name": "",
            "education_verified": [{"institution": "", "degree": "", "pass_out_year": ""}],
            "employment_history": [{"company": "", "designation": ""}]
        }
    }
}

@app.route('/api/forms')
def list_target_forms():
    return jsonify([{"id": k, "name": v["name"]} for k, v in TARGET_FORMS.items()])

@app.route('/api/map_form/<job_id>', methods=['POST'])
def map_to_form(job_id):
    job = Job.query.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
        
    data = request.json
    form_id = data.get('form_id')
    if not form_id or form_id not in TARGET_FORMS:
        return jsonify({'error': 'Invalid target form ID'}), 400
        
    target_schema = TARGET_FORMS[form_id]["schema"]
    source_data = job.verified_json or job.audit_summary.get('verified_json') # Fallback if not verified yet
    
    # If not explicitly verified, use the latest audit or combined
    if not source_data:
        pdf_name = Path(f"{job_id}_{job.filename}").stem
        semantic_path = os.path.join(app.config['OUTPUT_FOLDER'], job_id, f"{pdf_name}_semantic.json")
        if os.path.exists(semantic_path):
            with open(semantic_path, 'r', encoding='utf-8') as f:
                source_data = json.load(f)

    if not source_data:
        return jsonify({'error': 'No structured data found for this job'}), 404

    try:
        mapper = DynamicFormMapper()
        mapped_result = mapper.map_data(source_data, target_schema)
        return jsonify({
            'success': True,
            'form_name': TARGET_FORMS[form_id]["name"],
            'mapped_data': mapped_result
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/map_custom_form/<job_id>', methods=['POST'])
def map_custom_form(job_id):
    job = Job.query.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
        
    data = request.get_json() or {}
    custom_schema = data.get('schema')
    if not custom_schema:
        return jsonify({'error': 'No custom schema provided'}), 400
        
    source_data = job.verified_json
    if not source_data:
        pdf_name = Path(f"{job_id}_{job.filename}").stem
        semantic_path = os.path.join(app.config['OUTPUT_FOLDER'], job_id, f"{pdf_name}_semantic.json")
        if os.path.exists(semantic_path):
            with open(semantic_path, 'r', encoding='utf-8') as f:
                source_data = json.load(f)

    if not source_data:
        return jsonify({'error': 'No structured data found'}), 404

    try:
        mapper = DynamicFormMapper()
        mapped_result = mapper.map_data(source_data, custom_schema)
        
        # After successful export, update status to 'exported'
        job.status = 'exported'
        db.session.commit()
        
        return jsonify({
            'success': True,
            'mapped_data': mapped_result
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/demo-request', methods=['POST'])
def handle_demo_request():
    data = request.get_json() or {}
    name = data.get('name')
    email = data.get('email')
    contact = data.get('contact')
    
    if not name or not email or not contact:
        return jsonify({'success': False, 'message': 'All fields are required.'}), 400
        
    try:
        demo_req = DemoRequest(name=name, email=email, contact=contact)
        db.session.add(demo_req)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Demo request saved successfully!'})
    except Exception as e:
        logger.error(f"Error saving demo request: {e}")
        return jsonify({'success': False, 'message': 'Internal server error.'}), 500

# ══════════════════════════════════════════════════════
# ENTERPRISE UPGRADE — NEW ENDPOINTS
# ══════════════════════════════════════════════════════

@app.route('/api/master_case/<job_id>', methods=['GET'])
def get_master_case(job_id):
    """Get master_case.json for a job."""
    job = Job.query.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    master_path = os.path.join(app.config['OUTPUT_FOLDER'], job_id, 'master_case.json')
    if not os.path.exists(master_path):
        return jsonify({'error': 'master_case.json not found. Job may still be processing.'}), 404
    with open(master_path, 'r', encoding='utf-8') as f:
        return jsonify(json.load(f))


@app.route('/api/generate_draft/<job_id>', methods=['POST'])
def generate_draft_api(job_id):
    """Generate legal draft from master_case.json."""
    job = Job.query.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404

    data = request.get_json() or {}
    draft_type = data.get('draft_type', 'sarfaesi_demand_notice')
    output_dir = os.path.join(app.config['OUTPUT_FOLDER'], job_id)
    master_path = os.path.join(output_dir, 'master_case.json')

    if not os.path.exists(master_path):
        return jsonify({'error': 'master_case.json not found'}), 404

    if USE_CELERY:
        from tasks import generate_draft_task
        task = generate_draft_task.apply_async(args=[job_id, draft_type, output_dir], queue='export')
        return jsonify({'success': True, 'message': 'Draft generation queued', 'task_id': task.id})
    else:
        with open(master_path, 'r', encoding='utf-8') as f:
            master_case = json.load(f)
        from draft_generator import LegalDraftGenerator
        generator = LegalDraftGenerator()
        result = generator.generate(master_case, draft_type, output_dir)
        if result.get('success'):
            files = job.output_files or []
            docx_name = Path(result['docx_path']).name
            if docx_name not in files:
                files.append(docx_name)
            job.output_files = files
            db.session.commit()
        return jsonify(result)


@app.route('/api/export_excel/<job_id>', methods=['POST'])
def export_excel_api(job_id):
    """Export job results to Excel."""
    job = Job.query.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404

    output_dir = os.path.join(app.config['OUTPUT_FOLDER'], job_id)
    master_path = os.path.join(output_dir, 'master_case.json')

    if not os.path.exists(master_path):
        return jsonify({'error': 'master_case.json not found. Complete OCR first.'}), 404

    if USE_CELERY:
        from tasks import export_excel_task
        task = export_excel_task.apply_async(args=[job_id, output_dir], queue='export')
        return jsonify({'success': True, 'message': 'Excel export queued', 'task_id': task.id})
    else:
        with open(master_path, 'r', encoding='utf-8') as f:
            master_case = json.load(f)
        from excel_exporter import export_to_excel
        xlsx_path = export_to_excel(master_case, output_dir)
        if xlsx_path:
            xlsx_name = Path(xlsx_path).name
            files = job.output_files or []
            if xlsx_name not in files:
                files.append(xlsx_name)
            job.output_files = files
            db.session.commit()
            return jsonify({'success': True, 'filename': xlsx_name, 'excel_path': xlsx_path})
        return jsonify({'error': 'Excel export failed'}), 500


@app.route('/api/draft_types', methods=['GET'])
def list_draft_types():
    """List available legal draft types."""
    from draft_generator import LegalDraftGenerator
    return jsonify([{'id': k, 'name': v} for k, v in LegalDraftGenerator.SUPPORTED_DRAFTS.items()])


@app.route('/api/classify_page', methods=['POST'])
def classify_page_api():
    """Classify a text snippet on-demand."""
    data = request.get_json() or {}
    text = data.get('text', '')
    if not text:
        return jsonify({'error': 'No text provided'}), 400
    from document_classifier import DocumentClassifier
    classifier = DocumentClassifier()
    result = classifier.classify_page(text)
    return jsonify(result)


@app.route('/api/confidence/<job_id>', methods=['GET'])
def get_confidence(job_id):
    """Get confidence scores for a job's master_case."""
    output_dir = os.path.join(app.config['OUTPUT_FOLDER'], job_id)
    master_path = os.path.join(output_dir, 'master_case.json')
    if not os.path.exists(master_path):
        return jsonify({'error': 'master_case.json not found'}), 404
    with open(master_path, 'r', encoding='utf-8') as f:
        master_case = json.load(f)
    return jsonify({
        'overall_confidence': master_case.get('overall_confidence'),
        'confidence_status': master_case.get('confidence_status'),
        'review_required_fields': master_case.get('review_required_fields', []),
        'confidence_map': master_case.get('confidence_map', {}),
    })


@app.route('/api/page_stats/<job_id>/<int:page_num>', methods=['GET'])
def get_page_stats(job_id, page_num):
    """Get blank/quality stats for a specific page (diagnostic)."""
    job = Job.query.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_id}_{job.filename}")
    if not os.path.exists(pdf_path):
        return jsonify({'error': 'PDF not found'}), 404
    try:
        doc = pdfium.PdfDocument(pdf_path)
        page = doc[page_num - 1]
        bitmap = page.render(scale=1.5)
        pil_image = bitmap.to_pil()
        page.close(); doc.close()
        from blank_page_detector import get_page_stats
        stats = get_page_stats(pil_image)
        return jsonify({'page_num': page_num, **stats})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/demo-requests', methods=['GET'])
def get_demo_requests():
    # Basic RBAC check
    if session.get('role') != 'admin':
        return jsonify({'error': 'Unauthorized access'}), 403
        
    try:
        requests = DemoRequest.query.order_by(DemoRequest.created_at.desc()).all()
        return jsonify({
            'success': True,
            'requests': [r.to_dict() for r in requests]
        })
    except Exception as e:
        logger.error(f"Error fetching demo requests: {e}")
        return jsonify({'error': str(e)}), 500
@app.route('/api/cases', methods=['GET'])
def list_cases():
    """List all legal cases."""
    cases = Case.query.order_by(Case.created_at.desc()).all()
    return jsonify([c.to_dict() for c in cases])


@app.route('/api/case/<case_id>', methods=['GET'])
def get_case_api(case_id):
    """Get details of a specific case and its documents."""
    case = Case.query.get(case_id)
    if not case:
        return jsonify({'error': 'Case not found'}), 404
    
    data = case.to_dict()
    data['documents'] = []
    for doc in case.documents:
        doc_dict = doc.to_dict()
        doc_dict['latest_job'] = doc.jobs[-1].to_dict() if doc.jobs else None
        data['documents'].append(doc_dict)
        
    return jsonify(data)


@app.route('/api/documents', methods=['GET'])
def list_documents():
    """List all documents across all cases."""
    docs = Document.query.order_by(Document.created_at.desc()).all()
    return jsonify([d.to_dict() for d in docs])


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("\n" + "="*60)
    print("  Aether OCR Platform — Production")
    print(f"  http://0.0.0.0:{port}")
    print("="*60 + "\n")
    
    with app.app_context():
        db.create_all()
        
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
