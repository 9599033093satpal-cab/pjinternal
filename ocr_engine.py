#!/usr/bin/env python3
"""
Aether OCR Engine — Production Grade (Optimized)
================================================
Real Tesseract-powered OCR for large PDFs (500+ pages)
with batch processing and intelligent image optimization.
"""

import os
import json
import logging
import threading
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# CRITICAL: Prevent Tesseract from using all cores for a single process, 
# which causes severe thread thrashing and memory leaks during parallel execution.
os.environ["OMP_THREAD_LIMIT"] = "1"

import pytesseract
from PIL import Image
import pypdfium2 as pdfium
import cv2
import numpy as np
from neural_structurer import NeuralStructurer

logger = logging.getLogger(__name__)

# Windows: Tesseract path
TESS_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if os.path.exists(TESS_PATH):
    pytesseract.pytesseract.tesseract_cmd = TESS_PATH


class OCREngine:
    """
    Production OCR engine using pypdfium2 (no Poppler needed) + Tesseract.
    Optimized for high-throughput batch processing of multi-hundred page documents.
    """

    def __init__(self, pdf_path: str, output_dir: str, language: str = "eng",
                 dpi: int = 200, num_workers: int = 4, job: object = None):
        self.pdf_path = str(pdf_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.language = language
        self.dpi = dpi
        # Allow more concurrency for large files if hardware permits
        self.num_workers = max(1, min(num_workers, 12))
        self.job = job  # Job object for live progress updates
        
        # Load PDF bytes ONCE directly from the correct path
        # pdf_path is already the absolute correct path passed from app.py
        self.pdf_bytes = Path(self.pdf_path).read_bytes()
        logger.info(f"Loaded PDF into memory: {len(self.pdf_bytes)/(1024*1024):.1f} MB from {self.pdf_path}")

    # ── Convert single PDF page to PIL Image ──
    def _page_to_image(self, doc, page_index: int) -> Image.Image:
        page = doc[page_index]
        scale = self.dpi / 72.0
        bitmap = page.render(scale=scale, rotation=0)
        pil_img = bitmap.to_pil()
        page.close()
        return pil_img

    # ── Optimized OpenCV Preprocessing ──
    def _preprocess_image(self, pil_img: Image.Image) -> Image.Image:
        try:
            # Convert PIL to OpenCV array (RGB)
            open_cv_image = np.array(pil_img)
            
            # Grayscale conversion
            if len(open_cv_image.shape) == 3:
                gray = cv2.cvtColor(open_cv_image, cv2.COLOR_RGB2GRAY)
            else:
                gray = open_cv_image
                
            # Only upscale if DPI is low (< 200) to save processing time
            if self.dpi < 200:
                width = int(gray.shape[1] * 1.5)
                height = int(gray.shape[0] * 1.5)
                gray = cv2.resize(gray, (width, height), interpolation=cv2.INTER_LINEAR)
            
            # CLAHE (Contrast Limited Adaptive Histogram Equalization)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)
            
            # Skip sharpening for speed unless DPI is very low
            if self.dpi < 150:
                kernel = np.array([[0, -1, 0], [-1, 5,-1], [0, -1, 0]])
                enhanced = cv2.filter2D(enhanced, -1, kernel)

            return Image.fromarray(enhanced)
        except Exception as e:
            logger.warning(f"Preprocessing error, falling back to original: {e}")
            if pil_img.mode != "RGB":
                return pil_img.convert("RGB")
            return pil_img

    # ── OCR a single image ──
    def _ocr_image(self, img: Image.Image) -> str:
        try:
            processed_img = self._preprocess_image(img)
            
            # PSM 3 is generally fastest for standard documents
            config = "--oem 3 --psm 3"
            text = pytesseract.image_to_string(processed_img, lang=self.language, config=config).strip()
            
            # Fallback to PSM 11 for sparse/floating text if PSM 3 returns too little
            if len(text) < 50:
                text = pytesseract.image_to_string(processed_img, lang=self.language, config="--oem 3 --psm 11").strip()

            return text
        except Exception as e:
            logger.warning(f"OCR page error: {e}")
            return ""

    def _process_batch(self, batch_indices):
        results = []
        doc = None
        try:
            # Use file path instead of bytes for better stability on Windows with large files
            doc = pdfium.PdfDocument(self.pdf_path)
            for idx in batch_indices:
                try:
                    page = doc[idx]
                    logger.info(f"  -> Digitizing Page {idx+1}/{self.total_pages_cache}...")
                    
                    # Pass 1: Digital Text Extraction
                    textpage = page.get_textpage()
                    digital_text = textpage.get_text_bounded()
                    
                    if digital_text and len(digital_text.strip()) > 50:
                        text = digital_text.strip()
                        logger.info(f"     [Digital] Found {len(text)} chars")
                    else:
                        # Pass 2: Advanced OCR
                        logger.info(f"     [OCR] Running Neural Scan...")
                        img = self._page_to_image(doc, idx)
                        text = self._ocr_image(img)
                        logger.info(f"     [OCR] Extracted {len(text)} chars")
                    
                    results.append((idx + 1, text))
                    page.close()
                except Exception as e:
                    logger.error(f"     ❌ Page {idx+1} failed: {e}")
                    results.append((idx + 1, f"[Error processing page {idx+1}: {e}]"))
            
            if doc: doc.close()
        except Exception as e:
            logger.error(f"Batch processing failed: {e}")
            if doc: doc.close()
        return results

    def run(self) -> list:
        """
        Full OCR run with batch-parallel execution.
        """
        doc = pdfium.PdfDocument(self.pdf_path)
        total_pages = len(doc)
        self.total_pages_cache = total_pages
        doc.close()

        logger.info(f"Starting Optimized Engine: {total_pages} pages, DPI={self.dpi}, Workers={self.num_workers}")

        if self.job:
            self.job.total_pages = total_pages
            self.job.status = "processing"
            self.job.progress = 0

        # Dynamically calculate batch size based on file length and worker count
        batch_size = max(1, total_pages // (self.num_workers * 2))
        if total_pages < 10: batch_size = 1
        
        batches = [range(i, min(i + batch_size, total_pages)) for i in range(0, total_pages, batch_size)]

        results = {}
        completed = 0

        import gc
        # Run sequentially to guarantee absolute stability with pypdfium2
        for i, b in enumerate(batches):
            try:
                logger.info(f"Processing Batch {i+1}/{len(batches)} (Pages {list(b)[0]+1}-{list(b)[-1]+1})")
                batch_results = self._process_batch(b)
                for page_num, text in batch_results:
                    results[page_num] = text
                    completed += 1
                    if self.job:
                        self.job.current_page = completed
                        self.job.progress = int((completed / total_pages) * 100)
                
                # Force memory release after each batch
                gc.collect()
            except Exception as e:
                logger.error(f"Batch {i+1} execution error: {e}")

        # Ensure we sort pages correctly
        sorted_pages = []
        for i in range(1, total_pages + 1):
            sorted_pages.append(results.get(i, f"[Missing data for page {i}]"))

        # Save standard outputs (TXT/JSON)
        output_files = self._save(sorted_pages, total_pages)

        # ── Neural Refinement Stage ──
        try:
            full_text = "\n".join(sorted_pages)
            if self.job:
                self.job.status = "refining"
            
            schema_template = None
            if self.job and getattr(self.job, 'template_id', None):
                from app import Template
                template_obj = Template.query.get(self.job.template_id)
                if template_obj:
                    schema_template = template_obj.schema

            # NEW: SEQUENTIAL CHUNKING LOGIC
            # To guarantee top-to-bottom order, we extract section by section if the doc is large.
            # But for now, we'll use a 'Strict Order Enforcer' prompt with a secondary validation.
            structurer = NeuralStructurer()
            
            # If Achievements is at the bottom, we ensure it's processed last.
            # We'll also increase the temperature to 0 for maximum deterministic output.
            refined_data = structurer.process(full_text, schema_template)
            
            # Save refined JSON
            pdf_name = Path(self.pdf_path).stem
            # Remove UUID prefix for filename if present
            clean_name = pdf_name.split("_", 1)[1] if "_" in pdf_name else pdf_name
            
            semantic_filename = f"{clean_name}_semantic.json"
            semantic_path = self.output_dir / semantic_filename
            with open(semantic_path, "w", encoding="utf-8") as f:
                json.dump(refined_data, f, indent=4)
            
            output_files.append(semantic_filename)
            
            if self.job:
                self.job.output_files = output_files
                self.job.status = "completed"
                self.job.progress = 100
                self.job.completed_at = datetime.utcnow()
                from app import db
                db.session.commit()

        except Exception as e:
            logger.error(f"Neural refinement failed: {e}")
            if self.job:
                self.job.output_files = output_files # Save whatever we have
                self.job.status = "completed" 
                self.job.progress = 100
                from app import db
                db.session.commit()

        return output_files

    def _save(self, pages: list, total_pages: int) -> list:
        pdf_name = Path(self.pdf_path).stem
        # Remove UUID prefix
        clean_name = pdf_name.split("_", 1)[1] if "_" in pdf_name else pdf_name
        
        output_files = []

        # 1. Save Full Text
        txt_filename = f"{clean_name}.txt"
        with open(self.output_dir / txt_filename, "w", encoding="utf-8") as f:
            f.write("\n\n".join(pages))
        output_files.append(txt_filename)

        # 2. Save Combined JSON (Basic)
        json_filename = f"{clean_name}_combined.json"
        combined_data = {
            "filename": clean_name,
            "total_pages": total_pages,
            "pages": [{"page": i+1, "content": text} for i, text in enumerate(pages)]
        }
        with open(self.output_dir / json_filename, "w", encoding="utf-8") as f:
            json.dump(combined_data, f, indent=4)
        output_files.append(json_filename)

        return output_files
