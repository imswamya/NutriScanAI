import requests
import datetime as dt
import logging
import time
from jose import jwt
from jose.exceptions import JWTError

# Configure logging
logger = logging.getLogger(__name__)

# Global variables
FIREBASE_PUBLIC_KEYS_URL = "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"
FIREBASE_CERTIFICATES = {}
FIREBASE_AUDIENCE = "nutri-scan-a-i-3am8a8"  # ✅ Your Firebase Project ID
FIREBASE_ISSUER = f"https://securetoken.google.com/{FIREBASE_AUDIENCE}"
LAST_REFRESH_TIME = 0
REFRESH_INTERVAL = 60 * 60  # 1 hour in seconds
TOKEN_CACHE = {}           # Simple in-memory token cache

def initialize():
    """Initialize the token verification system."""
    refresh_certificates()
    logger.info(f"Token verification initialized for project: {FIREBASE_AUDIENCE}")

def refresh_certificates():
    """Fetch the latest Firebase public certificates."""
    global FIREBASE_CERTIFICATES, LAST_REFRESH_TIME

    try:
        response = requests.get(FIREBASE_PUBLIC_KEYS_URL, timeout=10)
        response.raise_for_status()

        FIREBASE_CERTIFICATES = response.json()
        LAST_REFRESH_TIME = time.time()

        # Get cache control headers to see when certs will expire
        cache_control = response.headers.get('Cache-Control', '')
        if 'max-age=' in cache_control:
            max_age = int(cache_control.split('max-age=')[1].split(',')[0])
            global REFRESH_INTERVAL
            REFRESH_INTERVAL = int(max_age * 0.9)

        logger.info(f"Certificates refreshed. Next refresh in {REFRESH_INTERVAL} seconds.")

    except Exception as e:
        logger.error(f"Error refreshing certificates: {e}")
        if not FIREBASE_CERTIFICATES:
            raise RuntimeError("Failed to initialize Firebase certificates")

def verify_token(token):
    """Verifies a Firebase JWT token without making a network request to Firebase."""
    
    # Check if token is in cache
    if token in TOKEN_CACHE:
        cache_entry = TOKEN_CACHE[token]
        if cache_entry["expires_at"] > (time.time() + 300):  # Check cache with 5 min buffer
            logger.info("Using cached token verification")
            return cache_entry["user_data"]

    # Check if certificates need refresh
    if time.time() - LAST_REFRESH_TIME > REFRESH_INTERVAL:
        logger.info("Certificate refresh interval exceeded. Refreshing...")
        refresh_certificates()

    try:
        # Get unverified header to extract key ID
        headers = jwt.get_unverified_header(token)
        key_id = headers["kid"]

        if key_id not in FIREBASE_CERTIFICATES:
            logger.error(f"Unknown key id: {key_id}")
            raise ValueError("Invalid token signature")

        key = FIREBASE_CERTIFICATES[key_id]
        current_ts = int(time.time())

        decoded = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=FIREBASE_AUDIENCE
        )

        # Validate token claims
        if decoded.get("exp", 0) < current_ts:
            raise ValueError("Token has expired")

        if decoded.get("iat", 0) > current_ts:
            raise ValueError("Token issued in the future")

        if decoded.get("aud", "") != FIREBASE_AUDIENCE:
            raise ValueError("Invalid audience")

        if decoded.get("iss", "") != FIREBASE_ISSUER:
            raise ValueError("Invalid issuer")

        if not decoded.get("sub", ""):
            raise ValueError("Invalid subject")

        # Store in cache
        TOKEN_CACHE[token] = {
            "user_data": {
                "uid": decoded.get("sub", ""),
                "email": decoded.get("email", ""),
                "email_verified": decoded.get("email_verified", False),
                "phone_number": decoded.get("phone_number", "")
            },
            "expires_at": decoded.get("exp", 0)
        }

        return TOKEN_CACHE[token]["user_data"]

    except JWTError as e:
        logger.error(f"JWT decode error: {e}")
        raise ValueError("Invalid token format or signature")
