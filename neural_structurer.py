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
        # Load .env using absolute path to avoid CWD issues in threads
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
        schema_instruction = ""
        if schema_template:
            schema_instruction = f"""
        STRICT SCHEMA: Return a JSON object matching EXACTLY the following template keys:
        {json.dumps(schema_template, indent=2)}
        """

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

    def _process_with_openai(self, raw_text: str, schema_instruction: str) -> dict:
        """Optimized OpenAI logic for massive documents"""
        chunk_size = 100000
        chunks = [raw_text[i:i + chunk_size] for i in range(0, len(raw_text), chunk_size)]
        
        # Intelligently limit chunks to prevent massive API overhead and rate limits
        if len(chunks) > 3:
            logger.info(f"Massive text detected ({len(chunks)} chunks). Intelligently downsampling to 3 primary key sections (Start, Middle, End).")
            chunks = [chunks[0], chunks[len(chunks)//2], chunks[-1]]
            
        combined_ordered_array = []

        for chunk_idx, chunk_text in enumerate(chunks):
            prompt = self._build_prompt(chunk_text, chunk_idx, len(chunks), schema_instruction)
            
            for attempt in range(2): # Reduced retries for faster fallback
                try:
                    response = self.openai_client.chat.completions.create(
                        model=self.model_name,
                        messages=[
                            {"role": "system", "content": "You are a precise JSON extraction engine. Output only valid JSON arrays. Do not wrap in markdown blocks."},
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0.0
                    )
                    content = response.choices[0].message.content
                    data = self._parse_json(content)
                    if data and isinstance(data, list):
                        combined_ordered_array.extend(data)
                        break
                except Exception as e:
                    logger.error(f"OpenAI error on chunk {chunk_idx+1}: {e}")
                    if 'rate limit' in str(e).lower(): time.sleep(5)
            else:
                return None # Signal failure for fallback

        return self._reconstruct_dict(combined_ordered_array)

    def _process_with_gemini(self, raw_text: str, schema_instruction: str) -> dict:
        """Optimized Gemini processing logic for massive documents"""
        chunk_size = 100000 
        chunks = [raw_text[i:i + chunk_size] for i in range(0, len(raw_text), chunk_size)]
        
        # Intelligently limit chunks
        if len(chunks) > 3:
            logger.info(f"Massive text detected for Gemini ({len(chunks)} chunks). Downsampling to 3 primary key sections.")
            chunks = [chunks[0], chunks[len(chunks)//2], chunks[-1]]
            
        combined_ordered_array = []

        for chunk_idx, chunk_text in enumerate(chunks):
            prompt = self._build_prompt(chunk_text, chunk_idx, len(chunks), schema_instruction)
            
            try:
                response = self.gemini_model.generate_content(prompt)
                data = self._parse_json(response.text)
                if data and isinstance(data, list):
                    combined_ordered_array.extend(data)
                else:
                    logger.error(f"Gemini returned invalid data for chunk {chunk_idx+1}")
                    return None
            except Exception as e:
                logger.error(f"Gemini error on chunk {chunk_idx+1}: {e}")
                return None

        return self._reconstruct_dict(combined_ordered_array)

    def _build_prompt(self, chunk_text, chunk_idx, total_chunks, schema_instruction):
        return f"""
        Act as an expert Document Intelligence Agent. Transform the following OCR text chunk into structured JSON.

        ### ABSOLUTE ORDER RULE (HARD-CODED, NO EXCEPTIONS):
        1. Output the data as a JSON ARRAY of objects to strictly preserve section order.
        2. Each object has exactly two keys: "section" (string title) and "data" (the content).
        3. The order of objects in the array MUST match the TOP-TO-BOTTOM physical order of the text.
        4. NEVER reorder sections.

        ### REQUIRED OUTPUT FORMAT:
        [
          {{"section": "Heading 1", "data": {{"key": "..."}}}},
          {{"section": "Heading 2", "data": ["..."]}}
        ]

        {schema_instruction}

        ### OCR TEXT CHUNK ({chunk_idx + 1} of {total_chunks}):
        {chunk_text}

        ### YOUR RESPONSE (JSON array only, no markdown, no explanation):
        """

    def _parse_json(self, content):
        try:
            cleaned_text = re.sub(r'```json|```', '', content).strip()
            return json.loads(cleaned_text)
        except Exception as e:
            logger.error(f"JSON Parse Error: {e}")
            return None

    def _reconstruct_dict(self, combined_ordered_array):
        if not combined_ordered_array: return None
        ordered_dict = {}
        for item in combined_ordered_array:
            if isinstance(item, dict) and "section" in item and "data" in item:
                sec_name = item["section"]
                if sec_name in ordered_dict:
                    if isinstance(ordered_dict[sec_name], list):
                        if isinstance(item["data"], list): ordered_dict[sec_name].extend(item["data"])
                        else: ordered_dict[sec_name].append(item["data"])
                    else:
                        ordered_dict[sec_name] = [ordered_dict[sec_name], item["data"]]
                else:
                    ordered_dict[sec_name] = item["data"]
        return ordered_dict

    def _fallback_structure(self, text: str) -> dict:
        """Heuristic fallback extraction if LLM is unavailable."""
        # Basic regex patterns for "Real" look
        emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
        dates = re.findall(r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}', text)
        phones = re.findall(r'(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', text)
        
        return {
            "document_analysis": {
                "summary": text[:300] + "...",
                "potential_entities": {
                    "emails": list(set(emails[:5])),
                    "dates": list(set(dates[:5])),
                    "contacts": list(set(phones[:5]))
                }
            },
            "system_status": {
                "mode": "pattern_matching_fallback",
                "reason": "AI_KEY_ISSUE_OR_QUOTA_EXCEEDED",
                "full_text_preview": text[:1000]
            }
        }
