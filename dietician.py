# import json
# import google.generativeai as genai
# from google.api_core.exceptions import PermissionDenied, GoogleAPICallError
# import os
# from dotenv import load_dotenv
# from google.cloud import firestore
# import logging
# import hashlib
# import time

# # Load environment variables
# load_dotenv()
# API_KEY = os.getenv("GOOGLE_API_KEY")

# if not API_KEY:
#     raise ValueError("GOOGLE_API_KEY not set. Cannot initialize Gemini API.")

# genai.configure(api_key=API_KEY)

# # Configure logging
# logger = logging.getLogger(__name__)

# # Simple in-memory cache for API responses (reduces API costs during testing)
# # In production, consider using Redis or another distributed cache
# _response_cache = {}

# def serialize_firestore_data(data):
#     """Convert Firestore data to JSON serializable format."""
#     if not data:
#         return {}
        
#     processed_data = {}
#     for key, value in data.items():
#         if hasattr(value, '__class__') and (
#             value.__class__.__name__ == 'ServerTimestamp' or 
#             isinstance(value, firestore.SERVER_TIMESTAMP.__class__)
#         ):
#             processed_data[key] = str(time.time())
#         elif isinstance(value, firestore.DocumentReference):
#             processed_data[key] = str(value.path)
#         elif isinstance(value, dict):
#             processed_data[key] = serialize_firestore_data(value)
#         else:
#             processed_data[key] = value
#     return processed_data

# def create_cache_key(healthcare_data, ingredients):
#     """Create a cache key based on input data."""
#     combined = json.dumps({
#         "health": healthcare_data,
#         "ingredients": ingredients
#     }, sort_keys=True)
#     return hashlib.md5(combined.encode()).hexdigest()

# def analyze(healthcare_data, ingredients, use_cache=True, cache_ttl=3600):
#     """Analyze product safety based on user's healthcare data and ingredients.
    
#     Args:
#         healthcare_data (dict): User's healthcare data
#         ingredients (list): List of ingredients to analyze
#         use_cache (bool): Whether to use caching (default: True)
#         cache_ttl (int): Cache time-to-live in seconds (default: 1 hour)
        
#     Returns:
#         str: Analysis results as formatted text
#     """
#     # Create cache key if caching is enabled
#     cache_key = create_cache_key(healthcare_data, ingredients) if use_cache else None
    
#     # Try to get from cache first
#     if use_cache and cache_key in _response_cache:
#         cache_entry = _response_cache[cache_key]
#         if time.time() - cache_entry["timestamp"] < cache_ttl:
#             logger.info(f"Using cached analysis result for key {cache_key[:8]}...")
#             return cache_entry["result"]
    
#     try:
#         # Convert Firestore timestamps and references to JSON-serializable format
#         serialized_data = serialize_firestore_data(healthcare_data)
        
#         # Log input data for debugging (redact in production)
#         logger.info(f"Processing analysis for {len(ingredients)} ingredients")
        
#         # Create prompt for the AI model
#         prompt = (
#             '''You are an advanced dieticiant who analysis healthcare report of a patient or data given by him with uploaded product details and present the structure personlised analysis report of the user as follows
#             Summary: A concise description of the patient’s health condition and key findings.
#             Recommendations: Dietary and lifestyle suggestions tailored to the patient’s health, including food choices, supplements, and medical consultations.
#             Ingredients Categorization: List the analyzed ingredients in three categories:Bad: Ingredients that are harmful or unsafe due to allergies or adverse effects.
#             Normal: Ingredients that are safe but should be consumed in moderation.
#             Good: Ingredients that are beneficial and recommended.
#             Risk on Health: Highlight the risks associated with the patient's condition, including the impact of allergens and nutritional deficiencies.
#             Detailed Overview: Provide a comprehensive explanation of the analysis and overall assessment of the patient’s dietary needs.
#             Suitability: Conclude whether the analyzed product is healthy for the patient. Suggest a suitable replacement product if necessary.
#             Graphical Risk Scale: Represent the risk level (on a scale of 0 to 10) with a traffic light color-coded visual, where green indicates low risk, yellow indicates moderate risk, and red indicates high risk.
#             Ensure the response is structured, visually organized, and easy to understand. The risk scale should be visually integrated into the result."
#             remove disclaimers and make all sections short and simple
#             also add summary of analysis whether product is good for him or not'''
#             "**Patient Data:**\n"
#             f"{json.dumps(serialized_data, indent=2)}\n\n"
#             "**Ingredients:**\n"
#             f"{', '.join(ingredients)}\n\n"
#             "Ensure the response is concise, accurate, and tailored to the patient's health conditions."
#         )

#         # Select the appropriate model
#         model = genai.GenerativeModel("gemini-1.5-flash")
        
#         # Implement exponential backoff for API calls
#         max_retries = 3
#         for attempt in range(max_retries):
#             try:
#                 logger.info(f"Calling Gemini API (attempt {attempt+1}/{max_retries})...")
#                 result = model.generate_content([prompt])
                
#                 # Ensure AI output exists before accessing parts
#                 if result and hasattr(result, 'candidates') and result.candidates and result.candidates[0].content and result.candidates[0].content.parts:
#                     response_text = result.candidates[0].content.parts[0].text
                    
#                     # Cache the result if caching is enabled
#                     if use_cache and cache_key:
#                         _response_cache[cache_key] = {
#                             "result": response_text,
#                             "timestamp": time.time()
#                         }
                        
#                     return response_text
#                 else:
#                     logger.warning("Received empty response from Gemini API")
                    
#             except (PermissionDenied, GoogleAPICallError) as e:
#                 if attempt < max_retries - 1:
#                     wait_time = (2 ** attempt) + 1  # Exponential backoff with jitter
#                     logger.warning(f"API error: {e}. Retrying in {wait_time}s...")
#                     time.sleep(wait_time)
#                 else:
#                     logger.error(f"API error after {max_retries} attempts: {e}")
#                     raise
        
#         # Fallback response if all retries fail
#         return "Unable to generate analysis after multiple attempts. Please try again later."
    
#     except Exception as e:
#         logger.exception(f"Unexpected error in analysis: {e}")
#         return f"Error in generating analysis: {str(e)}"


import json
import google.generativeai as genai
from google.api_core.exceptions import PermissionDenied, GoogleAPICallError
import os
from dotenv import load_dotenv
from google.cloud import firestore
import logging
import hashlib
import time

# Load environment variables
load_dotenv()
API_KEY = os.getenv("GOOGLE_API_KEY")

if not API_KEY:
    raise ValueError("GOOGLE_API_KEY not set. Cannot initialize Gemini API.")

genai.configure(api_key=API_KEY)

# Configure logging
logger = logging.getLogger(__name__)

# Simple in-memory cache for API responses (reduces API costs during testing)
# In production, consider using Redis or another distributed cache
_response_cache = {}

def serialize_firestore_data(data):
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

def create_cache_key(healthcare_data, ingredients):
    """Create a cache key based on input data."""
    combined = json.dumps({
        "health": healthcare_data,
        "ingredients": ingredients
    }, sort_keys=True)
    return hashlib.md5(combined.encode()).hexdigest()

def calculate_risk_scale(analysis_text):
    """
    Calculate a risk scale based on the analysis text.
    
    Args:
        analysis_text (str): Detailed analysis from Gemini
    
    Returns:
        float: Risk score between 0 and 10
    """
    try:
        # Look for indicators of risk in the text
        risk_indicators = {
            "high risk": 8,
            "very high risk": 9,
            "moderate risk": 5,
            "low risk": 2,
            "safe": 1,
            "dangerous": 9,
            "allergic": 9,
            "avoid": 8,
            "not recommended": 7,
            "caution": 6,
            "relatively safe": 3,
            "good": 1
        }
        
        # Convert text to lowercase for case-insensitive matching
        lower_analysis = analysis_text.lower()
        
        # Find the maximum risk score based on keywords
        max_risk = 5  # Default neutral risk
        for keyword, risk_value in risk_indicators.items():
            if keyword in lower_analysis:
                max_risk = max(max_risk, risk_value)
        
        return min(max(0, max_risk), 10)
    
    except Exception as e:
        logger.error(f"Error calculating risk scale: {e}")
        return 5  # Neutral risk if calculation fails

def analyze(healthcare_data, ingredients, use_cache=True, cache_ttl=3600):
    """Analyze product safety based on user's healthcare data and ingredients.
    
    Args:
        healthcare_data (dict): User's healthcare data
        ingredients (list): List of ingredients to analyze
        use_cache (bool): Whether to use caching (default: True)
        cache_ttl (int): Cache time-to-live in seconds (default: 1 hour)
        
    Returns:
        tuple: Analysis results as formatted text and risk scale
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
            '''You are an advanced dieticiant who analyses healthcare report of a patient or data given by him with uploaded product details and present the structure personalised analysis report of the user as follows
            Summary: A concise description of the patient's health condition and key findings.
            Recommendations: Dietary and lifestyle suggestions tailored to the patient's health, including food choices, supplements, and medical consultations.
            Ingredients Categorization: List the analyzed ingredients in three categories:Bad: Ingredients that are harmful or unsafe due to allergies or adverse effects.
            Normal: Ingredients that are safe but should be consumed in moderation.
            Good: Ingredients that are beneficial and recommended.
            Risk on Health: Highlight the risks associated with the patient's condition, including the impact of allergens and nutritional deficiencies.
            Detailed Overview: Provide a comprehensive explanation of the analysis and overall assessment of the patient's dietary needs.
            Suitability: Conclude whether the analyzed product is healthy for the patient. Suggest a suitable replacement product if necessary.
            Include clear language about the health risks and impact of the ingredients.
            Ensure the response includes a clear assessment of risk level and overall suitability for the patient's health conditions.'''
            "**Patient Data:**\n"
            f"{json.dumps(serialized_data, indent=2)}\n\n"
            "**Ingredients:**\n"
            f"{', '.join(ingredients)}\n\n"
            "Ensure the response is concise, accurate, and tailored to the patient's health conditions."
        )

        # Select the appropriate model
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        # Implement exponential backoff for API calls
        max_retries = 3
        for attempt in range(max_retries):
            try:
                logger.info(f"Calling Gemini API (attempt {attempt+1}/{max_retries})...")
                result = model.generate_content([prompt])
                
                # Ensure AI output exists before accessing parts
                if result and hasattr(result, 'candidates') and result.candidates and result.candidates[0].content and result.candidates[0].content.parts:
                    response_text = result.candidates[0].content.parts[0].text
                    
                    # Calculate risk scale based on analysis
                    risk_scale = calculate_risk_scale(response_text)
                    
                    # Cache the result if caching is enabled
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
        
        # Fallback response if all retries fail
        return "Unable to generate analysis after multiple attempts. Please try again later.", 5
    
    except Exception as e:
        logger.exception(f"Unexpected error in analysis: {e}")
        return f"Error in generating analysis: {str(e)}", 5
