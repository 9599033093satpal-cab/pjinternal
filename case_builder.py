"""
Aether OCR — Master Case JSON Builder
=======================================
Aggregates all page-level OCR + classification results
into a single enterprise-grade structured document intelligence output.
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
from confidence_engine import compute_page_confidence, compute_field_confidence

load_dotenv()
logger = logging.getLogger(__name__)

class MasterCaseBuilder:
    def __init__(self):
        api_key = os.environ.get("OPENAI_API_KEY")
        self.client = OpenAI(api_key=api_key) if api_key else None
        self.model = "gpt-4o"  # Full model for extraction accuracy

    def _is_document_start_page(self, page_text: str) -> bool:
        """Detects if a page contains clear signals of being the first page of a new document."""
        if not page_text:
            return False
            
        text_lower = page_text.lower()
        
        # Stamp paper indicators are strong signs of a new document start
        stamp_patterns = [
            "non judicial",
            "गैर न्यायिक",
            "stamp duty",
            "satyamev jayate",
            "सत्यमेव जयते"
        ]
        has_stamp = any(pat in text_lower[:800] for pat in stamp_patterns)
        if has_stamp:
            return True
            
        # Specific title patterns that start a document (usually near the top)
        title_patterns = [
            "articles of agreement",
            "this deed of",
            "memorandum of understanding",
            "offer letter",
            "insurance policy schedule",
            "sarfaesi notice",
            "possession notice"
        ]
        has_title = any(pat in text_lower[:500] for pat in title_patterns)
        if has_title:
            return True
            
        # "agreement for leave and license" or similar starting lines
        if "agreement for" in text_lower[:500] and "between" in text_lower[:800]:
            return True
            
        return False

    def segment_pages(self, pages: list) -> list:
        """
        Smooth classifications and segment pages into continuous document chunks.
        """
        if not pages:
            return []
            
        # 1. Smooth page types to clean up single-page classification noise
        smoothed = []
        for i, p in enumerate(pages):
            p_type = p.get("classification", {}).get("type", "other")
            if not p_type:
                p_type = "other"
            smoothed.append(p_type)
            
        n = len(smoothed)
        # 3-page window smoothing for 'blank_page' or 'other'
        for i in range(n):
            if smoothed[i] in ["blank_page", "other"]:
                left = smoothed[i-1] if i > 0 else None
                right = smoothed[i+1] if i < n-1 else None
                if left and left == right and left not in ["blank_page", "other"]:
                    smoothed[i] = left
                    
        # 2. Form contiguous segments
        segments = []
        curr_segment = None
        
        for i, p in enumerate(pages):
            p_type = smoothed[i]
            p_num = p.get("page_num", i + 1)
            p_text = p.get("text", "")
            
            is_start = self._is_document_start_page(p_text)
            
            if curr_segment is None:
                curr_segment = {
                    "document_type": p_type,
                    "page_range": [p_num, p_num],
                    "pages": [p]
                }
            elif is_start or (p_type != curr_segment["document_type"] and p_type not in ["blank_page", "other"] and curr_segment["document_type"] not in ["blank_page", "other"]):
                # Start new segment if we detect a new document start, or if type mismatch
                segments.append(curr_segment)
                curr_segment = {
                    "document_type": p_type if p_type not in ["blank_page", "other"] else curr_segment["document_type"],
                    "page_range": [p_num, p_num],
                    "pages": [p]
                }
            else:
                # Absorb/extend
                if curr_segment["document_type"] in ["blank_page", "other"] and p_type not in ["blank_page", "other"]:
                    curr_segment["document_type"] = p_type
                curr_segment["page_range"][1] = p_num
                curr_segment["pages"].append(p)
                
        if curr_segment:
            segments.append(curr_segment)
            
        # 3. Post-process segments
        final_segments = []
        for seg in segments:
            is_all_blank = all(p.get("is_blank", False) for p in seg["pages"])
            if is_all_blank or seg["document_type"] == "blank_page":
                continue
                
            # Merge adjacent segments only if they have the same type AND the second segment does not start with a start page signal
            if final_segments and final_segments[-1]["document_type"] == seg["document_type"]:
                first_page_text = seg["pages"][0].get("text", "")
                if not self._is_document_start_page(first_page_text):
                    final_segments[-1]["page_range"][1] = seg["page_range"][1]
                    final_segments[-1]["pages"].extend(seg["pages"])
                    continue
            
            final_segments.append(seg)
                
        if not final_segments and segments:
            final_segments = [segments[0]]
            
        return final_segments

    def extract_segment_intelligence(self, segment_text: str, doc_type: str, page_range: list) -> dict:
        """
        Call OpenAI to extract entities and semantically grouped clauses for the document segment.
        """
        if not self.client or not segment_text.strip():
            return {
                "entities": {},
                "clauses": {},
                "semantic_confidence": 0.5
            }
            
        from document_classifier import TYPE_FIELD_MAP
        fields = TYPE_FIELD_MAP.get(doc_type, [])
        if not fields:
            fields = ["content_summary"]
            
        fields_str = "\n".join(f"   - {f}: Value or description of {f}" for f in fields)
        json_entities_format = ",\n".join(f'    "{f}": {{"value": "", "source_section": ""}}' for f in fields)

        prompt = f"""You are an enterprise document intelligence AI system.
Analyze the following document of type '{doc_type}' (covering pages {page_range[0]} to {page_range[1]}).

Extract the following information. If a field is not present or mentioned, leave it empty/null or empty array. Do not hallucinate or guess.

1. ENTITIES TO EXTRACT:
{fields_str}

2. CLAUSES OR SECTIONS TO EXTRACT:
   - For standard agreements, extract clauses under: repayment_terms, loan_conditions, agreement_clauses, insurance_terms, legal_notices.
   - For non-agreement documents (like Resumes, KYC, bank statements, etc.), extract the relevant key sections (e.g. work_experience, education details, etc.) under appropriate semantic category names.

CRITICAL INSTRUCTIONS:
- You must return ONLY a valid JSON object. No markdown, no triple backticks, no explanatory text.
- Clean up any raw OCR noise (like extra spaces, strange symbols, or stamp marks) from the extracted values.
- For each extracted field in entities, return a dictionary with two keys: "value" (the extracted string) and "source_section" (the section header/context where it was found in the text).
- For clauses/sections, return a dictionary where the keys are the semantic categories and values are arrays of strings (each representing a specific block/paragraph found).

Required JSON format:
{{
  "entities": {{
{json_entities_format}
  }},
  "clauses": {{
    // Grouped clauses/sections
  }},
  "semantic_confidence": 0.0
}}

DOCUMENT TEXT:
{segment_text[:15000]}

JSON RESPONSE:"""

        for attempt in range(2):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "You are a precise enterprise document intelligence engine. Output only valid JSON. Never hallucinate values."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.0,
                    max_tokens=2500,
                )
                content = re.sub(r"```json|```", "", resp.choices[0].message.content).strip()
                parsed = json.loads(content)
                if "entities" not in parsed:
                    parsed["entities"] = {}
                if "clauses" not in parsed:
                    parsed["clauses"] = {}
                if "semantic_confidence" not in parsed:
                    parsed["semantic_confidence"] = 0.85
                return parsed
            except Exception as e:
                logger.warning(f"Segment extraction attempt {attempt+1} failed: {e}")
                
        return {
            "entities": {},
            "clauses": {},
            "semantic_confidence": 0.5
        }

    def _validate_field_format(self, field_name: str, value: str) -> bool:
        """Returns True if value matches expected format for the field."""
        if not value:
            return False
        value = str(value).strip()
        patterns = {
            "loan_account_number":     r"^\d{10,20}$",
            "phone":           r"^\d{10}$",
            "email":           r"^[\w\.-]+@[\w\.-]+\.\w+$",
            "pincode":         r"^\d{6}$",
            "loan_amount":     r"^\d+(\.\d{1,2})?$",
            "emi":             r"^\d+(\.\d{1,2})?$",
            "interest_rate":   r"^\d+(\.\d+)?%?$",
            "agreement_dates":  r"\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}",
        }
        pattern = patterns.get(field_name)
        if pattern:
            return bool(re.search(pattern, value))
        return len(value) > 2  # Any non-trivial value is a weak pass

    def _consolidate_dynamic_master_case(self, processed_docs: list, primary_type: str) -> dict:
        """
        Consolidates dynamic entities from processed documents into a clean master_case structure.
        """
        # Collect all non-empty fields
        merged_entities = {}
        for doc in processed_docs:
            for k, v in doc["entities"].items():
                if v and str(v).strip() not in ["", "null", "N/A"]:
                    # Keep the first non-empty value or list them if different
                    if k not in merged_entities:
                        merged_entities[k] = v
                        
        if not merged_entities:
            return {}
            
        if not self.client:
            return merged_entities
            
        # Ask LLM to consolidate and clean the structure
        prompt = f"""You are an enterprise document intelligence consolidator.
We have extracted fields from a document bundle classified as '{primary_type}'.
Consolidate these fields into a clean, well-organized JSON object representing the 'master_case' for this document.

Raw Extracted Fields:
{json.dumps(merged_entities, indent=2)}

Rules:
- Organize related fields into logical sub-objects (e.g. for Resume: personal_details, education, experience, skills; for Offer Letter: candidate, compensation, job_details).
- Ensure key names are clean, lowercase, and descriptive.
- Return ONLY valid JSON, with no markdown, no triple backticks, and no explanations.
"""
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a precise document intelligence consolidator. Output only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=1500,
            )
            content = re.sub(r"```json|```", "", resp.choices[0].message.content).strip()
            return json.loads(content)
        except Exception as e:
            logger.error(f"Error consolidating dynamic master case: {e}")
            return merged_entities

    def build(self, job_id: str, filename: str, pages: list, output_dir: str) -> dict:
        """
        Build complete enterprise-grade structured JSON and master_case.json.
        """
        logger.info(f"Building Enterprise Master Case for job {job_id} ({len(pages)} pages)")
        
        # 1. Segment pages into contiguous logical documents
        segments = self.segment_pages(pages)
        
        processed_docs = []
        extracted_entities_by_type = {}
        
        for doc_idx, seg in enumerate(segments):
            doc_type = seg["document_type"]
            pg_range = seg["page_range"]
            
            # Clean and combine text of pages in segment
            combined_text_list = []
            for p in seg["pages"]:
                cleaned_page_text = self._clean_ocr_text(p.get("text", ""))
                combined_text_list.append(cleaned_page_text)
            combined_text = "\n".join(combined_text_list)
            
            # Extract intelligence using LLM
            extracted = self.extract_segment_intelligence(combined_text, doc_type, pg_range)
            
            # Clean up the output structure
            entities_raw = extracted.get("entities", {})
            clauses_raw = extracted.get("clauses", {})
            semantic_conf = float(extracted.get("semantic_confidence", 0.85))
            
            # Extract simple values for entities, keeping source section
            entities_simple = {}
            source_pages_map = {}
            
            for k, val_info in entities_raw.items():
                if isinstance(val_info, dict):
                    val = val_info.get("value", "")
                    sec = val_info.get("source_section", "")
                else:
                    val = val_info
                    sec = ""
                entities_simple[k] = val
                
                # Determine which page in segment contains the value
                val_str = str(val).strip()
                source_pg = pg_range[0]
                if val_str and val_str not in ["", "null", "N/A"]:
                    for p in seg["pages"]:
                        if val_str.lower() in p.get("text", "").lower():
                            source_pg = p.get("page_num", source_pg)
                            break
                source_pages_map[k] = {
                    "source_page": source_pg,
                    "source_section": sec
                }
                
            # Compute OCR confidence for segment
            seg_ocr_scores = [compute_page_confidence(p) for p in seg["pages"]]
            ocr_conf = round(sum(seg_ocr_scores) / len(seg_ocr_scores), 3) if seg_ocr_scores else 0.8
            
            # Compute Validation confidence for segment
            non_empty_entities = [v for v in entities_simple.values() if v and str(v).strip() not in ["", "null", "N/A"]]
            valid_count = 0
            for k, v in entities_simple.items():
                if v and str(v).strip() not in ["", "null", "N/A"]:
                    if self._validate_field_format(k, v):
                        valid_count += 1
            validation_conf = round(valid_count / len(non_empty_entities), 3) if non_empty_entities else 1.0
            
            processed_doc = {
                "document_type": doc_type,
                "page_range": pg_range,
                "entities": entities_simple,
                "clauses": clauses_raw,
                "confidence": {
                    "ocr_confidence": ocr_conf,
                    "semantic_confidence": semantic_conf,
                    "validation_confidence": validation_conf
                },
                "source_pages": list(range(pg_range[0], pg_range[1] + 1)),
                "source_pages_map": source_pages_map
            }
            processed_docs.append(processed_doc)
            
            if doc_type not in extracted_entities_by_type:
                extracted_entities_by_type[doc_type] = []
            extracted_entities_by_type[doc_type].append(entities_simple)
            
        # 2. Build master_case fields by merging segment extractions
        type_dist = {}
        for doc in processed_docs:
            t = doc["document_type"]
            if t != "blank_page":
                type_dist[t] = type_dist.get(t, 0) + 1
        primary_type = max(type_dist, key=type_dist.get) if type_dist else "other"

        is_standard_agreement = primary_type in [
            "loan_agreement", 
            "leave_license_agreement", 
            "sarfaesi_notice", 
            "insurance_policy", 
            "mortgage_deed", 
            "sale_deed",
            "property_deed"
        ]

        if is_standard_agreement:
            def get_global_entity(keys):
                for doc in processed_docs:
                    for k in keys:
                        val = doc["entities"].get(k)
                        if val and str(val).strip() not in ["", "null", "N/A"]:
                            return str(val).strip()
                return ""
                
            master_case_obj = {
                "borrower": {
                    "name": get_global_entity(["borrower", "licensor", "licensee"]),
                    "address": get_global_entity(["property_address"])
                },
                "loan": {
                    "loan_account_number": get_global_entity(["loan_account_number"]),
                    "loan_amount": get_global_entity(["loan_amount"]),
                    "interest_rate": get_global_entity(["interest_rate"]),
                    "emi": get_global_entity(["emi"])
                },
                "property": {
                    "property_address": get_global_entity(["property_address"])
                },
                "insurance": {
                    "policy_number": get_global_entity(["policy_number"])
                },
                "agreements": {
                    "agreement_dates": get_global_entity(["agreement_dates"])
                }
            }
        else:
            master_case_obj = self._consolidate_dynamic_master_case(processed_docs, primary_type)
        
        # 3. Detect contradictions
        anomalies = self._detect_contradictions(processed_docs)
        
        # Check for missing expected fields
        missing_fields = []
        from document_classifier import TYPE_FIELD_MAP
        for doc in processed_docs:
            doc_type = doc["document_type"]
            expected = TYPE_FIELD_MAP.get(doc_type, [])
            for field in expected:
                val = doc["entities"].get(field)
                if not val or str(val).strip() in ["", "null", "N/A"]:
                    missing_fields.append(f"{doc_type}.{field}")
                    anomalies.append({
                        "field": f"{doc_type}.{field}",
                        "type": "missing",
                        "severity": "medium",
                        "message": f"Critical field '{field}' was not found in the {doc_type} segment."
                    })
                    
        validation_score = self._calculate_val_score(anomalies)
        
        # 4. Construct backward-compatible pages array for visual dashboard
        pages_compat = []
        for p in pages:
            p_num = p.get("page_num", 1)
            p_is_blank = p.get("is_blank", False)
            
            matching_seg = None
            for doc in processed_docs:
                if p_num in doc["source_pages"]:
                    matching_seg = doc
                    break
                    
            if matching_seg:
                extracted_fields = {
                    "entities": matching_seg["entities"],
                    "clauses": matching_seg["clauses"]
                }
                doc_type = matching_seg["document_type"]
            else:
                extracted_fields = {}
                doc_type = p.get("classification", {}).get("type", "other")
                
            page_entry = {
                "page_num": p_num,
                "doc_type": doc_type,
                "is_blank": p_is_blank,
                "ocr_engine": p.get("engine", "unknown"),
                "quality_score": p.get("quality_score", 0.0),
                "confidence": compute_page_confidence(p),
                "extracted_fields": extracted_fields,
                "text": p.get("text", "")
            }
            pages_compat.append(page_entry)
            
        # Build confidence map
        confidence_map = {}
        if isinstance(master_case_obj, dict):
            for sec, val_obj in master_case_obj.items():
                if isinstance(val_obj, dict):
                    for f, val in val_obj.items():
                        confidence_map[f"{sec}.{f}"] = compute_field_confidence(
                            val, f, 0.85
                        )
                else:
                    confidence_map[sec] = compute_field_confidence(
                        val_obj, sec, 0.85
                    )
                
        overall_conf = round(sum(d["confidence"]["semantic_confidence"] for d in processed_docs) / len(processed_docs), 3) if processed_docs else 0.85
        
        # Assemble final output
        output_data = {
            "case_id": job_id,
            "documents": processed_docs,
            "master_case": master_case_obj,
            
            "filename": filename,
            "created_at": datetime.now().isoformat(),
            "document_bundle": {
                "total_pages": len(pages),
                "blank_pages": sum(1 for p in pages if p.get("is_blank")),
                "processed_pages": sum(1 for p in pages if not p.get("is_blank")),
                "primary_type": primary_type,
                "type_distribution": type_dist,
            },
            "pages": pages_compat,
            "intelligence_report": {
                "has_conflicts": any(a["type"] == "contradiction" for a in anomalies),
                "conflicts": {a["field"]: a["variants"] for a in anomalies if a["type"] == "contradiction"},
                "missing_fields": missing_fields,
                "anomalies": anomalies,
                "validation_score": validation_score
            },
            "confidence_map": confidence_map,
            "overall_confidence": overall_conf,
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
            }
        }
        
        # Save master_case.json
        output_path = Path(output_dir) / "master_case.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
            
        output_data["exports"]["json_path"] = str(output_path)
        logger.info(f"master_case.json saved: {output_path}")
        return output_data

    def _detect_contradictions(self, documents: list) -> list:
        """
        Detect mismatches in extracted fields across different documents in the bundle.
        """
        anomalies = []
        field_values = {
            "borrower_name": {},
            "loan_account_number": {},
            "loan_amount": {},
            "interest_rate": {},
            "emi": {},
            "property_address": {},
            "agreement_dates": {}
        }
        
        for idx, doc in enumerate(documents):
            doc_type = doc["document_type"]
            label = f"{doc_type} (Pgs {doc['page_range'][0]}-{doc['page_range'][1]})"
            entities = doc["entities"]
            
            val_map = {
                "borrower_name": entities.get("borrower") or entities.get("licensor") or entities.get("licensee"),
                "loan_account_number": entities.get("loan_account_number"),
                "loan_amount": entities.get("loan_amount"),
                "interest_rate": entities.get("interest_rate"),
                "emi": entities.get("emi"),
                "property_address": entities.get("property_address"),
                "agreement_dates": entities.get("agreement_dates")
            }
            
            for key, val in val_map.items():
                if val and str(val).strip() not in ["", "null", "N/A"]:
                    field_values[key][label] = str(val).strip()
                    
        for key, variants in field_values.items():
            if len(variants) > 1:
                unique_vals = set(variants.values())
                if len(unique_vals) > 1:
                    conflict_desc = f"Mismatch in {key.replace('_', ' ')}: " + ", ".join([f"'{v}' in {doc_lbl}" for doc_lbl, v in variants.items()])
                    anomalies.append({
                        "field": key,
                        "type": "contradiction",
                        "severity": "high",
                        "message": conflict_desc,
                        "variants": variants
                    })
                    logger.warning(f"  [CONTRADICTION] {conflict_desc}")
                    
        return anomalies

    def _calculate_val_score(self, anomalies: list) -> int:
        """Calculate a 0-100 score for data integrity based on anomalies."""
        penalty = 0
        for a in anomalies:
            if a["type"] == "contradiction":
                penalty += 15
            elif a["type"] == "missing":
                penalty += 5
        score = 100 - penalty
        return max(0, min(100, score))

    def _clean_ocr_text(self, text: str) -> str:
        """Filter out OCR garbage (unreadable blocks, noisy symbols, duplicates)."""
        if not text:
            return ""
        
        # Split by lines
        lines = text.split('\n')
        clean_lines = []
        seen_paragraphs = set()
        
        for line in lines:
            line_strip = line.strip()
            if not line_strip:
                clean_lines.append("")
                continue
                
            if len(line_strip) < 3:
                continue
                
            # Filter lines that are mostly symbols/noise (e.g. stamp noise, borders)
            alnum_count = sum(1 for c in line_strip if c.isalnum())
            if len(line_strip) > 0 and (alnum_count / len(line_strip)) < 0.45:
                # Less than 45% alphanumeric -> likely border or separator noise
                continue
                
            # Filter repetitive characters/borders (e.g. "----------" or "============")
            if re.match(r'^[-=_*#\s]{5,}$', line_strip):
                continue
                
            # Filter stamp noise patterns or OCR artifacts
            words = line_strip.split()
            valid_words = []
            for w in words:
                w_clean = re.sub(r'[^\w]', '', w)
                if not w_clean:
                    continue
                if w_clean.isdigit():
                    valid_words.append(w)
                    continue
                if len(w_clean) > 5:
                    vowels = sum(1 for c in w_clean.lower() if c in 'aeiouy')
                    if vowels == 0:
                        continue
                valid_words.append(w)
                
            if not valid_words:
                continue
                
            reconstructed_line = " ".join(valid_words)
            
            # Remove duplicated clauses / duplicate lines
            norm_line = re.sub(r'\s+', ' ', reconstructed_line.lower()).strip()
            if len(norm_line) > 30:
                if norm_line in seen_paragraphs:
                    continue
                seen_paragraphs.add(norm_line)
                
            clean_lines.append(reconstructed_line)
            
        return "\n".join(clean_lines)
