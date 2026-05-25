"""
Aether OCR — Celery Tasks
===========================
All background tasks. These replace Flask threading.

Queue structure:
  ocr    → Heavy OCR work (CPU)
  llm    → OpenAI API calls
  export → File generation (docx, xlsx)
"""

import sys
import os

# Inject workspace directory and virtual environment site-packages
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
venv_site_packages = os.path.join(current_dir, "venv12", "Lib", "site-packages")
if os.path.exists(venv_site_packages) and venv_site_packages not in sys.path:
    sys.path.insert(0, venv_site_packages)
venv_standard = os.path.join(current_dir, "venv", "Lib", "site-packages")
if os.path.exists(venv_standard) and venv_standard not in sys.path:
    sys.path.insert(0, venv_standard)

import gc
import json
import logging
from datetime import datetime
from pathlib import Path

from celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="tasks.run_ocr_celery",
    queue="ocr",
    max_retries=2,
    autoretry_for=(Exception,),
    retry_backoff=True,
    soft_time_limit=3600,   # 1 hour max per job
)
def run_ocr_celery(self, job_id: str, pdf_path: str, output_dir: str,
                   language: str = "eng", dpi: int = 200, workers: int = 4):
    """
    Main OCR task. Replaces Flask background thread.
    Processes PDF in batches → classifies → builds master_case.json
    """
    from app import app, db, Job

    with app.app_context():
        job = Job.query.get(job_id)
        if not job:
            logger.error(f"Job {job_id} not found")
            return

        pdf_doc = None
        try:
            import pypdfium2 as pdfium
            from ocr_router import route_page
            from document_classifier import DocumentClassifier
            from case_builder import MasterCaseBuilder
            from confidence_engine import compute_page_confidence

            # ── Step 1: Validate PDF ──
            job.status = "processing"
            pdf_doc = pdfium.PdfDocument(pdf_path)
            total_pages = len(pdf_doc)
            job.total_pages = total_pages
            db.session.commit()
            logger.info(f"Job {job_id}: {total_pages} pages detected")

            # ── Step 2: Batch config & Azure DI Setup ──
            try:
                from azure.core.credentials import AzureKeyCredential
                from azure.ai.documentintelligence import DocumentIntelligenceClient
                # Using user-provided credentials for Azure Document Intelligence
                endpoint = os.environ.get("AZURE_DI_ENDPOINT", "")
                key = os.environ.get("AZURE_DI_KEY", "")
                azure_client = DocumentIntelligenceClient(endpoint=endpoint, credential=AzureKeyCredential(key))
                logger.info("Azure Document Intelligence Client initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Azure DI Client: {e}")
                azure_client = None

            BATCH_SIZE = 30
            batches = [
                list(range(i, min(i + BATCH_SIZE, total_pages)))
                for i in range(0, total_pages, BATCH_SIZE)
            ]

            # ── Step 3: Process batches sequentially ──
            all_pages = []
            completed = 0

            for batch_idx, batch in enumerate(batches):
                logger.info(f"  Batch {batch_idx+1}/{len(batches)} → Pages {batch[0]+1}–{batch[-1]+1}")

                for page_index in batch:
                    try:
                        page_result = route_page(
                            pdf_path=pdf_path,
                            page_index=page_index,
                            dpi=dpi,
                            language=language,
                            azure_client=azure_client,
                            doc=pdf_doc
                        )
                        all_pages.append(page_result)
                        completed += 1

                        # Live progress update
                        job.current_page = completed
                        job.progress = int((completed / total_pages) * 100)
                        db.session.commit()

                    except Exception as e:
                        logger.error(f"  Page {page_index+1} failed: {e}")
                        all_pages.append({
                            "page_num": page_index + 1,
                            "text": f"[ERROR: {e}]",
                            "engine": "error",
                            "confidence": 0.0,
                            "quality_score": 0.0,
                            "is_blank": False,
                        })

                # Memory release after each batch
                gc.collect()

            # ── Step 4: Document Classification ──
            job.status = "classifying"
            db.session.commit()
            logger.info(f"Job {job_id}: Classifying {len(all_pages)} pages...")

            classifier = DocumentClassifier()
            for page in all_pages:
                if not page.get("is_blank") and page.get("text", "").strip():
                    page["classification"] = classifier.classify_page(
                        page["text"], page["page_num"]
                    )
                else:
                    page["classification"] = {"type": "blank_page", "confidence": 1.0, "key_signals": []}

            # ── Step 5: Save raw text + combined JSON ──
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            pdf_stem = Path(pdf_path).stem
            clean_name = pdf_stem.split("_", 1)[1] if "_" in pdf_stem else pdf_stem

            txt_path = Path(output_dir) / f"{clean_name}.txt"
            with open(txt_path, "w", encoding="utf-8") as f:
                for p in all_pages:
                    f.write(f"\n{'='*60}\nPAGE {p['page_num']}\n{'='*60}\n")
                    f.write(p.get("text", "") + "\n\n")

            combined_path = Path(output_dir) / f"{clean_name}_combined.json"
            with open(combined_path, "w", encoding="utf-8") as f:
                json.dump({
                    "job_id": job_id,
                    "filename": job.filename,
                    "total_pages": total_pages,
                    "pages": [
                        {
                            "page_num": p["page_num"],
                            "engine": p.get("engine"),
                            "confidence": p.get("confidence", 0),
                            "is_blank": p.get("is_blank", False),
                            "doc_type": p.get("classification", {}).get("type", "other"),
                            "text": p.get("text", "")[:500],  # Truncate for combined JSON
                        }
                        for p in all_pages
                    ]
                }, f, indent=2, ensure_ascii=False)

            # ── Step 6: Neural Structuring (existing system, kept) ──
            job.status = "refining"
            db.session.commit()

            try:
                from neural_structurer import NeuralStructurer
                full_text = "\n".join(p.get("text", "") for p in all_pages)
                schema_template = None
                if job.template_id:
                    from app import Template
                    tmpl = Template.query.get(job.template_id)
                    if tmpl:
                        schema_template = tmpl.schema

                structurer = NeuralStructurer()
                refined_data = structurer.process(full_text, schema_template)
                semantic_path = Path(output_dir) / f"{clean_name}_semantic.json"
                with open(semantic_path, "w", encoding="utf-8") as f:
                    json.dump(refined_data, f, indent=2, ensure_ascii=False)
                logger.info(f"Semantic JSON saved: {semantic_path}")
            except Exception as e:
                logger.error(f"Neural structuring failed: {e}")
                semantic_path = None

            # ── Step 7: Build master_case.json ──
            job.status = "building_case"
            db.session.commit()

            try:
                builder = MasterCaseBuilder()
                master_case = builder.build(job_id, job.filename, all_pages, output_dir)
                master_case_path = Path(output_dir) / "master_case.json"
                logger.info(f"master_case.json built: {master_case_path}")
            except Exception as e:
                logger.error(f"master_case build failed: {e}")

            # ── Step 8: Final output file list ──
            output_files = []
            for fname in [f"{clean_name}.txt", f"{clean_name}_combined.json",
                          f"{clean_name}_semantic.json", "master_case.json"]:
                if (Path(output_dir) / fname).exists():
                    output_files.append(fname)

            # Add Excel file automatically
            try:
                master_case_path = Path(output_dir) / "master_case.json"
                if master_case_path.exists():
                    with open(master_case_path, "r", encoding="utf-8") as mc_f:
                        master_case = json.load(mc_f)
                    from excel_exporter import export_to_excel
                    xlsx_path = export_to_excel(master_case, output_dir)
                    if xlsx_path:
                        output_files.append(Path(xlsx_path).name)
            except Exception as ex_err:
                logger.error(f"Auto Excel export failed in run_ocr_celery: {ex_err}")

            # Calculate token usage
            total_prompt_tokens = 0
            total_completion_tokens = 0
            breakdown = {}

            if 'classifier' in locals() and classifier:
                total_prompt_tokens += getattr(classifier, 'prompt_tokens', 0)
                total_completion_tokens += getattr(classifier, 'completion_tokens', 0)
                breakdown['classifier'] = {
                    'prompt_tokens': getattr(classifier, 'prompt_tokens', 0),
                    'completion_tokens': getattr(classifier, 'completion_tokens', 0)
                }
            if 'structurer' in locals() and structurer:
                total_prompt_tokens += getattr(structurer, 'prompt_tokens', 0)
                total_completion_tokens += getattr(structurer, 'completion_tokens', 0)
                breakdown['structurer'] = {
                    'prompt_tokens': getattr(structurer, 'prompt_tokens', 0),
                    'completion_tokens': getattr(structurer, 'completion_tokens', 0)
                }
            if 'builder' in locals() and builder:
                total_prompt_tokens += getattr(builder, 'prompt_tokens', 0)
                total_completion_tokens += getattr(builder, 'completion_tokens', 0)
                breakdown['builder'] = {
                    'prompt_tokens': getattr(builder, 'prompt_tokens', 0),
                    'completion_tokens': getattr(builder, 'completion_tokens', 0)
                }

            current_summary = job.audit_summary or {}
            current_summary["token_usage"] = {
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "total_tokens": total_prompt_tokens + total_completion_tokens,
                "breakdown": breakdown
            }
            job.audit_summary = current_summary

            job.output_files = output_files
            job.status = "completed"
            job.progress = 100
            job.completed_at = datetime.utcnow()
            db.session.commit()
            logger.info(f"Job {job_id} COMPLETED. Files: {output_files}")

        except Exception as e:
            logger.error(f"Job {job_id} FAILED: {e}")
            job.status = "failed"
            job.error = str(e)
            job.completed_at = datetime.utcnow()
            db.session.commit()
            raise
        finally:
            if pdf_doc is not None:
                try:
                    pdf_doc.close()
                except Exception as e:
                    logger.error(f"Error closing pdf_doc in tasks: {e}")


@celery_app.task(name="tasks.generate_draft_task", queue="export")
def generate_draft_task(job_id: str, draft_type: str, output_dir: str):
    """Generate legal draft document from master_case.json."""
    from app import app, db, Job

    with app.app_context():
        job = Job.query.get(job_id)
        if not job:
            return {"error": "Job not found"}

        master_path = Path(output_dir) / "master_case.json"
        if not master_path.exists():
            return {"error": "master_case.json not found"}

        with open(master_path, "r", encoding="utf-8") as f:
            master_case = json.load(f)

        from draft_generator import LegalDraftGenerator
        generator = LegalDraftGenerator()
        result = generator.generate(master_case, draft_type, output_dir)

        if result.get("success"):
            # Update job output files
            files = job.output_files or []
            docx_name = Path(result["docx_path"]).name
            if docx_name not in files:
                files.append(docx_name)
            job.output_files = files
            db.session.commit()

        return result


@celery_app.task(name="tasks.export_excel_task", queue="export")
def export_excel_task(job_id: str, output_dir: str):
    """Export master_case.json to Excel."""
    from app import app, db, Job

    with app.app_context():
        job = Job.query.get(job_id)
        if not job:
            return {"error": "Job not found"}

        master_path = Path(output_dir) / "master_case.json"
        if not master_path.exists():
            return {"error": "master_case.json not found"}

        with open(master_path, "r", encoding="utf-8") as f:
            master_case = json.load(f)

        from excel_exporter import export_to_excel
        xlsx_path = export_to_excel(master_case, output_dir)

        if xlsx_path:
            files = job.output_files or []
            xlsx_name = Path(xlsx_path).name
            if xlsx_name not in files:
                files.append(xlsx_name)
            job.output_files = files
            db.session.commit()
            return {"success": True, "excel_path": xlsx_path, "filename": xlsx_name}

        return {"error": "Excel export failed"}
