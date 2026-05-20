"""
Aether OCR — Document Classifier
===================================
Uses GPT-4o-mini to classify document type per page / per bundle.
Cheap, fast, accurate. ~$0.0001 per page.
"""

import json
import logging
import os
import re
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# All supported document types
DOCUMENT_TYPES = [
    "sarfaesi_notice",
    "loan_agreement",
    "property_deed",
    "affidavit",
    "kyc_document",
    "insurance_policy",
    "court_order",
    "bank_statement",
    "agreement_contract",
    "notice_letter",
    "possession_notice",
    "auction_notice",
    "mortgage_deed",
    "sale_deed",
    "power_of_attorney",
    "blank_page",
    "other",
]

# Type → key fields to extract (used to build extraction prompts later)
TYPE_FIELD_MAP = {
    "sarfaesi_notice": ["borrower_name", "loan_number", "outstanding_amount", "notice_date", "bank_name", "property_description"],
    "loan_agreement":  ["borrower_name", "co_borrower", "loan_amount", "interest_rate", "tenure", "emi_amount", "disbursement_date"],
    "property_deed":   ["owner_name", "survey_number", "area", "location", "registration_date", "consideration_amount"],
    "affidavit":       ["deponent_name", "court_name", "date", "subject_matter", "notary_name"],
    "kyc_document":    ["full_name", "dob", "address", "id_type", "id_number", "phone", "email"],
    "insurance_policy":["policy_number", "insured_name", "sum_assured", "premium", "nominee", "policy_period"],
    "court_order":     ["case_number", "court_name", "judge_name", "order_date", "parties", "directions"],
    "bank_statement":  ["account_number", "account_holder", "bank_name", "period", "opening_balance", "closing_balance"],
    "possession_notice":["borrower_name", "property_address", "possession_date", "authorized_officer"],
    "auction_notice":  ["property_description", "reserve_price", "auction_date", "contact_officer"],
    "mortgage_deed":   ["mortgagor", "mortgagee", "property", "loan_amount", "date"],
    "other":           ["content_summary"],
}


class DocumentClassifier:
    def __init__(self):
        api_key = os.environ.get("OPENAI_API_KEY")
        if api_key:
            self.client = OpenAI(api_key=api_key, timeout=60.0)
            self.model = "gpt-4o-mini"
            logger.info("DocumentClassifier ready (gpt-4o-mini)")
        else:
            self.client = None
            logger.warning("No OPENAI_API_KEY — classifier will use keyword fallback")

    def classify_page(self, text: str, page_num: int = 0) -> dict:
        """
        Classify a single page's text.
        Returns: {type, confidence, key_signals, fields_to_extract}
        """
        if not text or len(text.strip()) < 20:
            return self._blank_result()

        if not self.client:
            return self._keyword_fallback(text)

        try:
            prompt = f"""You are a legal document classification expert.
Classify the following document page text into ONE of these types:
{', '.join(DOCUMENT_TYPES)}

Rules:
- Return ONLY valid JSON, no markdown, no explanation.
- confidence: 0.0–1.0 float
- key_signals: up to 3 phrases that led to your decision

Required output:
{{"type": "...", "confidence": 0.0, "key_signals": ["..."]}}

TEXT (Page {page_num}):
{text[:2500]}

JSON:"""

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a precise document classification engine. Output only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=150,
            )

            content = re.sub(r"```json|```", "", response.choices[0].message.content).strip()
            result = json.loads(content)

            doc_type = result.get("type", "other")
            if doc_type not in DOCUMENT_TYPES:
                doc_type = "other"

            return {
                "type": doc_type,
                "confidence": float(result.get("confidence", 0.7)),
                "key_signals": result.get("key_signals", []),
                "fields_to_extract": TYPE_FIELD_MAP.get(doc_type, []),
            }

        except Exception as e:
            logger.error(f"Classification error page {page_num}: {e}")
            return self._keyword_fallback(text)

    def classify_bundle(self, pages: list) -> dict:
        """
        Classify the entire document bundle.
        Returns dominant doc type + page-level breakdown.
        """
        type_counts = {}
        page_classifications = []

        for page in pages:
            result = self.classify_page(page.get("text", ""), page.get("page_num", 0))
            page_classifications.append({**page, "classification": result})
            t = result["type"]
            if t != "blank_page":
                type_counts[t] = type_counts.get(t, 0) + 1

        dominant_type = max(type_counts, key=type_counts.get) if type_counts else "other"

        return {
            "dominant_type": dominant_type,
            "type_distribution": type_counts,
            "pages": page_classifications,
        }

    def _blank_result(self) -> dict:
        return {"type": "blank_page", "confidence": 1.0, "key_signals": ["no text"], "fields_to_extract": []}

    def _keyword_fallback(self, text: str) -> dict:
        """Simple keyword-based fallback when LLM unavailable."""
        text_lower = text.lower()
        rules = [
            ("sarfaesi", "sarfaesi_notice"),
            ("demand notice", "sarfaesi_notice"),
            ("loan agreement", "loan_agreement"),
            ("emi", "loan_agreement"),
            ("sale deed", "sale_deed"),
            ("affidavit", "affidavit"),
            ("deponent", "affidavit"),
            ("policy number", "insurance_policy"),
            ("aadhaar", "kyc_document"),
            ("pan card", "kyc_document"),
            ("auction", "auction_notice"),
            ("possession", "possession_notice"),
            ("court", "court_order"),
            ("survey", "property_deed"),
        ]
        for keyword, doc_type in rules:
            if keyword in text_lower:
                return {
                    "type": doc_type,
                    "confidence": 0.65,
                    "key_signals": [keyword],
                    "fields_to_extract": TYPE_FIELD_MAP.get(doc_type, []),
                }
        return {"type": "other", "confidence": 0.5, "key_signals": [], "fields_to_extract": []}
