import google.generativeai as genai
import json
import logging
import os
import re
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

class DynamicFormMapper:
    """
    Intelligently maps structured JSON data into target form schemas using LLM.
    """
    def __init__(self, api_key=None):
        load_dotenv()
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        
        if self.api_key:
            try:
                genai.configure(api_key=self.api_key)
                # Using flash-latest for fast, intelligent mapping
                self.model = genai.GenerativeModel('gemini-flash-latest')
                logger.info("DynamicFormMapper initialized with Gemini SUCCESS.")
            except Exception as e:
                logger.error(f"Failed to init Gemini for FormMapper: {e}")
                self.model = None
        else:
            logger.warning("No Gemini API Key found for FormMapper.")
            self.model = None

    def map_data(self, source_data: dict, target_schema: dict) -> dict:
        if not self.model:
            raise Exception("FormMapper is not initialized properly. API Key missing.")

        prompt = f"""
        Act as an expert Data Integration Agent. Your task is to accurately map data from a source JSON object into a specific target JSON schema.
        
        CRITICAL INSTRUCTIONS:
        1. SCHEMA STRICTNESS: You MUST output a valid JSON object that exactly matches the keys and structure of the TARGET SCHEMA provided below. Do NOT add new keys, do NOT remove keys from the target schema.
        2. INTELLIGENT MAPPING: Analyze the SOURCE DATA and find the corresponding information for each field in the TARGET SCHEMA. 
           - For example, if the source has "dates": "2020 - 2022" and the target requires "start_year" and "end_year", you must extract and format them accordingly.
        3. NO HALLUCINATION: If a piece of information required by the target schema is absolutely NOT present in the source data, leave the value as an empty string "", null, or an empty array [] (depending on the target type).
        4. RAW JSON ONLY: Output ONLY raw, valid JSON. Do not wrap it in markdown block quotes like ```json. Do not include any explanations.

        SOURCE DATA (From OCR Document):
        {json.dumps(source_data, indent=2)}

        TARGET SCHEMA (To be Filled):
        {json.dumps(target_schema, indent=2)}
        
        MAPPED FINAL JSON:
        """
        
        try:
            response = self.model.generate_content(prompt)
            # Clean response (remove markdown blocks if LLM adds them)
            cleaned_text = re.sub(r'```json|```', '', response.text).strip()
            return json.loads(cleaned_text)
        except Exception as e:
            logger.error(f"Error during semantic form mapping: {e}")
            raise Exception(f"Mapping failed: {str(e)}")
