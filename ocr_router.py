"""
Aether OCR — Smart OCR Router
================================
Routes each page to the best OCR engine based on content type and quality.

Priority:
  1. pdfium digital extraction  → free, instant
  2. PaddleOCR PP-Structure     → primary OCR engine
  3. Azure Document Intelligence → difficult/noisy pages
  4. Tesseract                  → last resort fallback
"""

import os
import io
import logging
import numpy as np
import cv2
from PIL import Image
import pypdfium2 as pdfium
import pytesseract

from blank_page_detector import compute_image_quality, is_blank_page

logger = logging.getLogger(__name__)

# Windows Tesseract path
TESS_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if os.path.exists(TESS_PATH):
    pytesseract.pytesseract.tesseract_cmd = TESS_PATH

os.environ["OMP_THREAD_LIMIT"] = "1"

# Quality thresholds for routing decisions
QUALITY_GOOD = 0.45     # >= this → PaddleOCR
QUALITY_POOR = 0.20     # >= this → Azure DI, < this → Tesseract fallback


def route_page(
    pdf_path: str,
    page_index: int,
    dpi: int = 200,
    language: str = "eng",
    azure_client=None,
    doc=None,
) -> dict:
    """
    Main routing function.
    Returns: {text, engine, confidence, quality_score, is_blank}
    """
    result = {
        "page_num": page_index + 1,
        "text": "",
        "engine": "none",
        "confidence": 0.0,
        "quality_score": 0.0,
        "is_blank": False,
    }

    local_doc = None
    try:
        if doc is not None:
            active_doc = doc
        else:
            local_doc = pdfium.PdfDocument(pdf_path)
            active_doc = local_doc

        page = active_doc[page_index]

        # ── Step 1: Digital text extraction (FREE) ──
        textpage = page.get_textpage()
        digital_text = textpage.get_text_bounded().strip()
        textpage.close()

        # If user wants Azure DI for everything, bypass digital extraction
        if len(digital_text) > 50 and not azure_client:
            page.close()
            if local_doc is not None:
                local_doc.close()
            result.update({"text": digital_text, "engine": "digital", "confidence": 1.0, "quality_score": 1.0})
            logger.info(f"  Page {page_index+1}: [DIGITAL] {len(digital_text)} chars")
            return result

        # ── Step 2: Render image for visual OCR ──
        scale = dpi / 72.0
        bitmap = page.render(scale=scale, rotation=0)
        pil_image = bitmap.to_pil()
        page.close()
        if local_doc is not None:
            local_doc.close()

        # ── Step 3: Blank page check ──
        if is_blank_page(pil_image, digital_text):
            result.update({"is_blank": True, "engine": "skipped", "confidence": 1.0})
            logger.info(f"  Page {page_index+1}: [BLANK] → SKIPPED")
            return result

        # ── Step 4: Quality check → route decision ──
        quality = compute_image_quality(pil_image)
        result["quality_score"] = quality

        if azure_client:
            text, conf = _azure_di(pil_image, azure_client)
            result.update({"text": text, "engine": "azure_di", "confidence": conf})
            logger.info(f"  Page {page_index+1}: [Azure DI] Q={quality:.2f} → {len(text)} chars")

        elif quality >= QUALITY_GOOD:
            text, conf = _paddleocr(pil_image, language)
            result.update({"text": text, "engine": "paddleocr", "confidence": conf})
            logger.info(f"  Page {page_index+1}: [PaddleOCR] Q={quality:.2f} → {len(text)} chars")

        else:
            text, conf = _tesseract(pil_image, language)
            result.update({"text": text, "engine": "tesseract", "confidence": conf})
            logger.info(f"  Page {page_index+1}: [Tesseract] Q={quality:.2f} → {len(text)} chars")

        # Final fallback: if nothing got text, try Tesseract
        if not result["text"].strip() and result["engine"] != "tesseract":
            text, conf = _tesseract(pil_image, language)
            result.update({"text": text, "engine": "tesseract_fallback", "confidence": conf})
            logger.warning(f"  Page {page_index+1}: Primary OCR returned empty → Tesseract fallback")

    except Exception as e:
        logger.error(f"  Page {page_index+1}: Routing error → {e}")
        result["text"] = f"[ERROR: {e}]"
        result["engine"] = "error"

    return result


_paddleocr_instances = {}


def _paddleocr(pil_image: Image.Image, language: str = "eng") -> tuple:
    """PaddleOCR PP-Structure — primary engine."""
    try:
        from paddleocr import PaddleOCR
        lang_map = {"eng": "en", "hin": "hi", "chi_sim": "ch", "ara": "ar", "fra": "fr", "deu": "de"}
        lang = lang_map.get(language, "en")

        global _paddleocr_instances
        if lang not in _paddleocr_instances:
            logger.info(f"Initializing global PaddleOCR instance for language: {lang}")
            _paddleocr_instances[lang] = PaddleOCR(use_angle_cls=True, lang=lang, use_gpu=False, show_log=False)

        ocr = _paddleocr_instances[lang]
        img_array = np.array(pil_image)
        result = ocr.ocr(img_array, cls=True)

        if not result or not result[0]:
            return "", 0.5

        lines = []
        confidences = []
        for line in result[0]:
            bbox, (text, conf) = line
            if conf > 0.4:
                lines.append(text)
                confidences.append(conf)

        avg_conf = float(np.mean(confidences)) if confidences else 0.5
        return "\n".join(lines), round(avg_conf, 3)

    except ImportError:
        logger.warning("PaddleOCR not installed → falling back to Tesseract")
        return _tesseract(pil_image, language)
    except Exception as e:
        logger.error(f"PaddleOCR error: {e}")
        return _tesseract(pil_image, language)


def _azure_di(pil_image: Image.Image, azure_client) -> tuple:
    """Azure Document Intelligence — for difficult pages."""
    try:
        img_bytes = io.BytesIO()
        pil_image.save(img_bytes, format="JPEG", quality=90)
        img_bytes.seek(0)

        poller = azure_client.begin_analyze_document("prebuilt-read", img_bytes)
        result = poller.result()

        lines = [line.content for page in result.pages for line in page.lines]
        text = "\n".join(lines)

        # Azure doesn't return per-word confidence in basic tier; assume high
        return text, 0.92

    except Exception as e:
        logger.error(f"Azure DI error: {e} → Tesseract fallback")
        return _tesseract(pil_image, "eng")


def _tesseract(pil_image: Image.Image, language: str = "eng") -> tuple:
    """Tesseract — last resort fallback."""
    try:
        # Preprocess for Tesseract
        gray = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        processed = Image.fromarray(enhanced)

        text = pytesseract.image_to_string(
            processed, lang=language, config="--oem 3 --psm 3"
        ).strip()

        if len(text) < 50:
            text = pytesseract.image_to_string(
                processed, lang=language, config="--oem 3 --psm 11"
            ).strip()

        return text, 0.65

    except Exception as e:
        logger.error(f"Tesseract error: {e}")
        return "", 0.0
