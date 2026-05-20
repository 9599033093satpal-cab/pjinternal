"""
Aether OCR — Confidence Scoring Engine
=========================================
Computes confidence score for each extracted field and page.

Formula:
  confidence = (ocr_weight * ocr_score)
             + (density_weight * density_score)
             + (llm_weight * llm_score)
             + (cross_weight * cross_score)

Thresholds:
  >= 0.85 → Auto-approve (green)
  0.60–0.84 → Flag for human review (yellow)
  < 0.60 → Mandatory correction (red)
"""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Score weights
W_OCR = 0.30
W_DENSITY = 0.20
W_LLM = 0.30
W_CROSS = 0.20

# Per-engine base scores
ENGINE_SCORES = {
    "digital":          1.00,
    "paddleocr":        0.87,
    "azure_di":         0.92,
    "tesseract":        0.65,
    "tesseract_fallback": 0.55,
    "error":            0.00,
    "skipped":          1.00,
    "none":             0.00,
}

# Review thresholds
AUTO_APPROVE = 0.85
HUMAN_REVIEW = 0.60


def compute_page_confidence(page_result: dict) -> float:
    """
    Compute confidence score for a single page OCR result.
    page_result: {engine, text, quality_score, ...}
    """
    # 1. OCR engine score
    ocr_score = ENGINE_SCORES.get(page_result.get("engine", "none"), 0.5)

    # 2. Text density score (500 chars = good page)
    char_count = len(page_result.get("text", ""))
    density_score = min(char_count / 500.0, 1.0)

    # 3. LLM confidence (from classification or extraction)
    llm_score = float(page_result.get("classification", {}).get("confidence", 0.75))

    # 4. Cross-validation (default 0.7 until cross-validation runs)
    cross_score = float(page_result.get("cross_validation_score", 0.70))

    final = (
        W_OCR * ocr_score
        + W_DENSITY * density_score
        + W_LLM * llm_score
        + W_CROSS * cross_score
    )
    return round(final, 3)


def compute_field_confidence(
    field_value: str,
    field_name: str,
    page_confidence: float,
    llm_field_confidence: Optional[float] = None,
    cross_page_match: bool = False,
) -> dict:
    """
    Compute confidence for a specific extracted field.
    Returns: {score, status, color, needs_review}
    """
    score = page_confidence

    # Bonus: Field passes format validation
    if _validate_field_format(field_name, field_value):
        score = min(score + 0.08, 1.0)

    # Bonus: LLM said it's confident
    if llm_field_confidence is not None:
        score = (score + llm_field_confidence) / 2

    # Bonus: Same value found on multiple pages (strong signal)
    if cross_page_match:
        score = min(score + 0.10, 1.0)

    # Penalty: Empty or placeholder value
    val_str = str(field_value).strip() if field_value is not None else ""
    if not val_str or val_str.lower() in ["", "null", "n/a", "none", "unknown", "[]", "{}"]:
        score = 0.0

    score = round(score, 3)
    status, color = _get_status(score)

    return {
        "score": score,
        "status": status,
        "color": color,
        "needs_review": score < AUTO_APPROVE,
    }


def score_master_case(master_case: dict) -> dict:
    """
    Scores all fields in master_case.json.
    Returns updated master_case with confidence_map added.
    """
    pages = master_case.get("pages", [])
    field_confidences = {}

    # Build per-page confidence lookup
    page_conf_map = {p["page_num"]: p.get("confidence", 0.7) for p in pages}

    # Score financial fields (high importance)
    financial = master_case.get("financial", {})
    for field, value in financial.items():
        page_conf = _find_field_page_confidence(field, pages, page_conf_map)
        field_confidences[f"financial.{field}"] = compute_field_confidence(
            str(value), field, page_conf
        )

    # Score party fields
    parties = master_case.get("parties", {})
    for party_key, party_data in parties.items():
        if isinstance(party_data, dict):
            for field, value in party_data.items():
                page_conf = _find_field_page_confidence(field, pages, page_conf_map)
                field_confidences[f"parties.{party_key}.{field}"] = compute_field_confidence(
                    str(value), field, page_conf
                )

    # Score all extracted fields per page so the UI can map them directly
    def _score_recursive(data, prefix, page_conf):
        if isinstance(data, dict):
            for k, v in data.items():
                _score_recursive(v, f"{prefix}.{k}" if prefix else k, page_conf)
        elif isinstance(data, list):
            for i, v in enumerate(data):
                _score_recursive(v, f"{prefix}[{i}]", page_conf)
        else:
            # It's a leaf node/primitive, compute its confidence
            field_name = prefix.split('.')[-1] if '.' in prefix else prefix
            field_name = re.sub(r'\[\d+\]$', '', field_name) # Remove array index for field name
            field_confidences[prefix] = compute_field_confidence(
                str(data), field_name, page_conf
            )

    for idx, page in enumerate(pages):
        fields = page.get("extracted_fields", {})
        page_conf = page.get("confidence", 0.7)
        _score_recursive(fields, f"pages[{idx}].extracted_fields", page_conf)

    # Overall case confidence
    if field_confidences:
        scores = [v["score"] for v in field_confidences.values()]
        overall = round(sum(scores) / len(scores), 3)
    else:
        overall = 0.5

    master_case["confidence_map"] = field_confidences
    master_case["overall_confidence"] = overall
    master_case["confidence_status"] = _get_status(overall)[0]

    low_conf_fields = [k for k, v in field_confidences.items() if v["score"] < HUMAN_REVIEW]
    master_case["review_required_fields"] = low_conf_fields

    logger.info(f"Case confidence: {overall} | Fields needing review: {len(low_conf_fields)}")
    return master_case


def get_field_color(score: float) -> str:
    """Returns CSS color class for UI highlighting."""
    if score >= AUTO_APPROVE:
        return "confidence-green"
    elif score >= HUMAN_REVIEW:
        return "confidence-yellow"
    else:
        return "confidence-red"


def _get_status(score: float) -> tuple:
    if score >= AUTO_APPROVE:
        return "auto_approved", "green"
    elif score >= HUMAN_REVIEW:
        return "needs_review", "yellow"
    else:
        return "must_correct", "red"


def _validate_field_format(field_name: str, value: str) -> bool:
    """Returns True if value matches expected format for the field."""
    if not value:
        return False
    value = str(value).strip()
    patterns = {
        "loan_number":     r"^\d{10,20}$",
        "pan":             r"^[A-Z]{5}\d{4}[A-Z]$",
        "phone":           r"^\d{10}$",
        "email":           r"^[\w\.-]+@[\w\.-]+\.\w+$",
        "pincode":         r"^\d{6}$",
        "outstanding_amount": r"^\d+(\.\d{1,2})?$",
        "interest_rate":   r"^\d+(\.\d+)?%?$",
        "notice_date":     r"\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}",
    }
    pattern = patterns.get(field_name)
    if pattern:
        return bool(re.search(pattern, value))
    return len(value) > 2  # Any non-trivial value is a weak pass


def _find_field_page_confidence(field_name: str, pages: list, page_conf_map: dict) -> float:
    """Find which page a field was extracted from and return its confidence."""
    for page in pages:
        fields = page.get("extracted_fields", {})
        if field_name in fields:
            return page_conf_map.get(page["page_num"], 0.7)
    return 0.7  # Default if field source page unknown
