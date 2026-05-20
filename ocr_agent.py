#!/usr/bin/env python3
"""
Enterprise-Ready OCR Agent
==========================
Production-grade OCR solution for large PDF files with multiple engine support,
parallel processing, and automatic output management.

Features:
- Multiple OCR engines (Tesseract, EasyOCR, PaddleOCR)
- Parallel page processing
- Progress tracking with rich UI
- Automatic output splitting into multiple files
- Error handling and recovery
- Support for 500+ page documents
"""

import os
import sys
import argparse
import logging
from pathlib import Path
from typing import List, Tuple, Optional
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
from datetime import datetime

# PDF and image processing
try:
    import pypdfium2 as pdfium
    PYPDFIUM2_AVAILABLE = True
except ImportError:
    PYPDFIUM2_AVAILABLE = False

from pdf2image import convert_from_path
from PIL import Image
import numpy as np

# OCR engines
import pytesseract
try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False

try:
    from paddleocr import PaddleOCR
    PADDLEOCR_AVAILABLE = True
except ImportError:
    PADDLEOCR_AVAILABLE = False

# Progress tracking
from tqdm import tqdm

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('ocr_agent.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class OCREngine:
    """Base class for OCR engines"""
    
    def __init__(self, language='eng'):
        self.language = language
    
    def process_image(self, image: Image.Image) -> str:
        raise NotImplementedError


class TesseractEngine(OCREngine):
    """Tesseract OCR Engine - Most reliable and fast"""
    
    def __init__(self, language='eng', config='--psm 3 --oem 3'):
        super().__init__(language)
        self.config = config
        logger.info(f"Initialized Tesseract with language: {language}")
    
    def process_image(self, image: Image.Image) -> str:
        try:
            # PSM 3: Fully automatic page segmentation (default)
            # OEM 3: Default, based on what is available
            text = pytesseract.image_to_string(
                image, 
                lang=self.language,
                config=self.config
            )
            return text.strip()
        except Exception as e:
            logger.error(f"Tesseract OCR error: {e}")
            return ""


class EasyOCREngine(OCREngine):
    """EasyOCR Engine - Better for non-English and complex layouts"""
    
    def __init__(self, language=['en'], gpu=True):
        super().__init__()
        if not EASYOCR_AVAILABLE:
            raise ImportError("EasyOCR not installed. Install with: pip install easyocr")
        
        self.reader = easyocr.Reader(language, gpu=gpu)
        logger.info(f"Initialized EasyOCR with languages: {language}")
    
    def process_image(self, image: Image.Image) -> str:
        try:
            # Convert PIL to numpy array
            img_array = np.array(image)
            results = self.reader.readtext(img_array)
            
            # Extract text with confidence filtering
            text_lines = []
            for detection in results:
                bbox, text, confidence = detection
                if confidence > 0.5:  # Filter low confidence
                    text_lines.append(text)
            
            return '\n'.join(text_lines)
        except Exception as e:
            logger.error(f"EasyOCR error: {e}")
            return ""


class PaddleOCREngine(OCREngine):
    """PaddleOCR Engine - Fast and accurate for Asian languages"""
    
    def __init__(self, language='en', use_gpu=False):
        super().__init__(language)
        if not PADDLEOCR_AVAILABLE:
            raise ImportError("PaddleOCR not installed. Install with: pip install paddleocr")
        
        self.ocr = PaddleOCR(
            use_angle_cls=True,
            lang=language,
            use_gpu=use_gpu,
            show_log=False
        )
        logger.info(f"Initialized PaddleOCR with language: {language}")
    
    def process_image(self, image: Image.Image) -> str:
        try:
            img_array = np.array(image)
            result = self.ocr.ocr(img_array, cls=True)
            
            if not result or not result[0]:
                return ""
            
            # Extract text
            text_lines = []
            for line in result[0]:
                text_lines.append(line[1][0])
            
            return '\n'.join(text_lines)
        except Exception as e:
            logger.error(f"PaddleOCR error: {e}")
            return ""


class OCRAgent:
    """Main OCR Agent for processing large PDF files"""
    
    def __init__(
        self,
        pdf_path: str,
        output_dir: str = "ocr_output",
        engine: str = "tesseract",
        language: str = "eng",
        dpi: int = 300,
        num_workers: int = 4,
        split_files: int = 2
    ):
        self.pdf_path = Path(pdf_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.dpi = dpi
        self.num_workers = num_workers
        self.split_files = split_files
        
        # Initialize OCR engine
        self.engine_type = engine
        self.engine = self._init_engine(engine, language)
        
        # Metadata
        self.metadata = {
            'pdf_path': str(self.pdf_path),
            'engine': engine,
            'language': language,
            'dpi': dpi,
            'timestamp': datetime.now().isoformat()
        }
        
        logger.info(f"OCR Agent initialized for: {self.pdf_path}")
        logger.info(f"Output directory: {self.output_dir}")
    
    def _init_engine(self, engine_name: str, language: str) -> OCREngine:
        """Initialize the specified OCR engine"""
        if engine_name == "tesseract":
            return TesseractEngine(language=language)
        elif engine_name == "easyocr":
            lang_map = {'eng': 'en', 'fra': 'fr', 'deu': 'de', 'spa': 'es'}
            lang = lang_map.get(language, 'en')
            return EasyOCREngine(language=[lang])
        elif engine_name == "paddleocr":
            lang_map = {'eng': 'en', 'chi_sim': 'ch', 'chi_tra': 'chinese_cht'}
            lang = lang_map.get(language, 'en')
            return PaddleOCREngine(language=lang)
        else:
            raise ValueError(f"Unknown engine: {engine_name}")
    
    def process_page(self, page_info: Tuple[int, Image.Image]) -> Tuple[int, str]:
        """Process a single page with OCR"""
        page_num, image = page_info
        try:
            text = self.engine.process_image(image)
            logger.debug(f"Processed page {page_num}: {len(text)} characters")
            return page_num, text
        except Exception as e:
            logger.error(f"Error processing page {page_num}: {e}")
            return page_num, f"[ERROR: Page {page_num} - {str(e)}]\n"
    
    def convert_pdf_to_images(self, batch_size: int = 50) -> List[Image.Image]:
        """Convert PDF to images in batches to manage memory"""
        logger.info(f"Converting PDF to images (DPI: {self.dpi})...")
        
        try:
            # Try pypdfium2 first (no external dependencies)
            if PYPDFIUM2_AVAILABLE:
                logger.info("Using pypdfium2 for conversion...")
                pdf = pdfium.PdfDocument(str(self.pdf_path))
                all_images = []
                
                # Scale factor for DPI (72 is default PDF DPI)
                scale = self.dpi / 72
                
                for i in tqdm(range(len(pdf)), desc="Converting pages"):
                    page = pdf[i]
                    bitmap = page.render(scale=scale)
                    pil_image = bitmap.to_pil()
                    all_images.append(pil_image)
                
                return all_images
            
            # Fallback to pdf2image (requires poppler)
            logger.info("Using pdf2image for conversion (requires poppler)...")
            from pypdf import PdfReader
            reader = PdfReader(str(self.pdf_path))
            total_pages = len(reader.pages)
            logger.info(f"Total pages: {total_pages}")
            
            all_images = []
            
            # Process in batches to avoid memory issues
            for start_page in tqdm(range(1, total_pages + 1, batch_size), 
                                  desc="Converting PDF batches"):
                end_page = min(start_page + batch_size - 1, total_pages)
                
                images = convert_from_path(
                    str(self.pdf_path),
                    dpi=self.dpi,
                    first_page=start_page,
                    last_page=end_page,
                    fmt='jpeg'  # JPEG uses less memory than PNG
                )
                all_images.extend(images)
                
                logger.info(f"Converted pages {start_page}-{end_page}")
            
            return all_images
            
        except Exception as e:
            logger.error(f"Error converting PDF to images: {e}")
            if not PYPDFIUM2_AVAILABLE and "poppler" in str(e).lower():
                logger.error("TIP: Install pypdfium2 to avoid poppler dependency: pip install pypdfium2")
            raise
    
    def process_pdf_chunked(self, chunk_size: int = 20, progress_callback=None) -> List[dict]:
        """Process entire PDF in small chunks to keep memory usage low (Enterprise Logic)"""
        logger.info(f"Starting Enterprise Chunked OCR (Chunk Size: {chunk_size})...")
        
        pdf = pdfium.PdfDocument(str(self.pdf_path))
        total_pages = len(pdf)
        scale = self.dpi / 72
        
        all_results = {}
        
        for start_page in range(0, total_pages, chunk_size):
            end_page = min(start_page + chunk_size, total_pages)
            logger.info(f"Processing Chunk: Pages {start_page+1} to {end_page}")
            
            # 1. Convert only the current chunk to images
            chunk_images = []
            for i in range(start_page, end_page):
                page = pdf[i]
                bitmap = page.render(scale=scale)
                chunk_images.append((i + 1, bitmap.to_pil()))
                page.close() # Immediate cleanup
            
            # 2. Process chunk in parallel (ThreadPool is more stable on Windows Flask threads)
            from concurrent.futures import ThreadPoolExecutor
            try:
                with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
                    futures = {executor.submit(self.process_page, data): data[0] for data in chunk_images}
                    for future in as_completed(futures):
                        p_num, text = future.result()
                        all_results[p_num] = {
                            "page_num": p_num,
                            "text": text,
                            "engine": self.engine_type,
                            "is_blank": len(text.strip()) < 10
                        }
                        if progress_callback:
                            progress_callback(p_num, total_pages)
            except Exception as e:
                logger.error(f"Parallel chunk failed: {e}. Falling back to sequential for this chunk.")
                for p_num, img in chunk_images:
                    p_num, text = self.process_page((p_num, img))
                    all_results[p_num] = {"page_num": p_num, "text": text, "engine": self.engine_type, "is_blank": len(text.strip()) < 10}
                    if progress_callback: progress_callback(p_num, total_pages)
            
            # 3. Explicit Memory Cleanup
            chunk_images.clear()
            import gc
            gc.collect()
        
        pdf.close()
        
        # Sort and return
        return [all_results[i] for i in sorted(all_results.keys())]

    def process_pdf(self) -> List[str]:
        """Legacy entry point — redirects to chunked processing for enterprise stability"""
        return self.process_pdf_chunked(chunk_size=20)
    
    def split_and_save(self, pages: List[str]) -> List[str]:
        """Split OCR results into multiple files and save"""
        total_pages = len(pages)
        pages_per_file = total_pages // self.split_files
        
        output_files = []
        
        for file_idx in range(self.split_files):
            start_idx = file_idx * pages_per_file
            
            # Last file gets remaining pages
            if file_idx == self.split_files - 1:
                end_idx = total_pages
            else:
                end_idx = start_idx + pages_per_file
            
            # Get pages for this file
            file_pages = pages[start_idx:end_idx]
            
            # Create output file
            output_file = self.output_dir / f"ocr_output_part{file_idx + 1}.txt"
            
            with open(output_file, 'w', encoding='utf-8') as f:
                # Write header
                f.write(f"{'='*80}\n")
                f.write(f"OCR Output - Part {file_idx + 1} of {self.split_files}\n")
                f.write(f"Pages: {start_idx + 1} to {end_idx}\n")
                f.write(f"Source: {self.pdf_path.name}\n")
                f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"{'='*80}\n\n")
                
                # Write pages
                for page_idx, page_text in enumerate(file_pages, start=start_idx + 1):
                    f.write(f"\n{'='*80}\n")
                    f.write(f"PAGE {page_idx}\n")
                    f.write(f"{'='*80}\n\n")
                    f.write(page_text)
                    f.write("\n\n")
            
            output_files.append(str(output_file))
            logger.info(f"Saved: {output_file} ({len(file_pages)} pages)")
        
        # Save metadata
        metadata_file = self.output_dir / "ocr_metadata.json"
        self.metadata.update({
            'total_pages': total_pages,
            'output_files': output_files,
            'pages_per_file': pages_per_file
        })
        
        with open(metadata_file, 'w') as f:
            json.dump(self.metadata, f, indent=2)
        
        logger.info(f"Metadata saved: {metadata_file}")
        
        return output_files
    
    def run(self) -> List[str]:
        """Execute the complete OCR workflow"""
        try:
            # Process PDF
            pages = self.process_pdf()
            
            # Split and save results
            output_files = self.split_and_save(pages)
            
            logger.info("="*80)
            logger.info("OCR PROCESSING COMPLETED SUCCESSFULLY!")
            logger.info(f"Total pages processed: {len(pages)}")
            logger.info(f"Output files: {len(output_files)}")
            for f in output_files:
                logger.info(f"  - {f}")
            logger.info("="*80)
            
            return output_files
            
        except Exception as e:
            logger.error(f"OCR processing failed: {e}")
            raise


def main():
    parser = argparse.ArgumentParser(
        description="Enterprise-Ready OCR Agent for Large PDF Files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage with Tesseract
  python ocr_agent.py document.pdf
  
  # Use EasyOCR with 8 parallel workers
  python ocr_agent.py document.pdf --engine easyocr --workers 8
  
  # High-quality OCR with custom output directory
  python ocr_agent.py document.pdf --dpi 600 --output results/
  
  # Split output into 3 files instead of 2
  python ocr_agent.py document.pdf --split 3
  
  # Process Hindi document with Tesseract
  python ocr_agent.py hindi_doc.pdf --language hin
        """
    )
    
    parser.add_argument(
        'pdf_path',
        help='Path to the PDF file to process'
    )
    
    parser.add_argument(
        '--output', '-o',
        default='ocr_output',
        help='Output directory (default: ocr_output)'
    )
    
    parser.add_argument(
        '--engine', '-e',
        choices=['tesseract', 'easyocr', 'paddleocr'],
        default='tesseract',
        help='OCR engine to use (default: tesseract)'
    )
    
    parser.add_argument(
        '--language', '-l',
        default='eng',
        help='OCR language (default: eng). Examples: eng, hin, fra, deu, spa, chi_sim'
    )
    
    parser.add_argument(
        '--dpi',
        type=int,
        default=300,
        help='DPI for PDF to image conversion (default: 300, higher = better quality but slower)'
    )
    
    parser.add_argument(
        '--workers', '-w',
        type=int,
        default=4,
        help='Number of parallel workers (default: 4)'
    )
    
    parser.add_argument(
        '--split', '-s',
        type=int,
        default=2,
        help='Number of output files to split into (default: 2)'
    )
    
    args = parser.parse_args()
    
    # Validate PDF exists
    if not Path(args.pdf_path).exists():
        print(f"Error: PDF file not found: {args.pdf_path}")
        sys.exit(1)
    
    # Create agent and run
    agent = OCRAgent(
        pdf_path=args.pdf_path,
        output_dir=args.output,
        engine=args.engine,
        language=args.language,
        dpi=args.dpi,
        num_workers=args.workers,
        split_files=args.split
    )
    
    output_files = agent.run()
    
    print("\n" + "="*80)
    print("SUCCESS! OCR processing completed.")
    print(f"\nOutput files created:")
    for f in output_files:
        print(f"  ✓ {f}")
    print("="*80)


if __name__ == "__main__":
    main()
