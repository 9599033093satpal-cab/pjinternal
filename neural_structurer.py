"""
[ignoring loop detection]
Aether OCR — Neural Structurer
===================================
Transforms raw OCR text into semantically structured JSON matching
the enterprise-grade target document intelligence schema.
"""

import json
import logging
import os
import re
import time
from dotenv import load_dotenv
from openai import OpenAI
import google.generativeai as genai

logger = logging.getLogger(__name__)

class NeuralStructurer:
    """
    Transforms raw OCR text into semantically structured JSON using LLM.
    """
    def __init__(self, api_key=None):
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        load_dotenv(dotenv_path=env_path)
        self.openai_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.gemini_key = os.environ.get("GEMINI_API_KEY")

        # Initialize OpenAI
        self.openai_client = None
        if self.openai_key:
            try:
                self.openai_client = OpenAI(api_key=self.openai_key, timeout=60.0)
                self.model_name = "gpt-4o-mini"
                logger.info(f"Neural Structurer: OpenAI initialized ({self.model_name}).")
            except Exception as e:
                logger.error(f"Failed to init OpenAI: {e}")

        # Initialize Gemini
        self.gemini_model = None
        if self.gemini_key:
            try:
                genai.configure(api_key=self.gemini_key)
                self.gemini_model = genai.GenerativeModel('gemini-1.5-flash')
                logger.info("Neural Structurer: Gemini initialized (gemini-1.5-flash).")
            except Exception as e:
                logger.error(f"Failed to init Gemini: {e}")

        if not self.openai_client and not self.gemini_model:
            logger.warning("No valid AI API keys (OpenAI/Gemini) found. Structuring will use heuristic fallback.")

    def process(self, raw_text: str, schema_template: dict = None) -> dict:
        """
        Processes raw text and returns structured enterprise-grade JSON.
        """
        # If schema template is provided, use it
        if schema_template:
            schema_instruction = f"""
            STRICT SCHEMA: Return a JSON object matching EXACTLY the following template keys:
            {json.dumps(schema_template, indent=2)}
            """
        else:
            schema_instruction = None

        # 1. Try OpenAI if available
        if self.openai_client:
            logger.info("Attempting structuring with OpenAI...")
            result = self._process_with_openai(raw_text, schema_instruction)
            if result:
                return result
            logger.warning("OpenAI structuring failed or returned empty. Trying Gemini fallback...")

        # 2. Try Gemini if available
        if self.gemini_model:
            logger.info("Attempting structuring with Gemini...")
            result = self._process_with_gemini(raw_text, schema_instruction)
            if result:
                return result
            logger.warning("Gemini structuring failed or returned empty.")

        # 3. Last Resort: Heuristic Fallback
        logger.error("All AI structuring methods failed. Using heuristic fallback.")
        return self._fallback_structure(raw_text)

    def _process_with_openai(self, raw_text: str, schema_instruction: str = None) -> dict:
        """Process text with OpenAI client."""
        prompt = self._build_prompt(raw_text, schema_instruction)
        
        for attempt in range(2):
            try:
                response = self.openai_client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": "You are a precise enterprise document intelligence AI system. Output only valid JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.0,
                    max_tokens=3000
                )
                content = response.choices[0].message.content
                data = self._parse_json(content)
                if data:
                    return data
            except Exception as e:
                logger.error(f"OpenAI structuring error: {e}")
                if 'rate limit' in str(e).lower():
                    time.sleep(5)
        return None

    def _process_with_gemini(self, raw_text: str, schema_instruction: str = None) -> dict:
        """Process text with Gemini client."""
        prompt = self._build_prompt(raw_text, schema_instruction)
        
        try:
            response = self.gemini_model.generate_content(prompt)
            data = self._parse_json(response.text)
            if data:
                return data
        except Exception as e:
            logger.error(f"Gemini structuring error: {e}")
        return None

    def _build_prompt(self, raw_text: str, schema_instruction: str = None) -> str:
        if schema_instruction:
            return f"""
            Act as an expert Document Intelligence Agent. Transform the following OCR text into structured JSON.
            {schema_instruction}

            OCR TEXT:
            {raw_text[:25000]}

            YOUR RESPONSE (JSON object only, no markdown, no explanation):
            """
            
        return f"""You are an enterprise document intelligence AI system.
Analyze the following document bundle and perform document segmentation, classification, and entity/clause extraction.

1. SEGMENTATION & CLASSIFICATION:
   Identify all logical sub-documents in the text (e.g. Leave and License Agreements, Loan Agreements, Offer Letters, Insurance Policies, Resumes/CVs, KYC documents, Schedules, Financial Clauses, and Court Orders).
   For each document, define its type and approximate page range or section within the text.

2. ENTITY EXTRACTION:
   - For standard financial/legal agreements (Loan, Lease, Mortgage, Insurance, etc.), extract: licensor, licensee, borrower, co_borrower, loan_account_number, property_address, emi, interest_rate, loan_amount, policy_number, agreement_dates.
   - For other document types (e.g. Resume, Offer Letter, KYC, Bank Statement, Court Order), dynamically extract the most relevant entities (e.g. candidate_name, skills, company_name, date of birth, case number, account holder, etc.).

3. SEMANTIC CLAUSE GROUPING:
   Group key clauses or sections (if applicable) into logical categories (e.g. repayment_terms, loan_conditions, agreement_clauses, insurance_terms, legal_notices, or work_experience, education for resumes).

4. MASTER CASE CONSOLIDATION:
   - For standard financial/legal agreements, consolidate into a global 'master_case' matching:
     {{
       "borrower": {{"name": "", "address": ""}},
       "loan": {{"loan_account_number": "", "loan_amount": "", "interest_rate": "", "emi": ""}},
       "property": {{"property_address": ""}},
       "insurance": {{"policy_number": ""}},
       "agreements": {{"agreement_dates": ""}}
     }}
   - For other document types (Resume, KYC, Offer Letter, etc.), dynamically construct the most logical structured JSON for the 'master_case' to represent the primary entities and metadata of the document.

Return ONLY a valid JSON object matching the target enterprise schema:
{{
  "documents": [
    {{
      "document_type": "...",
      "page_range": [1, 5],
      "entities": {{
        // Key-value pairs of extracted entities (either standard or dynamically determined)
      }},
      "clauses": {{
        // Grouped clauses/sections
      }},
      "confidence": {{
        "ocr_confidence": 0.95,
        "semantic_confidence": 0.9,
        "validation_confidence": 0.9
      }}
    }}
  ],
  "master_case": {{
     // The consolidated master case (either standard or dynamically structured for resumes/other types)
  }}
}}

TEXT BUNDLE:
{raw_text[:25000]}

JSON RESPONSE:"""

    def _parse_json(self, content):
        try:
            cleaned_text = re.sub(r'```json|```', '', content).strip()
            return json.loads(cleaned_text)
        except Exception as e:
            logger.error(f"JSON Parse Error: {e}")
            return None

    def _fallback_structure(self, text: str) -> dict:
        """Heuristic fallback extraction if LLM is unavailable."""
        emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
        dates = re.findall(r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}', text)
        
        return {
            "documents": [
                {
                    "document_type": "unknown",
                    "page_range": [1, 1],
                    "entities": {
                        "emails": list(set(emails[:5])),
                        "dates": list(set(dates[:5]))
                    },
                    "clauses": {},
                    "confidence": {
                        "ocr_confidence": 0.5,
                        "semantic_confidence": 0.5,
                        "validation_confidence": 0.5
                    }
                }
            ],
            "master_case": {
                "borrower": {"name": "", "address": ""},
                "loan": {"loan_account_number": "", "loan_amount": "", "interest_rate": "", "emi": ""},
                "property": {"property_address": ""},
                "insurance": {"policy_number": ""},
                "agreements": {"agreement_dates": ""}
            }
        }
