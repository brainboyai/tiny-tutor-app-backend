# app.py
from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import re
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
import json
import base64
import requests # For Gemini API calls
import jwt # PyJWT for encoding/decoding
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps # For JWT decorator

# Load environment variables from .env file
load_dotenv()

# Initialize Flask App FIRST
app = Flask(__name__)

# Configure CORS - Adjust origins as needed for your frontend
CORS(app, resources={r"/*": {"origins": [
    "https://tiny-tutor-app-frontend.onrender.com", # Your deployed frontend
    "http://localhost:5173", # Local Vite dev server
    "http://127.0.0.1:5173"  # Alternate local Vite dev server
]}}, supports_credentials=True)


# --- JWT Configuration & Helper ---
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'fallback_secret_key_for_dev_only') # Ensure this is strong and in .env
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)

# --- Firebase Initialization ---
service_account_key_base64 = os.getenv('FIREBASE_SERVICE_ACCOUNT_KEY_BASE64')
db = None # Firestore database client

if service_account_key_base64:
    try:
        # Decode the base64 string to bytes, then decode bytes to UTF-8 string
        decoded_key_bytes = base64.b64decode(service_account_key_base64)
        decoded_key_str = decoded_key_bytes.decode('utf-8')
        cred_json = json.loads(decoded_key_str) # Parse the JSON string
        
        cred = credentials.Certificate(cred_json)
        if not firebase_admin._apps: # Check if app already initialized
            firebase_admin.initialize_app(cred)
        db = firestore.client()
        app.logger.info("Firebase initialized successfully.")
    except Exception as e:
        app.logger.error(f"Error initializing Firebase Admin SDK: {e}")
        db = None # Ensure db is None if initialization fails
else:
    app.logger.warning("FIREBASE_SERVICE_ACCOUNT_KEY_BASE64 not found. Firestore integration will be disabled.")

# --- Gemini API Configuration ---
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={GEMINI_API_KEY}"

# --- JWT Decorator ---
def jwt_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({"error": "Authorization header is missing"}), 401
        
        parts = auth_header.split()
        if parts[0].lower() != 'bearer' or len(parts) == 1 or len(parts) > 2:
            return jsonify({"error": "Invalid Authorization header format"}), 401
        
        token = parts[1]
        try:
            payload = jwt.decode(token, app.config['JWT_SECRET_KEY'], algorithms=["HS256"])
            request.current_user_jwt = payload # Store payload in request context
            # Optionally, fetch user from DB here if needed for every request,
            # but for user_id, username, tier, JWT is enough.
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token has expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401
        return f(*args, **kwargs)
    return decorated_function

# --- Helper Functions ---
def sanitize_word_id(word):
    """Creates a Firestore-safe document ID from a word."""
    if not word: return None
    # Lowercase, replace special characters (including / * [ ]) with underscore, trim, and truncate
    sanitized = re.sub(r'[/*\[\]\s.#$]+', '_', word.lower().strip())
    return sanitized[:100] # Firestore document ID limit is 1500 bytes, 100 chars is safe

# --- Routes ---
@app.route('/')
def home():
    return "Tiny Tutor Backend is running!"

@app.route('/signup', methods=['POST'])
def signup():
    if not db:
        return jsonify({"error": "Database service not available"}), 503
        
    data = request.get_json()
    if not data or not data.get('username') or not data.get('email') or not data.get('password'):
        return jsonify({"error": "Missing username, email, or password"}), 400

    username = data['username'].strip()
    email = data['email'].strip().lower()
    password = data['password']

    if len(username) < 3 or len(password) < 6:
        return jsonify({"error": "Username must be at least 3 characters and password at least 6 characters"}), 400
    
    # Basic email validation
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return jsonify({"error": "Invalid email format"}), 400

    user_ref = db.collection('users').document(username)
    if user_ref.get().exists:
        return jsonify({"error": "Username already exists"}), 409 # Conflict

    # Check if email already exists (optional, but good practice)
    # users_query = db.collection('users').where('email', '==', email).limit(1).stream()
    # if any(users_query):
    #     return jsonify({"error": "Email already registered"}), 409

    hashed_password = generate_password_hash(password)
    user_data = {
        "username": username,
        "email": email,
        "password": hashed_password,
        "tier": "basic", # Default tier
        "created_at": firestore.SERVER_TIMESTAMP
    }
    try:
        user_ref.set(user_data)
        return jsonify({"message": "User created successfully"}), 201
    except Exception as e:
        app.logger.error(f"Error creating user {username}: {e}")
        return jsonify({"error": f"Could not create user: {e}"}), 500


@app.route('/login', methods=['POST'])
def login():
    if not db:
        return jsonify({"error": "Database service not available"}), 503

    data = request.get_json()
    if not data or not data.get('username') or not data.get('password'):
        return jsonify({"error": "Missing username or password"}), 400

    username = data['username'].strip()
    password = data['password']
    
    user_ref = db.collection('users').document(username)
    user_doc = user_ref.get()

    if not user_doc.exists:
        return jsonify({"error": "Invalid username or password"}), 401 # Unauthorized
    
    user_data = user_doc.to_dict()
    if not check_password_hash(user_data.get('password', ''), password):
        return jsonify({"error": "Invalid username or password"}), 401

    # Create JWT token
    token_payload = {
        'user_id': user_doc.id, # This is the username
        'username': user_data.get('username'),
        'tier': user_data.get('tier', 'basic'),
        'exp': datetime.now(timezone.utc) + app.config['JWT_ACCESS_TOKEN_EXPIRES']
    }
    access_token = jwt.encode(token_payload, app.config['JWT_SECRET_KEY'], algorithm="HS256")
    
    return jsonify({"message": "Login successful", "access_token": access_token}), 200

@app.route('/generate_explanation', methods=['POST'])
@jwt_required
def generate_explanation_route():
    if not db:
        return jsonify({"error": "Database service not available"}), 503
    if not GEMINI_API_KEY:
        return jsonify({"error": "AI service not configured"}), 503

    data = request.get_json()
    question = data.get('question', '').strip()
    content_type = data.get('content_type', 'explain').strip().lower() # explain, image, fact, quiz, deep

    if not question:
        return jsonify({"error": "Question/concept is required"}), 400
    
    user_id = request.current_user_jwt.get('user_id') # Username from JWT
    if not user_id:
        return jsonify({"error": "User not identified"}), 401

    # --- Firestore Word History Update ---
    sanitized_id = sanitize_word_id(question)
    word_doc_ref = db.collection('users').document(user_id).collection('word_history').document(sanitized_id)
    
    explanation_text = f"Placeholder for {content_type} about '{question}'" # Default placeholder

    # --- Handle Placeholder Modes ---
    if content_type == "image":
        explanation_text = f"Image generation feature coming soon! You can imagine an image of '{question}'."
    elif content_type == "deep":
        explanation_text = f"In-depth explanation feature coming soon! We're working on providing more detailed insights for '{question}'."
    
    # --- Call Gemini API for other modes ---
    else:
        prompt = ""
        if content_type == "explain":
            # MODIFIED PROMPT for word highlighting
            prompt = (
                f"Explain the concept of '{question}' in a concise and easy-to-understand way (around 100-150 words). "
                f"In your explanation, please identify one single important keyword or closely related concept that a user might want to explore further. "
                f"Wrap this single keyword with <click> tags. For example, if explaining 'photosynthesis', "
                f"you might output something like: 'Photosynthesis is the process used by plants to convert light "
                f"energy into chemical energy, primarily through the action of <click>chlorophyll</click>.' "
                f"Only use the <click>YourChosenWord</click> tags once for the most relevant keyword. Do not use any other HTML or Markdown for highlighting."
            )
        elif content_type == "fact":
            prompt = f"Tell me an interesting and concise fun fact about '{question}'."
        elif content_type == "quiz":
            prompt = f"Create a very short multiple-choice quiz question (1 question, 3 options: A, B, C, and then the correct answer on a new line like 'Answer: A') about '{question}'. Keep it brief."
        else: # Should not happen if frontend sends valid modes
            return jsonify({"error": "Invalid content type requested"}), 400

        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        try:
            response = requests.post(GEMINI_API_URL, json=payload, timeout=25) # 25 second timeout
            response.raise_for_status() # Raise an exception for HTTP errors
            result = response.json()
            
            if result.get('candidates') and result['candidates'][0].get('content') and result['candidates'][0]['content'].get('parts'):
                explanation_text = result['candidates'][0]['content']['parts'][0].get('text', 'AI could not generate content for this query.')
            else:
                # Check for safety ratings or other blocks
                if result.get('promptFeedback') and result['promptFeedback'].get('blockReason'):
                    reason = result['promptFeedback']['blockReason']
                    explanation_text = f"Content generation blocked due to: {reason}. Please try a different query."
                    app.logger.warning(f"Gemini content blocked for '{question}': {reason}")
                else:
                    explanation_text = "AI response format was unexpected. Please try again."
                    app.logger.error(f"Unexpected Gemini response for '{question}': {result}")

        except requests.exceptions.RequestException as e:
            app.logger.error(f"Gemini API request failed for '{question}': {e}")
            explanation_text = f"Error connecting to AI service: {e}. Please try again later."
        except Exception as e: # Catch any other unexpected errors
            app.logger.error(f"Unexpected error during Gemini call for '{question}': {e}")
            explanation_text = f"An unexpected error occurred with the AI service: {e}"


    # --- Update Firestore ---
    try:
        word_doc_data = word_doc_ref.get()
        current_time = firestore.SERVER_TIMESTAMP # Use server timestamp for consistency

        if word_doc_data.exists:
            update_data = {
                'last_explored_at': current_time,
                f'generated_content_cache.{content_type}': explanation_text,
                'modes_generated': firestore.ArrayUnion([content_type])
            }
            word_doc_ref.update(update_data)
        else:
            word_doc_ref.set({
                'word': question, # Original casing
                'sanitized_word': sanitize_word_id(question), # Lowercase, trimmed for consistency if needed elsewhere
                'is_favorite': False,
                'first_explored_at': current_time,
                'last_explored_at': current_time,
                'modes_generated': [content_type],
                'generated_content_cache': {
                    content_type: explanation_text
                }
            })
        app.logger.info(f"Word history for '{question}' (mode: {content_type}) updated for user '{user_id}'.")
    except Exception as e:
        app.logger.error(f"Firestore update failed for '{question}', user '{user_id}': {e}")
        # Don't fail the whole request if Firestore write fails, but log it.
        # The user still gets the explanation.

    return jsonify({"explanation": explanation_text, "contentType": content_type}), 200


@app.route('/toggle_favorite', methods=['POST'])
@jwt_required
def toggle_favorite():
    if not db: return jsonify({"error": "Database service not available"}), 503
    
    data = request.get_json()
    word_to_toggle = data.get('word', '').strip()
    if not word_to_toggle: return jsonify({"error": "Word is required"}), 400

    user_id = request.current_user_jwt.get('user_id')
    sanitized_id = sanitize_word_id(word_to_toggle)
    word_doc_ref = db.collection('users').document(user_id).collection('word_history').document(sanitized_id)

    try:
        word_doc = word_doc_ref.get()
        if not word_doc.exists:
            # If word doesn't exist in history, we can't favorite it (or create it as non-favorite first)
            # For simplicity, let's assume it should exist if user is trying to favorite from UI
            return jsonify({"error": "Word not found in your history. Explore it first."}), 404
        
        current_status = word_doc.to_dict().get('is_favorite', False)
        word_doc_ref.update({'is_favorite': not current_status, 'last_explored_at': firestore.SERVER_TIMESTAMP})
        return jsonify({"message": "Favorite status updated", "new_status": not current_status}), 200
    except Exception as e:
        app.logger.error(f"Error toggling favorite for '{word_to_toggle}', user '{user_id}': {e}")
        return jsonify({"error": f"Could not update favorite status: {e}"}), 500

@app.route('/profile', methods=['GET'])
@jwt_required
def get_profile():
    if not db: return jsonify({"error": "Database service not available"}), 503

    user_id = request.current_user_jwt.get('user_id')
    # user_doc_ref = db.collection('users').document(user_id) # Not needed if JWT has username/tier
    
    word_history_coll_ref = db.collection('users').document(user_id).collection('word_history')
    
    try:
        # Order by last_explored_at descending. Firestore requires an index for this.
        # If you get an error about index, Firestore will provide a link to create it.
        all_words_query = word_history_coll_ref.order_by('last_explored_at', direction=firestore.Query.DESCENDING).stream()
        
        explored_words = []
        favorite_words = []

        for doc in all_words_query:
            data = doc.to_dict()
            # Ensure timestamp is serializable (ISO format)
            last_explored_iso = None
            if 'last_explored_at' in data and hasattr(data['last_explored_at'], 'isoformat'):
                last_explored_iso = data['last_explored_at'].isoformat()
            
            display_word = {
                "id": doc.id, # This is the sanitized_word_id
                "word": data.get('word', 'N/A'), # Original word
                "is_favorite": data.get('is_favorite', False),
                "last_explored_at": last_explored_iso,
                "generated_content_cache": data.get('generated_content_cache', {}), # Include cache
                "modes_generated": data.get('modes_generated', [])
            }
            explored_words.append(display_word)
            if display_word["is_favorite"]:
                favorite_words.append(display_word)
        
        return jsonify({
            "username": request.current_user_jwt.get('username'), # From JWT
            "tier": request.current_user_jwt.get('tier'),       # From JWT
            "explored_words_count": len(explored_words),
            "explored_words_list": explored_words,
            "favorite_words_list": favorite_words # Already sorted by last_explored_at due to initial query
        }), 200
    except Exception as e:
        app.logger.error(f"Error fetching profile for user '{user_id}': {e}")
        # Check if the error message contains "index" to guide user
        if "index" in str(e).lower():
            return jsonify({"error": f"Profile fetch failed: {e}. This might be due to a missing Firestore index. Please check backend logs for a link to create it."}), 500
        return jsonify({"error": f"Profile fetch failed: {e}"}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001)) # Render typically sets PORT env var
    # For local development, use Flask's dev server. For production, Gunicorn is specified in Procfile.
    # The FLASK_DEBUG env var will control debug mode.
    app.run(host='0.0.0.0', port=port, debug=os.getenv('FLASK_DEBUG', '0') == '1')
