import json
import google.generativeai as genai
from google.api_core.exceptions import PermissionDenied, GoogleAPICallError
import os
from dotenv import load_dotenv
from google.cloud import firestore
import logging
import hashlib
import time
import re

# Load environment variables
load_dotenv()
API_KEY = os.getenv("GOOGLE_API_KEY")

if not API_KEY:
    raise ValueError("GOOGLE_API_KEY not set. Cannot initialize Gemini API.")

genai.configure(api_key=API_KEY)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Simple in-memory cache for API responses (reduces API costs during testing)
# In production, consider using Redis or another distributed cache
_response_cache = {}

def serialize_firestore_data(data: dict) -> dict:
    """Convert Firestore data to JSON serializable format."""
    if not data:
        return {}
        
    processed_data = {}
    for key, value in data.items():
        if hasattr(value, '__class__') and (
            value.__class__.__name__ == 'ServerTimestamp' or 
            isinstance(value, firestore.SERVER_TIMESTAMP.__class__)
        ):
            processed_data[key] = str(time.time())
        elif isinstance(value, firestore.DocumentReference):
            processed_data[key] = str(value.path)
        elif isinstance(value, dict):
            processed_data[key] = serialize_firestore_data(value)
        else:
            processed_data[key] = value
    return processed_data

def create_cache_key(healthcare_data: dict, ingredients: list) -> str:
    """Create a cache key based on input data."""
    combined = json.dumps({
        "health": healthcare_data,
        "ingredients": ingredients
    }, sort_keys=True)
    return hashlib.md5(combined.encode()).hexdigest()

# def calculate_risk_scale(analysis_text: str) -> float:
#     """
#     Extract the risk scale from the analysis text.
    
#     Args:
#         analysis_text (str): Detailed analysis from Gemini.
    
#     Returns:
#         float: Risk score between 0 and 10, or 5 if extraction fails.
#     """
#     try:
#         # Look for a line containing "Risk Scale:" and extract the number
#         for line in analysis_text.splitlines():
#             if "Risk Scale:" in line:
#                 # Extract numeric portion, handling extra dots or spaces
#                 risk_value_str = line.split("Risk Scale:")[-1].strip()
                
#                 # Remove any extra dots or non-numeric characters except first dot
#                 risk_value_str = risk_value_str.replace('..', '.')
#                 risk_value_str = ''.join(char for char in risk_value_str if char.isdigit() or char == '.')
                
#                 # Truncate to first dot if multiple exist
#                 if risk_value_str.count('.') > 1:
#                     risk_value_str = risk_value_str.split('.', 1)[0] + '.' + risk_value_str.split('.', 1)[1]
                
#                 # Convert to float and validate
#                 risk_value = float(risk_value_str)
#                 return min(max(0, risk_value), 10)  # Ensure the value is within 0-10
        
#         logger.warning("Risk Scale not found in analysis text")
#         return 5  # Default neutral risk if not found
#     except ValueError as e:
#         logger.error(f"Error extracting risk scale: {e}. Problematic value: {risk_value_str}")
#         return 5  # Neutral risk if conversion fails
#     except Exception as e:
#         logger.error(f"Unexpected error extracting risk scale: {e}")
#         return 5  # Neutral risk if any other error occurs
# import re

import re


def calculate_risk_scale(analysis_text: str) -> float:
    """
    Extracts the risk scale from the analysis text with robust handling.
    
    Args:
        analysis_text (str): Detailed analysis text.
    
    Returns:
        float: Risk scale between 0 and 10, or 5 if extraction fails.
    """
    try:
        # Multiple pattern matching strategies
        risk_patterns = [
            # Primary pattern
            r"Risk Scale:\s*([\d\.]+)",
            
            # Alternative patterns
            r"\*\*Risk Scale:\*\*\s*([\d\.]+)",
            r"Risk\s*Scale[:\s]*([\d\.]+)",
            r"Risk\s*Level[:\s]*([\d\.]+)",
            
            # Fallback patterns
            r"\b([\d\.]+)\s*(?:on\s*(?:the\s*)?risk\s*scale)\b",
            r"\b(?:risk\s*of)\s*([\d\.]+)\b"
        ]
        
        # Try each pattern
        for pattern in risk_patterns:
            match = re.search(pattern, analysis_text, re.IGNORECASE)
            if match:
                risk_value_str = match.group(1)
                
                # Aggressive cleaning
                risk_value_str = re.sub(r"[^0-9.]", "", risk_value_str)
                
                # Handle multiple decimal points
                if risk_value_str.count('.') > 1:
                    # Keep only the first decimal point
                    parts = risk_value_str.split('.')
                    risk_value_str = f"{parts[0]}.{''.join(parts[1:]).replace('.', '')}"
                
                # Convert to float
                try:
                    risk_value = float(risk_value_str)
                    # Ensure value is within 0-10 range
                    return min(max(0, risk_value), 10)
                except ValueError:
                    # If conversion fails, continue to next pattern
                    continue
        
        # Logging for debugging if no pattern matches
        logging.warning(f"Risk Scale not found. First 200 chars: {analysis_text[:200]}")
        return 5  # Default risk score
    
    except Exception as e:
        # Comprehensive error logging
        logging.error(f"Unexpected error extracting risk scale: {e}")
        logging.error(f"Full analysis text: {analysis_text}")
        return 5  # Return default if anything goes wrong

# Test cases to verify robustness
# def test_risk_scale_extraction():
#     test_cases = [
#         "Risk Scale: 7.5",
#         "**Risk Scale:** 8..",
#         "The risk is 6 on the risk scale",
#         "Risk Level: 4.3",
#         "A risk of 9 was identified",
#         "Risk Scale near 7.2 indicates high potential",
#         "The analysis shows a risk level of 5.6",
#         "No clear risk scale present"
#     ]
    
#     for case in test_cases:
#         risk = calculate_risk_scale(case)
#         print(f"Input: {case}")
#         print(f"Extracted Risk Scale: {risk}\n")

# Uncomment to run tests
# test_risk_scale_extraction()

def analyze(healthcare_data: dict, ingredients: list, use_cache: bool = True, cache_ttl: int = 3600) -> tuple:
    """Analyze product safety based on user's healthcare data and ingredients.
    
    Args:
        healthcare_data (dict): User's healthcare data.
        ingredients (list): List of ingredients to analyze.
        use_cache (bool): Whether to use caching (default: True).
        cache_ttl (int): Cache time-to-live in seconds (default: 1 hour).
        
    Returns:
        tuple: Analysis results as formatted text and risk scale.
    """
    # Create cache key if caching is enabled
    cache_key = create_cache_key(healthcare_data, ingredients) if use_cache else None
    
    # Try to get from cache first
    if use_cache and cache_key in _response_cache:
        cache_entry = _response_cache[cache_key]
        if time.time() - cache_entry["timestamp"] < cache_ttl:
            logger.info(f"Using cached analysis result for key {cache_key[:8]}...")
            return cache_entry["result"], cache_entry["scale"]
    
    try:
        # Convert Firestore timestamps and references to JSON-serializable format
        serialized_data = serialize_firestore_data(healthcare_data)
        
        # Log input data for debugging (redact in production)
        logger.info(f"Processing analysis for {len(ingredients)} ingredients")
        
        # Create prompt for the AI model
        prompt = (
            f'''You are an advanced dietician who analyzes healthcare data and ingredients. Provide a structured report as follows:
            Summary: Concise description of the patient's health and findings.
            Recommendations: Dietary suggestions tailored to the patient's health.
            Ingredients Categorization: Bad, Normal, and Good categories.
            Risk Scale: A number from 0 to 10 indicating overall risk.
            Detailed Overview: Comprehensive assessment of the patient's needs.
            Suitability: Conclude whether the product is suitable.
            
            Include "Risk Scale:" followed by a number (0-10) in the response.
            
            **Patient Data:**
            {json.dumps(serialized_data, indent=2)}
            
            **Ingredients:**
            {', '.join(ingredients)}
            
            Ensure the response is concise, accurate, and tailored to the patient's health conditions.
            '''
        )

        # Select the appropriate model
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        # Implement exponential backoff for API calls
        max_retries = 3
        for attempt in range(max_retries):
            try:
                logger.info(f"Calling Gemini API (attempt {attempt+1}/{max_retries})...")
                result = model.generate_content([prompt])
                
                if result and hasattr(result, 'candidates') and result.candidates and result.candidates[0].content and result.candidates[0].content.parts:
                    response_text = result.candidates[0].content.parts[0].text
                    risk_scale = calculate_risk_scale(response_text)
                    
                    if use_cache and cache_key:
                        _response_cache[cache_key] = {
                            "result": response_text,
                            "scale": risk_scale,
                            "timestamp": time.time()
                        }
                    
                    return response_text, risk_scale
                else:
                    logger.warning("Received empty response from Gemini API")
                    
            except (PermissionDenied, GoogleAPICallError) as e:
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) + 1  # Exponential backoff with jitter
                    logger.warning(f"API error: {e}. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"API error after {max_retries} attempts: {e}")
                    raise
        
        return "Unable to generate analysis after multiple attempts. Please try again later.", 5
    
    except Exception as e:
        logger.exception(f"Unexpected error in analysis: {e}")
        return f"Error in generating analysis: {str(e)}", 5
