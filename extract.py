import json
import google.generativeai as genai
from google.api_core.exceptions import PermissionDenied, GoogleAPICallError
import logging
import os
import re
import mimetypes
import time
from io import BytesIO
from werkzeug.utils import secure_filename
import tempfile
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
API_KEY = os.getenv("GOOGLE_API_KEY")

if not API_KEY:
    raise ValueError("GOOGLE_API_KEY not set. Cannot initialize Gemini API.")

genai.configure(api_key=API_KEY)

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("extract.log", mode="a"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Allowed MIME types for security
ALLOWED_MIME_TYPES = {"image/png", "image/jpeg", "application/pdf"}

# --- Helper Functions ---
def save_file_temporarily(file_storage_object) -> str:
    """Save uploaded file temporarily with validation.
    
    Args:
        file_storage_object (BytesIO): File-like object to save
        
    Returns:
        str: Path to temporarily saved file
        
    Raises:
        ValueError: If file type is not allowed
        IOError: If file saving fails
    """
    temp_path = None
    try:
        # Check if we're dealing with BytesIO or similar
        if hasattr(file_storage_object, 'read') and callable(file_storage_object.read):
            # Read the first few bytes to check file type
            file_storage_object.seek(0)
            file_header = file_storage_object.read(2048)
            file_storage_object.seek(0)
            
            # Guess MIME type from file content
            mime_type = mimetypes.guess_type("file.pdf")[0]  # Default to PDF
            
            # Check for JPEG/PNG signatures
            if file_header.startswith(b'\xff\xd8'):
                mime_type = "image/jpeg"
            elif file_header.startswith(b'\x89PNG\r\n\x1a\n'):
                mime_type = "image/png"
            elif b'%PDF-' in file_header:
                mime_type = "application/pdf"
                
            if mime_type not in ALLOWED_MIME_TYPES:
                raise ValueError(f"Unsupported file type detected: {mime_type}")
                
            # Create temporary file with appropriate extension
            ext = ".pdf" if mime_type == "application/pdf" else ".jpg"
            temp_fd, temp_path = tempfile.mkstemp(suffix=ext)
            
            with os.fdopen(temp_fd, "wb") as tmp_file:
                # Reset the file pointer and copy all content
                file_storage_object.seek(0)
                tmp_file.write(file_storage_object.read())
                
            logger.info(f"File saved temporarily at: {temp_path}")
            return temp_path
            
        else:
            raise ValueError("Invalid file object provided")
            
    except Exception as e:
        # Clean up the temp file if something goes wrong
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass
        logger.error(f"Error saving temp file: {e}")
        raise

def call_gemini_api(prompt, file_path, retries=3, model_name="gemini-1.5-flash"):
    """Handle Gemini API calls with error handling and retries.
    
    Args:
        prompt (str): The prompt to send to the AI
        file_path (str): Path to the file to analyze
        retries (int): Number of retry attempts
        model_name (str): Gemini model to use
        
    Returns:
        object: Gemini API response object or None if failed
    """
    for attempt in range(retries):
        try:
            logger.info(f"Uploading file to Gemini API: {file_path}")
            report_file = genai.upload_file(file_path)
            if not report_file:
                logger.error("Gemini file upload failed.")
                time.sleep(2 ** attempt)
                continue

            model = genai.GenerativeModel(model_name)
            response = model.generate_content([report_file, prompt])

            logger.info(f"Gemini API response received")
            if response and hasattr(response, "candidates") and response.candidates:
                return response

            logger.warning(f"AI returned no candidates. Attempt {attempt + 1} failed.")
            
        except (PermissionDenied, GoogleAPICallError) as e:
            logger.error(f"Gemini API error: {e}")
        except Exception as e:
            logger.error(f"Unexpected error in API call: {e}")

        # Exponential backoff before retrying
        wait_time = (2 ** attempt) + (attempt * 0.1)  # adding jitter
        logger.info(f"Waiting {wait_time:.2f}s before retry...")
        time.sleep(wait_time)

    return None

def clean_and_parse_json(raw_text):
    """Cleans and parses JSON safely from AI response.
    
    Args:
        raw_text (str): Raw text containing JSON
        
    Returns:
        dict/list: Parsed JSON object or empty dict/list on failure
    """
    # Check if empty
    if not raw_text or not raw_text.strip():
        return {}
        
    # Try multiple approaches to extract valid JSON
    try:
        # First try: Direct parse
        return json.loads(raw_text)
    except json.JSONDecodeError:
        pass
        
    try:
        # Second try: Look for JSON in code blocks
        json_pattern = r'```(?:json)?\s*([\s\S]*?)\s*```'
        matches = re.findall(json_pattern, raw_text)
        if matches:
            return json.loads(matches[0].strip())
    except json.JSONDecodeError:
        pass
        
    try:
        # Third try: Clean up common issues and retry
        cleaned_text = re.sub(r"`json\n|\n`", "", raw_text).replace('"null"', 'null')
        cleaned_text = re.sub(r",\s*}", "}", cleaned_text).replace(", ]", "]")
        return json.loads(cleaned_text)
    except json.JSONDecodeError:
        pass
        
    try:
        # Fourth try: More aggressive cleanup
        text = raw_text.strip()
        
        # Find first { or [ and last } or ]
        start_idx = min((text.find('{') if text.find('{') != -1 else float('inf')), 
                         (text.find('[') if text.find('[') != -1 else float('inf')))
        end_idx_brace = text.rfind('}')
        end_idx_bracket = text.rfind(']')
        end_idx = max(end_idx_brace, end_idx_bracket)
        
        if start_idx < float('inf') and end_idx != -1:
            potential_json = text[start_idx:end_idx+1]
            return json.loads(potential_json)
    except (json.JSONDecodeError, ValueError):
        pass
        
    # Last resort: Return empty object based on context
    logger.error(f"Failed to parse JSON: {raw_text[:100]}...")
    return {} if '{' in raw_text else []

# --- Healthcare Data Extraction ---
def extract_healthcare_data(file_storage_object):
    """Extract healthcare data from an image or PDF file using AI.
    
    Args:
        file_storage_object (BytesIO): File-like object containing healthcare report
        
    Returns:
        dict: Extracted healthcare data as key-value pairs
    """
    temp_path = None
    try:
        logger.info("Processing healthcare report...")
        temp_path = save_file_temporarily(file_storage_object)

        prompt = """
        Extract structured healthcare data from this medical report.
        Return a JSON object with key health metrics and conditions.
        Format: 
        {
            "blood_pressure": "120/80",
            "blood_sugar": "100 mg/dL",
            "cholesterol": {"total": "180 mg/dL", "hdl": "50 mg/dL", "ldl": "100 mg/dL"},
            "conditions": ["diabetes", "hypertension"],
            "allergies": ["peanuts", "shellfish"],
            "medications": ["metformin", "lisinopril"]
        }
        Include only fields that are present in the document.
        """
        
        response = call_gemini_api(prompt, temp_path)

        if response and hasattr(response, "candidates") and response.candidates:
            raw_text = "".join(part.text for part in response.candidates[0].content.parts if hasattr(part, "text"))
            extracted_data = clean_and_parse_json(raw_text)
            
            if extracted_data and isinstance(extracted_data, dict):
                logger.info("Healthcare data extraction successful.")
                return extracted_data
            else:
                logger.warning("Extracted data is not a valid dictionary.")
                return {}

        logger.warning("No healthcare data found in AI response.")
        return {}

    except Exception as e:
        logger.error(f"Unexpected error in extract_healthcare_data: {e}", exc_info=True)
        return {}
    finally:
        # Clean up temp file
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                logger.info(f"Deleted temp file: {temp_path}")
            except Exception as cleanup_error:
                logger.warning(f"Failed to delete temp file {temp_path}: {cleanup_error}")

# --- Ingredient Extraction ---
def extract_ingredients(file_storage_object):
    """Extract ingredients from an image file using AI.
    
    Args:
        file_storage_object (BytesIO): File-like object containing ingredient list image
        
    Returns:
        list: Extracted list of ingredients
    """
    temp_path = None
    try:
        logger.info("Processing ingredient image...")
        temp_path = save_file_temporarily(file_storage_object)

        prompt = """
        Extract all ingredients from this food product label or image.
        Return a JSON array of ingredients, one per item.
        Format example: ["sugar", "salt", "milk", "wheat flour", "preservatives"]
        Be comprehensive and include all visible ingredients.
        """
        
        response = call_gemini_api(prompt, temp_path)

        if response and hasattr(response, "candidates") and response.candidates:
            raw_text = "".join(part.text for part in response.candidates[0].content.parts if hasattr(part, "text"))
            extracted_ingredients = clean_and_parse_json(raw_text)
            
            if extracted_ingredients and isinstance(extracted_ingredients, list):
                logger.info(f"Successfully extracted {len(extracted_ingredients)} ingredients.")
                return extracted_ingredients
            else:
                logger.warning("Extracted data is not a valid ingredient list.")
                return []

        logger.warning("No ingredients found in AI response.")
        return []

    except Exception as e:
        logger.error(f"Unexpected error in extract_ingredients: {e}", exc_info=True)
        return []
    finally:
        # Clean up temp file
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                logger.info(f"Deleted temp file: {temp_path}")
            except Exception as cleanup_error:
                logger.warning(f"Failed to delete temp file {temp_path}: {cleanup_error}")