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
        # Decode the base64 string to JSON
        decoded_key = base64.b64decode(service_account_key_base64).decode('utf-8')
        service_account_info = json.loads(decoded_key)
        
        # Initialize Firebase Admin SDK
        cred = credentials.Certificate(service_account_info)
        firebase_admin.initialize_app(cred)
        db = firestore.client() # Initialize Firestore client
        app.logger.info("Firebase Admin SDK initialized successfully.")
    except Exception as e:
        app.logger.error(f"Failed to initialize Firebase Admin SDK: {e}")
        db = None # Ensure db is None if initialization fails
else:
    app.logger.warning("FIREBASE_SERVICE_ACCOUNT_KEY_BASE64 not found. Firebase Admin SDK not initialized.")

# --- Gemini API Configuration ---
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GEMINI_API_URL_BASE = "https://generativelanguage.googleapis.com/v1beta/models/"
# Using the specific model from the report
GEMINI_MODEL = "gemini-1.5-flash-latest:generateContent"


# --- Helper Functions ---
def sanitize_word_for_id(word):
    """Sanitizes a word to be used as a Firestore document ID."""
    sanitized = re.sub(r'[^a-zA-Z0-9_.-]', '_', word)
    return sanitized[:100] # Limit length for IDs

# --- JWT Decorator ---
# This decorator ensures that a valid JWT is present in the request header
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            if auth_header.startswith('Bearer '):
                token = auth_header.split(" ")[1]
        
        if not token:
            return jsonify({'error': 'Token is missing!'}), 401
        
        try:
            # Decode the token using the secret key
            data = jwt.decode(token, app.config['JWT_SECRET_KEY'], algorithms=["HS256"])
            # Store the decoded payload in a request-local or pass to function
            # For simplicity, we can attach it to `request` or a global-like context if needed,
            # but it's often better to pass it directly or use Flask's `g` object.
            # Here, we'll assume the route itself will access `data`.
            # To make it available to the route like `request.current_user_jwt`:
            request.current_user_jwt = data 
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired!'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Token is invalid!'}), 401
        
        return f(*args, **kwargs)
    return decorated

# --- API Endpoints ---

@app.route('/')
def home():
    return "Tiny Tutor Backend is running!"

@app.route('/signup', methods=['POST'])
def signup():
    if not db:
        return jsonify({"error": "Database not initialized. Cannot process signup."}), 500
        
    data = request.get_json()
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')

    if not username or not email or not password:
        return jsonify({"error": "Missing username, email, or password"}), 400

    # Validate username (e.g., length, characters)
    if not re.match("^[a-zA-Z0-9_]{3,20}$", username):
        return jsonify({"error": "Invalid username. Must be 3-20 characters, letters, numbers, or underscores."}), 400
    
    # Validate email
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return jsonify({"error": "Invalid email format."}), 400

    # Validate password (e.g., length, complexity)
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters long."}), 400

    try:
        user_ref = db.collection('users').document(username)
        if user_ref.get().exists:
            return jsonify({"error": "Username already exists"}), 409 # Conflict

        hashed_password = generate_password_hash(password)
        
        user_data = {
            "username": username,
            "email": email.lower(), # Store email in lowercase for consistency
            "password": hashed_password,
            "tier": "free", # Default tier
            "created_at": firestore.SERVER_TIMESTAMP
        }
        user_ref.set(user_data)
        
        app.logger.info(f"User '{username}' created successfully.")
        return jsonify({"message": "User created successfully"}), 201
    except Exception as e:
        app.logger.error(f"Error during signup for user '{username}': {e}")
        return jsonify({"error": f"Signup failed: {e}"}), 500


@app.route('/login', methods=['POST'])
def login():
    if not db:
        return jsonify({"error": "Database not initialized. Cannot process login."}), 500

    data = request.get_json()
    username_or_email = data.get('usernameOrEmail')
    password = data.get('password')

    if not username_or_email or not password:
        return jsonify({"error": "Missing username/email or password"}), 400

    try:
        user_doc = None
        # Check if it's an email or username
        if "@" in username_or_email: # Assume it's an email
            users_query = db.collection('users').where('email', '==', username_or_email.lower()).limit(1).stream()
            for doc in users_query: # Should be at most one
                user_doc = doc
        else: # Assume it's a username
            doc_ref = db.collection('users').document(username_or_email)
            fetched_doc = doc_ref.get()
            if fetched_doc.exists:
                user_doc = fetched_doc
        
        if not user_doc or not user_doc.exists:
            return jsonify({"error": "Invalid credentials"}), 401 

        user_data = user_doc.to_dict()
        
        if not check_password_hash(user_data.get('password', ''), password):
            return jsonify({"error": "Invalid credentials"}), 401

        # Create JWT token
        token_payload = {
            'username': user_data['username'], # Use username as user_id in JWT as per report
            'email': user_data['email'],
            'tier': user_data.get('tier', 'free'),
            'exp': datetime.now(timezone.utc) + app.config['JWT_ACCESS_TOKEN_EXPIRES']
        }
        token = jwt.encode(token_payload, app.config['JWT_SECRET_KEY'], algorithm="HS256")
        
        app.logger.info(f"User '{user_data['username']}' logged in successfully.")
        return jsonify({
            "message": "Login successful", 
            "token": token,
            "username": user_data['username'],
            "tier": user_data.get('tier', 'free')
        }), 200

    except Exception as e:
        app.logger.error(f"Error during login for '{username_or_email}': {e}")
        return jsonify({"error": f"Login failed: {e}"}), 500

# app.py
# ... (other imports and setup remain the same) ...
# Ensure db and GEMINI_API_KEY are checked at the beginning of relevant routes

# app.py
# ... (other imports and setup remain the same) ...

@app.route('/generate_explanation', methods=['POST'])
@token_required
def generate_explanation():
    if not db:
        return jsonify({"error": "Database not initialized. Cannot process."}), 500
    if not GEMINI_API_KEY:
        return jsonify({"error": "Gemini API key not configured."}), 500

    user_id = request.current_user_jwt.get('username')
    data = request.get_json()
    question = data.get('question')
    mode = data.get('mode', 'explain').lower()
    force_refresh = data.get('force_refresh', False)

    if not question:
        return jsonify({"error": "No question provided"}), 400

    sanitized_word_id = sanitize_word_for_id(question)
    word_doc_ref = db.collection('users').document(user_id).collection('word_history').document(sanitized_word_id)
    
    # Fetch current cache from DB once at the beginning
    current_db_cache_for_word = {}
    word_doc_snapshot = word_doc_ref.get()
    is_new_word_entry = not word_doc_snapshot.exists
    
    if word_doc_snapshot.exists:
        word_data_from_db = word_doc_snapshot.to_dict()
        current_db_cache_for_word = word_data_from_db.get('generated_content_cache', {})
        if not isinstance(current_db_cache_for_word, dict):
            current_db_cache_for_word = {}

    # 1. Check cache if not forcing refresh
    if not force_refresh:
        cached_content_for_mode = current_db_cache_for_word.get(mode)
        if cached_content_for_mode:
            app.logger.info(f"Returning cached '{mode}' for '{question}' for user '{user_id}'.")
            # Update last_explored_at for this interaction, but don't modify other cache fields
            word_doc_ref.set({'last_explored_at': firestore.SERVER_TIMESTAMP}, merge=True)
            return jsonify({
                "question": question,
                "mode": mode,
                "content": cached_content_for_mode,
                "full_cache": current_db_cache_for_word, # Send existing full cache from DB
                "source": "cache"
            }), 200

    # Handle placeholder modes explicitly to prevent Gemini calls for them
    if mode in ["image", "deep"]:
        placeholder_content = ""
        if mode == "image": placeholder_content = f"Image generation feature coming soon for '{question}'."
        if mode == "deep": placeholder_content = f"In-depth explanation feature coming soon for '{question}'."
        
        # If force_refresh, we might "log" it as refreshed, but still return placeholder
        if force_refresh:
            placeholder_content += " (Placeholder refreshed)"
            app.logger.info(f"Placeholder for '{mode}' for '{question}' (user '{user_id}') refreshed.")
        
        # Update the local cache copy that will be saved
        # This ensures if user refreshes 'image', it's "cached" as the placeholder
        updated_cache_for_response = dict(current_db_cache_for_word) # Make a copy
        updated_cache_for_response[mode] = placeholder_content

        # Save this placeholder to DB if it's a forced refresh or if it's new for this mode
        if force_refresh or mode not in current_db_cache_for_word:
            db_update_payload = {
                'word': question, 'sanitized_word': sanitized_word_id,
                'last_explored_at': firestore.SERVER_TIMESTAMP,
                'generated_content_cache': updated_cache_for_response,
                'modes_generated': firestore.ArrayUnion([mode])
            }
            if is_new_word_entry:
                db_update_payload['first_explored_at'] = firestore.SERVER_TIMESTAMP
                db_update_payload['is_favorite'] = False
            word_doc_ref.set(db_update_payload, merge=True)
        
        return jsonify({
            "question": question, "mode": mode, "content": placeholder_content,
            "full_cache": updated_cache_for_response # Return the cache including this placeholder
        }), 200

    # 2. If not cached (for this mode) or force_refresh is true, proceed to generate for valid AI modes
    prompt_text = ""
    if mode == "explain":
        prompt_text = f"Explain the concept '{question}' in a clear, concise, and engaging way for a general audience. Identify up to 3 important keywords within your explanation and wrap them in <click>keyword</click> tags. For example, if explaining 'photosynthesis', you might say 'Plants use <click>chlorophyll</click> to convert <click>sunlight</click> into energy through a process called <click>photosynthesis</click>.' Keep the explanation to about 2-4 sentences."
    elif mode == "fact":
        prompt_text = f"Provide one interesting and concise fact about '{question}'. The fact should be easily understandable."
    elif mode == "quiz":
        prompt_text = f"Create a simple multiple-choice quiz question about '{question}'. Provide the question, three incorrect options (A, B, C), and one correct option (D). Format it as: Question: [Your question]? A) [Option A] B) [Option B] C) [Option C] D) [Option D] Correct: D"
    else:
        app.logger.warning(f"Attempt to generate for unexpected mode '{mode}' for question '{question}'.")
        return jsonify({"error": f"Cannot generate content for mode: {mode}", "full_cache": current_db_cache_for_word }), 400

    try:
        headers = {'Content-Type': 'application/json'}
        payload = {
            "contents": [{"parts": [{"text": prompt_text}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 300}
        }
        api_url = f"{GEMINI_API_URL_BASE}{GEMINI_MODEL}?key={GEMINI_API_KEY}"
        
        response_gemini = requests.post(api_url, headers=headers, json=payload)
        response_gemini.raise_for_status()
        response_data = response_gemini.json()
        
        generated_text = "Error: No content could be generated."
        if response_data.get("candidates") and isinstance(response_data["candidates"], list) and len(response_data["candidates"]) > 0 and \
           response_data["candidates"][0].get("content") and isinstance(response_data["candidates"][0]["content"].get("parts"), list) and \
           len(response_data["candidates"][0]["content"]["parts"]) > 0:
            generated_text = response_data["candidates"][0]["content"]["parts"][0].get("text", "Error extracting text.")
        
        # Prepare the cache to be saved and returned
        # Start with the cache fetched at the beginning or an empty dict
        cache_to_save_and_return = dict(current_db_cache_for_word) # Make a copy
        cache_to_save_and_return[mode] = generated_text # Add/update the newly generated content

        db_update_payload = {
            'word': question,
            'sanitized_word': sanitized_word_id,
            'last_explored_at': firestore.SERVER_TIMESTAMP,
            'generated_content_cache': cache_to_save_and_return, # Save the updated full cache
            'modes_generated': firestore.ArrayUnion([mode])
        }
        if mode == "explain": # Only add explicit_connections if 'explain' mode was generated
            highlighted_words = re.findall(r'<click>(.*?)</click>', generated_text)
            db_update_payload['explicit_connections'] = list(set(highlighted_words))
        
        if is_new_word_entry: # If this is the first time any content is generated for this word
            db_update_payload['first_explored_at'] = firestore.SERVER_TIMESTAMP
            db_update_payload['is_favorite'] = False
            # If explicit_connections is not set for a new word in explain mode, initialize it
            if mode == "explain" and 'explicit_connections' not in db_update_payload:
                 db_update_payload['explicit_connections'] = []


        word_doc_ref.set(db_update_payload, merge=True)

        app.logger.info(f"Generated (and cached) '{mode}' for '{question}' for user '{user_id}'.")
        return jsonify({
            "question": question,
            "mode": mode,
            "content": generated_text, # The specific content for the requested mode
            "full_cache": cache_to_save_and_return, # The complete cache for the word after this operation
            "source": "generated"
        }), 200

    except requests.exceptions.RequestException as e:
        app.logger.error(f"Gemini API request failed for '{question}', mode '{mode}', user '{user_id}': {e}")
        return jsonify({"error": f"AI content generation failed: {e}", "full_cache": current_db_cache_for_word}), 503
    except Exception as e:
        app.logger.error(f"Error in generate_explanation for '{question}', mode '{mode}', user '{user_id}': {e}")
        return jsonify({"error": f"An unexpected error occurred: {e}", "full_cache": current_db_cache_for_word}), 500

# ... (rest of app.py)


    # ... (exception handling) ...

    # --- AI Content Generation (Explain, Fact, Quiz) ---
    prompt_text = ""
    if mode == "explain":
        prompt_text = f"Explain the concept '{question}' in a clear, concise, and engaging way for a general audience. Identify up to 3 important keywords within your explanation and wrap them in <click>keyword</click> tags. For example, if explaining 'photosynthesis', you might say 'Plants use <click>chlorophyll</click> to convert <click>sunlight</click> into energy through a process called <click>photosynthesis</click>.' Keep the explanation to about 2-4 sentences."
    elif mode == "fact":
        prompt_text = f"Provide one interesting and concise fact about '{question}'. The fact should be easily understandable."
    elif mode == "quiz":
        prompt_text = f"Create a simple multiple-choice quiz question about '{question}'. Provide the question, three incorrect options (A, B, C), and one correct option (D). Format it as: Question: [Your question]? A) [Option A] B) [Option B] C) [Option C] D) [Option D] Correct: D"
    else:
        return jsonify({"error": "Invalid content mode"}), 400

    try:
        headers = {'Content-Type': 'application/json'}
        payload = {
            "contents": [{"parts": [{"text": prompt_text}]}],
            "generationConfig": {
                "temperature": 0.7, # Adjust as needed
                "maxOutputTokens": 300 # Adjust as needed
            }
        }
        api_url = f"{GEMINI_API_URL_BASE}{GEMINI_MODEL}?key={GEMINI_API_KEY}"
        
        response = requests.post(api_url, headers=headers, json=payload)
        response.raise_for_status() # Raise an exception for HTTP errors
        
        response_data = response.json()
        
        generated_text = "No content generated."
        if response_data.get("candidates") and response_data["candidates"][0].get("content") and response_data["candidates"][0]["content"].get("parts"):
            generated_text = response_data["candidates"][0]["content"]["parts"][0].get("text", "Error extracting text.")
        
        # --- Log word exploration to Firestore ---
        sanitized_word_id = sanitize_word_for_id(question)
        word_doc_ref = db.collection('users').document(user_id).collection('word_history').document(sanitized_word_id)
        
        word_data_update = {
            'word': question,
            'sanitized_word': sanitized_word_id,
            'last_explored_at': firestore.SERVER_TIMESTAMP,
            f'generated_content_cache.{mode}': generated_text, # Cache the newly generated content
            'modes_generated': firestore.ArrayUnion([mode]) # Add current mode to list of generated modes
        }
        
        # If it's an 'explain' mode, also store explicit connections
        if mode == "explain":
            # Extract words from <click>tags</click>
            highlighted_words = re.findall(r'<click>(.*?)</click>', generated_text)
            word_data_update['explicit_connections'] = list(set(highlighted_words)) # Store unique highlighted words

        # Use set with merge=True to create or update the document
        word_doc_ref.set(word_data_update, merge=True) 
        
        # If the document is being created for the first time, set first_explored_at and default is_favorite
        word_doc_snapshot = word_doc_ref.get()
        if not word_doc_snapshot.to_dict().get('first_explored_at'):
            word_doc_ref.set({
                'first_explored_at': firestore.SERVER_TIMESTAMP,
                'is_favorite': False # Default to not favorite
            }, merge=True)

        app.logger.info(f"Generated '{mode}' for '{question}' for user '{user_id}'.")
        return jsonify({
            "question": question,
            "mode": mode,
            "content": generated_text
        }), 200

    except requests.exceptions.RequestException as e:
        app.logger.error(f"Gemini API request failed: {e}")
        return jsonify({"error": f"AI content generation failed: {e}"}), 503 # Service Unavailable
    except Exception as e:
        app.logger.error(f"Error in generate_explanation for '{question}', mode '{mode}', user '{user_id}': {e}")
        return jsonify({"error": f"An unexpected error occurred: {e}"}), 500


@app.route('/toggle_favorite', methods=['POST'])
@token_required
def toggle_favorite():
    if not db:
        return jsonify({"error": "Database not initialized."}), 500
        
    user_id = request.current_user_jwt.get('username')
    data = request.get_json()
    word_to_toggle = data.get('word')
    is_favorite = data.get('is_favorite') # This will be the new desired state (true or false)

    if word_to_toggle is None or is_favorite is None:
        return jsonify({"error": "Missing 'word' or 'is_favorite' status"}), 400
    if not isinstance(is_favorite, bool):
        return jsonify({"error": "'is_favorite' must be a boolean"}), 400

    try:
        sanitized_word_id = sanitize_word_for_id(word_to_toggle)
        word_doc_ref = db.collection('users').document(user_id).collection('word_history').document(sanitized_word_id)
        
        word_doc = word_doc_ref.get()
        if not word_doc.exists:
            # If word doesn't exist in history, we can't favorite it this way.
            # Optionally, create it, but current flow assumes it's explored first.
            return jsonify({"error": "Word not found in history. Explore it first to favorite."}), 404

        word_doc_ref.update({'is_favorite': is_favorite})
        
        action = "favorited" if is_favorite else "unfavorited"
        app.logger.info(f"Word '{word_to_toggle}' {action} by user '{user_id}'.")
        return jsonify({"message": f"Word '{word_to_toggle}' status updated to {is_favorite}."}), 200
    except Exception as e:
        app.logger.error(f"Error toggling favorite for word '{word_to_toggle}', user '{user_id}': {e}")
        return jsonify({"error": f"Failed to toggle favorite: {e}"}), 500

@app.route('/profile', methods=['GET'])
@token_required
def get_profile():
    if not db:
        return jsonify({"error": "Database not initialized. Cannot fetch profile."}), 500

    user_id = request.current_user_jwt.get('username')
    
    try:
        user_doc_ref = db.collection('users').document(user_id)
        user_doc_snapshot = user_doc_ref.get()

        if not user_doc_snapshot.exists:
            return jsonify({"error": "User not found"}), 404
        
        user_data_main = user_doc_snapshot.to_dict()

        # Fetch explored words and favorite words
        explored_words = []
        favorite_words = []
        word_history_ref = user_doc_ref.collection('word_history')
        # Order by last_explored_at to get most recent first
        word_docs_query = word_history_ref.order_by('last_explored_at', direction=firestore.Query.DESCENDING)
        
        for doc in word_docs_query.stream():
            data = doc.to_dict()
            last_explored_dt = data.get('last_explored_at')
            # Convert Firestore timestamp to ISO string if it's a datetime object
            last_explored_str = last_explored_dt.isoformat() if isinstance(last_explored_dt, datetime) else str(last_explored_dt)
            
            # Ensure cached content is a dict, default to empty if not present or not a dict
            cached_content = data.get('generated_content_cache', {})
            if not isinstance(cached_content, dict):
                cached_content = {}

            display_word = {
                "id": doc.id, # Sanitized word ID
                "word": data.get('word'), # Original word
                "is_favorite": data.get('is_favorite', False),
                "last_explored_at": last_explored_str,
                "cached_explain_content": cached_content.get('explain'), # Get specific cached explain content
                "explicit_connections": data.get('explicit_connections', []),
                "modes_generated": data.get('modes_generated', [])
            }
            explored_words.append(display_word)
            if display_word["is_favorite"]:
                favorite_words.append(display_word) # Favorite words will be inherently sorted by last_explored_at

        # --- New: Fetch Streaks ---
        streaks_history = []
        streaks_collection_ref = user_doc_ref.collection('streaks')
        # Order by 'completed_at' in descending order to get the latest streaks first
        # This query might require a composite index in Firestore.
        # Firestore will provide an error message with a link to create it if needed.
        streak_docs_query = streaks_collection_ref.order_by('completed_at', direction=firestore.Query.DESCENDING)
        
        for streak_doc in streak_docs_query.stream():
            streak_data = streak_doc.to_dict()
            completed_at_dt = streak_data.get('completed_at')
            # Convert Firestore timestamp to ISO string
            completed_at_str = completed_at_dt.isoformat() if isinstance(completed_at_dt, datetime) else str(completed_at_dt)
            
            streaks_history.append({
                "id": streak_doc.id,
                "words": streak_data.get('words', []),
                "score": streak_data.get('score', 0),
                "completed_at": completed_at_str
            })
        # --- End New: Fetch Streaks ---
        
        return jsonify({
            "username": user_data_main.get('username'), 
            "tier": user_data_main.get('tier', 'free'),       
            "explored_words_count": len(explored_words),
            "explored_words_list": explored_words,
            "favorite_words_list": favorite_words,
            "streak_history": streaks_history # Add streak history to the response
        }), 200
        
    except Exception as e:
        app.logger.error(f"Error fetching profile for user '{user_id}': {e}")
        # Check if the error message contains "index" to guide user
        if "index" in str(e).lower() and "firestore" in str(e).lower(): # Be more specific for Firestore index errors
            app.logger.error(f"Potential Firestore index missing for profile query: {e}")
            return jsonify({"error": f"Profile fetch failed. A Firestore index might be required. Please check backend logs for details and a link to create the index. Error: {e}"}), 500
        return jsonify({"error": f"Profile fetch failed: {e}"}), 500


@app.route('/save_streak', methods=['POST'])
@token_required
def save_streak():
    if not db:
        return jsonify({"error": "Database not initialized. Cannot save streak."}), 500

    user_id = request.current_user_jwt.get('username')
    data = request.get_json()
    streak_words = data.get('words')
    streak_score = data.get('score')

    # Validate input as per report: "streak is only considered valid and recorded if it contains at least two words"
    if not isinstance(streak_words, list) or not all(isinstance(word, str) for word in streak_words) or len(streak_words) < 2 :
        return jsonify({"error": "Invalid 'words' format or insufficient words for a streak (min 2)."}), 400
    if not isinstance(streak_score, int) or streak_score < 2:
        return jsonify({"error": "Invalid 'score' format or insufficient score for a streak (min 2)."}), 400
    
    try:
        user_ref = db.collection('users').document(user_id)
        streaks_collection_ref = user_ref.collection('streaks')
        
        # Add a new streak document with an auto-generated ID
        streak_doc_ref = streaks_collection_ref.document() 
        streak_doc_ref.set({
            'words': streak_words,
            'score': streak_score,
            'completed_at': firestore.SERVER_TIMESTAMP  # Automatically set server-side timestamp
        })
        
        app.logger.info(f"Streak saved for user '{user_id}', streak ID: {streak_doc_ref.id}, score: {streak_score}, words: {len(streak_words)}")
        return jsonify({"message": "Streak saved successfully", "streak_id": streak_doc_ref.id}), 201
        
    except Exception as e:
        app.logger.error(f"Error saving streak for user '{user_id}': {e}")
        return jsonify({"error": f"Failed to save streak: {e}"}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001)) # Render typically sets PORT env var
    # For local development, use Flask's dev server. 
    # The FLASK_DEBUG env var (or app.debug = True) will control debug mode.
    # Gunicorn is typically used in production (specified in Procfile for Render).
    is_debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=is_debug_mode)
