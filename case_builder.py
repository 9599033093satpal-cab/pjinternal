"""
Aether OCR — Master Case JSON Builder
=======================================
Aggregates all page-level OCR + classification results
into a single master_case.json — the Single Source of Truth.

Also handles cross-page field validation
(same loan number must appear consistently across pages).
"""

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

from document_classifier import TYPE_FIELD_MAP
from confidence_engine import compute_page_confidence, score_master_case

load_dotenv()
logger = logging.getLogger(__name__)


# Document-type-aware extraction prompts
EXTRACTION_PROMPTS = {
    "sarfaesi_notice": """Extract from this SARFAESI notice. Return ONLY valid JSON with these exact keys:
{
  "borrower_name": "", "borrower_address": "", "co_borrower_name": "",
  "loan_number": "", "outstanding_principal": "", "outstanding_interest": "",
  "total_demand_amount": "", "notice_date": "", "response_deadline": "",
  "bank_name": "", "bank_branch": "", "authorized_officer": "",
  "property_description": "", "account_type": ""
}""",

    "loan_agreement": """Extract from this loan agreement. Return ONLY valid JSON:
{
  "borrower_name": "", "co_borrower_name": "", "guarantor_name": "",
  "loan_amount": "", "disbursement_date": "", "interest_rate": "",
  "tenure_months": "", "emi_amount": "", "loan_type": "",
  "collateral_description": "", "bank_name": "", "branch_name": ""
}""",

    "property_deed": """Extract from this property deed. Return ONLY valid JSON:
{
  "owner_name": "", "previous_owner": "", "survey_number": "",
  "plot_number": "", "total_area": "", "area_unit": "",
  "property_address": "", "village": "", "taluka": "", "district": "",
  "state": "", "registration_date": "", "registration_number": "",
  "sub_registrar_office": "", "consideration_amount": ""
}""",

    "affidavit": """Extract from this affidavit. Return ONLY valid JSON:
{
  "deponent_name": "", "deponent_address": "", "court_name": "",
  "case_number": "", "date": "", "subject_matter": "",
  "key_statements": [], "notary_name": "", "notary_date": ""
}""",

    "kyc_document": """Extract from this KYC document. Return ONLY valid JSON:
{
  "full_name": "", "dob": "", "gender": "", "address": "",
  "city": "", "state": "", "pincode": "", "phone": "", "email": "",
  "id_type": "", "id_number": "", "photo_present": false
}""",

    "possession_notice": """Extract from this possession notice. Return ONLY valid JSON:
{
  "borrower_name": "", "loan_number": "", "bank_name": "",
  "property_address": "", "possession_date": "", "authorized_officer": "",
  "outstanding_amount": "", "notice_date": ""
}""",

    "court_order": """Extract from this court order. Return ONLY valid JSON:
{
  "case_number": "", "court_name": "", "judge_name": "",
  "petitioner": "", "respondent": "", "order_date": "",
  "next_hearing_date": "", "key_directions": [], "case_type": ""
}""",

    "other": """Extract key information from this document. Return ONLY valid JSON:
{"content_summary": "", "key_entities": [], "dates_mentioned": [], "amounts_mentioned": []}""",
}


class MasterCaseBuilder:
    def __init__(self):
        api_key = os.environ.get("OPENAI_API_KEY")
        self.client = OpenAI(api_key=api_key) if api_key else None
        self.model = "gpt-4o"  # Full model for extraction accuracy

    def extract_fields(self, text: str, doc_type: str, page_num: int) -> dict:
        """Extract structured fields from page text using type-aware prompt."""
        if not self.client or not text.strip():
            return {}

        prompt_template = EXTRACTION_PROMPTS.get(doc_type, EXTRACTION_PROMPTS["other"])

        prompt = f"""{prompt_template}

CRITICAL RULES:
1. Only extract values that ACTUALLY APPEAR in the text.
2. If a field is not found, leave it as empty string "".
3. Do NOT hallucinate or guess values.
4. Return ONLY raw JSON, no markdown, no explanation.

DOCUMENT TEXT (Page {page_num}):
{text[:3000]}

JSON:"""

        for attempt in range(2):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "You are a precise legal document data extraction engine. Output only valid JSON. Never hallucinate values."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.0,
                    max_tokens=800,
                )
                content = re.sub(r"```json|```", "", resp.choices[0].message.content).strip()
                return json.loads(content)
            except Exception as e:
                logger.warning(f"Extraction attempt {attempt+1} failed page {page_num}: {e}")

        return {}

    def build(self, job_id: str, filename: str, pages: list, output_dir: str) -> dict:
        """
        Build complete master_case.json from all processed pages.
        pages: list of {page_num, text, engine, confidence, quality_score, is_blank, classification}
        """
        logger.info(f"Building master_case.json for job {job_id} ({len(pages)} pages)")

        master = {
            "case_id": job_id,
            "filename": filename,
            "created_at": datetime.now().isoformat(),
            "document_bundle": {
                "total_pages": len(pages),
                "blank_pages": sum(1 for p in pages if p.get("is_blank")),
                "processed_pages": sum(1 for p in pages if not p.get("is_blank")),
                "primary_type": "unknown",
                "type_distribution": {},
            },
            "parties": {
                "borrower": {"name": "", "address": "", "pan": "", "phone": ""},
                "co_borrower": {"name": ""},
                "lender": {"bank_name": "", "branch": "", "officer": ""},
                "guarantor": {"name": ""},
            },
            "financial": {
                "loan_number": "",
                "loan_amount": "",
                "outstanding_principal": "",
                "outstanding_interest": "",
                "total_demand": "",
                "interest_rate": "",
                "tenure_months": "",
                "emi_amount": "",
                "overdue_since": "",
            },
            "property": {
                "survey_number": "",
                "area": "",
                "area_unit": "",
                "address": "",
                "district": "",
                "state": "",
            },
            "legal_status": {
                "notice_issued": False,
                "notice_date": "",
                "response_deadline": "",
                "possession_status": "unknown",
                "court_case_number": "",
            },
            "pages": [],
            "page_metadata": {}, # Maps page number (str) to diagnostic info
            "audit": {
                "human_corrections": 0,
                "accuracy_score": None,
                "verified_by": None,
                "verified_at": None,
                "trail": [],
            },
            "exports": {
                "txt_path": "",
                "json_path": "",
                "semantic_json": "",
                "excel_path": "",
                "draft_docx": "",
                "verified_json": "",
            },
        }

        # Track field sources for cross-validation
        field_sources = {}

        for page in pages:
            page_num = page.get("page_num", 0)
            is_blank = page.get("is_blank", False)
            doc_type = page.get("classification", {}).get("type", "other")

            page_confidence = compute_page_confidence(page)

            page_entry = {
                "page_num": page_num,
                "doc_type": doc_type,
                "is_blank": is_blank,
                "ocr_engine": page.get("engine", "unknown"),
                "quality_score": page.get("quality_score", 0.0),
                "confidence": page_confidence,
                "extracted_fields": {},
                "text": page.get("text", "")
            }

            if not is_blank and page.get("text", "").strip():
                # Extract fields for this page
                extracted = self.extract_fields(page["text"], doc_type, page_num)
                page_entry["extracted_fields"] = extracted

                # Merge into master case (first non-empty value wins, unless cross-validated)
                self._merge_fields(master, extracted, doc_type, page_num, field_sources)

            master["pages"].append(page_entry)
            master["page_metadata"][str(page_num)] = {
                "engine": page_entry["ocr_engine"],
                "quality": page_entry["quality_score"],
                "confidence": page_entry["confidence"],
                "doc_type": doc_type
            }

        # Cross-validate: flag inconsistencies
        master = self._cross_validate(master, field_sources)

        # Score all fields
        master = score_master_case(master)

        # Determine dominant doc type
        type_dist = {}
        for p in master["pages"]:
            t = p["doc_type"]
            if t != "blank_page":
                type_dist[t] = type_dist.get(t, 0) + 1
        master["document_bundle"]["type_distribution"] = type_dist
        if type_dist:
            master["document_bundle"]["primary_type"] = max(type_dist, key=type_dist.get)

        # Legal status flags
        if master["financial"]["loan_number"]:
            master["legal_status"]["notice_issued"] = True

        # Save master_case.json
        output_path = Path(output_dir) / "master_case.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(master, f, indent=2, ensure_ascii=False)

        master["exports"]["json_path"] = str(output_path)
        logger.info(f"master_case.json saved: {output_path}")
        return master

    def _merge_fields(self, master: dict, extracted: dict, doc_type: str,
                      page_num: int, field_sources: dict):
        """Merge extracted fields into master case structure."""
        mappings = {
            # Financial
            "loan_number":           ("financial", "loan_number"),
            "loan_amount":           ("financial", "loan_amount"),
            "outstanding_principal": ("financial", "outstanding_principal"),
            "outstanding_interest":  ("financial", "outstanding_interest"),
            "total_demand_amount":   ("financial", "total_demand"),
            "interest_rate":         ("financial", "interest_rate"),
            "tenure_months":         ("financial", "tenure_months"),
            "emi_amount":            ("financial", "emi_amount"),
            # Parties
            "borrower_name":         ("parties", "borrower", "name"),
            "borrower_address":      ("parties", "borrower", "address"),
            "co_borrower_name":      ("parties", "co_borrower", "name"),
            "bank_name":             ("parties", "lender", "bank_name"),
            "bank_branch":           ("parties", "lender", "branch"),
            "authorized_officer":    ("parties", "lender", "officer"),
            "guarantor_name":        ("parties", "guarantor", "name"),
            # Property
            "survey_number":         ("property", "survey_number"),
            "total_area":            ("property", "area"),
            "area_unit":             ("property", "area_unit"),
            "property_address":      ("property", "address"),
            "district":              ("property", "district"),
            "state":                 ("property", "state"),
            # Legal
            "notice_date":           ("legal_status", "notice_date"),
            "response_deadline":     ("legal_status", "response_deadline"),
            "case_number":           ("legal_status", "court_case_number"),
        }

        for ext_key, master_path in mappings.items():
            value = extracted.get(ext_key, "")
            if not value or str(value).strip() in ["", "null", "N/A"]:
                continue

            # Navigate to the right place in master
            if len(master_path) == 2:
                section, field = master_path
                target = master[section]
                field_name = field
            elif len(master_path) == 3:
                section, sub, field = master_path
                target = master[section][sub]
                field_name = field
            
            key = ".".join(master_path)
            val_str = str(value).strip()
            
            # Track variant for contradiction detection
            if key not in field_sources: field_sources[key] = {}
            if val_str not in field_sources[key]: field_sources[key][val_str] = []
            field_sources[key][val_str].append(page_num)

            # First value found becomes the default in master
            if not target.get(field_name):
                target[field_name] = val_str

    def _cross_validate(self, master: dict, field_sources: dict) -> dict:
        """Flag fields that appear inconsistently across pages and find missing data."""
        inconsistencies = []
        conflicts = {} # field_key -> list of different values found
        
        # 1. Detect Conflicts (Contradiction Detection)
        # field_sources structure: { "financial.loan_number": { "val1": [pg1, pg2], "val2": [pg10] } }
        for field_key, variants in field_sources.items():
            if len(variants) > 1:
                # We have a mismatch!
                conflict_desc = f"Mismatch found for {field_key}: " + ", ".join([f"'{v}' (Pgs: {', '.join(map(str, pgs))})" for v, pgs in variants.items()])
                inconsistencies.append({
                    "field": field_key,
                    "type": "contradiction",
                    "severity": "high",
                    "message": conflict_desc,
                    "variants": variants
                })
                conflicts[field_key] = variants
                logger.warning(f"  [CONTRADICTION] {conflict_desc}")

        # 2. Detect Missing Critical Fields
        # Based on primary document type
        doc_type = master["document_bundle"]["primary_type"]
        expected_fields = TYPE_FIELD_MAP.get(doc_type, [])
        missing = []
        
        for field in expected_fields:
            # Flatten master check
            path = field.split('.')
            curr = master
            found = True
            for part in path:
                if isinstance(curr, dict) and part in curr:
                    curr = curr[part]
                else:
                    found = False; break
            
            if not found or not str(curr).strip():
                missing.append(field)
                inconsistencies.append({
                    "field": field,
                    "type": "missing",
                    "severity": "medium",
                    "message": f"Critical field '{field}' was not found in the {doc_type} bundle."
                })

        master["intelligence_report"] = {
            "has_conflicts": len(conflicts) > 0,
            "conflicts": conflicts,
            "missing_fields": missing,
            "anomalies": inconsistencies,
            "validation_score": self._calculate_val_score(master, inconsistencies)
        }
        return master

    def _calculate_val_score(self, master, anomalies):
        """Calculate a 0-100 score for the entire case's data integrity."""
        total_pages = master["document_bundle"]["processed_pages"]
        if total_pages == 0: return 0
        
        penalty = 0
        for a in anomalies:
            if a["type"] == "contradiction": penalty += 15
            if a["type"] == "missing": penalty += 5
        
        score = 100 - penalty
        return max(0, min(100, score))

    def _clean_ocr_text(self, text: str) -> str:
        """Filter out OCR garbage (unreadable blocks, noisy symbols)."""
        if not text: return ""
        # Remove lines that are mostly garbage (low vowel density or too many special chars)
        lines = text.split('\n')
        clean_lines = []
        for line in lines:
            if len(line.strip()) < 3: continue
            # Garbage heuristic: ratio of alphanumeric to symbols
            alnum = sum(1 for c in line if c.isalnum() or c.isspace())
            ratio = alnum / len(line)
            if ratio < 0.4: continue # Skip if >60% is symbols
            clean_lines.append(line)
        return "\n".join(clean_lines)
