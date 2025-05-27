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
# import requests # For Gemini API calls (if you were using requests directly)
import google.generativeai as genai # Using the official SDK
import jwt # PyJWT for encoding/decoding
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps # For JWT decorator
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

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
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'fallback_secret_key_for_dev_only_change_me')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)

# --- Firebase Initialization ---
service_account_key_base64 = os.getenv('FIREBASE_SERVICE_ACCOUNT_KEY_BASE64')
db = None # Firestore database client

if service_account_key_base64:
    try:
        decoded_key_bytes = base64.b64decode(service_account_key_base64)
        decoded_key_str = decoded_key_bytes.decode('utf-8')
        service_account_info = json.loads(decoded_key_str)
        
        # Check if Firebase app is already initialized
        if not firebase_admin._apps:
            cred = credentials.Certificate(service_account_info)
            firebase_admin.initialize_app(cred)
            app.logger.info("Firebase Admin SDK initialized successfully from Base64.")
        else:
            app.logger.info("Firebase Admin SDK already initialized.")
            
        db = firestore.client()
    except Exception as e:
        app.logger.error(f"Failed to initialize Firebase Admin SDK from Base64: {e}")
        db = None # Ensure db is None if initialization fails
else:
    app.logger.warning("FIREBASE_SERVICE_ACCOUNT_KEY_BASE64 not found. Firebase Admin SDK not initialized.")


# --- Gemini API Initialization ---
gemini_api_key = os.getenv('GEMINI_API_KEY')
if gemini_api_key:
    try:
        genai.configure(api_key=gemini_api_key)
        # model = genai.GenerativeModel('gemini-1.5-flash-latest') # Or your preferred model
        app.logger.info("Google Gemini API configured successfully.")
    except Exception as e:
        app.logger.error(f"Failed to configure Google Gemini API: {e}")
else:
    app.logger.warning("GEMINI_API_KEY not found. Google Gemini API not configured.")


# --- Rate Limiting ---
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://", # Use "redis://localhost:6379" or other persistent storage for production
    # strategy="fixed-window" # or "moving-window"
)


# --- Helper Functions ---
def sanitize_word_for_id(word: str) -> str:
    """Sanitizes a word to be used as a Firestore document ID."""
    if not isinstance(word, str):
        return "invalid_input"
    sanitized = word.lower()
    sanitized = re.sub(r'\s+', '_', sanitized)  # Replace spaces with underscores
    sanitized = re.sub(r'[^a-z0-9_]', '', sanitized)  # Remove non-alphanumeric characters (except underscore)
    return sanitized if sanitized else "empty_word"

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]
            except IndexError:
                return jsonify({"error": "Bearer token malformed"}), 401

        if not token:
            return jsonify({"error": "Token is missing"}), 401

        try:
            # Add leeway for clock skew issues if necessary
            data = jwt.decode(token, app.config['JWT_SECRET_KEY'], algorithms=['HS256'], leeway=timedelta(seconds=30))
            current_user_id = data['user_id']
            # You can also pass the user_id or full user data to the route if needed
            # For example, by adding it to flask.g or as a parameter
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token has expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Token is invalid"}), 401
        except Exception as e:
            app.logger.error(f"Token validation error: {e}")
            return jsonify({"error": "Token validation failed"}), 401
            
        return f(current_user_id, *args, **kwargs) # Pass user_id to the decorated function
    return decorated


# --- Routes ---
@app.route('/')
def home():
    return "Tiny Tutor Backend is running!"

@app.route('/signup', methods=['POST'])
@limiter.limit("5 per hour")
def signup_user():
    if not db: return jsonify({"error": "Database not configured"}), 500
    data = request.get_json()
    if not data:
        return jsonify({"error": "No input data provided"}), 400

    username = data.get('username', '').strip()
    email = data.get('email', '').strip().lower() # Emails stored lowercase
    password = data.get('password', '') # Passwords are not stripped by default, hash will take care of it

    if not username or not email or not password:
        return jsonify({"error": "Username, email, and password are required"}), 400
    if len(username) < 3 or len(username) > 30:
        return jsonify({"error": "Username must be between 3 and 30 characters"}), 400
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        return jsonify({"error": "Username can only contain letters, numbers, and underscores"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters long"}), 400
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return jsonify({"error": "Invalid email format"}), 400

    try:
        users_ref = db.collection('users')
        # Check if username exists (case-insensitive for username_lowercase)
        existing_user_username = users_ref.where('username_lowercase', '==', username.lower()).limit(1).stream()
        if len(list(existing_user_username)) > 0:
            return jsonify({"error": "Username already exists"}), 409
        # Check if email exists
        existing_user_email = users_ref.where('email', '==', email).limit(1).stream()
        if len(list(existing_user_email)) > 0:
            return jsonify({"error": "Email already registered"}), 409

        password_hash = generate_password_hash(password)
        user_doc_ref = users_ref.document()
        user_doc_ref.set({
            'username': username,
            'username_lowercase': username.lower(), # For case-insensitive username checks
            'email': email,
            'password_hash': password_hash,
            'tier': 'standard', # Default tier
            'created_at': firestore.SERVER_TIMESTAMP
        })
        app.logger.info(f"User '{username}' signed up successfully with ID: {user_doc_ref.id}")
        return jsonify({"message": "User created successfully. Please login."}), 201
    except Exception as e:
        app.logger.error(f"Error during signup for {username}: {e}")
        return jsonify({"error": f"Signup failed due to an internal error: {e}"}), 500


@app.route('/login', methods=['POST'])
@limiter.limit("10 per minute")
def login_user():
    if not db: return jsonify({"error": "Database not configured"}), 500
    
    app.logger.info("--- LOGIN ATTEMPT START ---") # START LOG
    data = request.get_json()

    if not data:
        app.logger.error("Login attempt with NO JSON DATA in request body.")
        return jsonify({"error": "No input data provided"}), 400
    
    app.logger.info(f"Raw JSON data received for login: {data}") # LOG RAW DATA

    identifier_raw = data.get('email_or_username') # Get raw value first
    password_raw = data.get('password') # Get raw value first

    app.logger.info(f"Raw identifier from payload: '{identifier_raw}' (type: {type(identifier_raw)})")
    app.logger.info(f"Raw password from payload: '{password_raw}' (type: {type(password_raw)})")

    identifier = str(identifier_raw).strip() if identifier_raw is not None else ''
    password = str(password_raw) if password_raw is not None else '' # Don't strip password yet, hash handles it

    app.logger.info(f"Processed identifier: '{identifier}'")
    app.logger.info(f"Processed password (is empty?): {not bool(password)}")


    if not identifier or not password:
        app.logger.warning(f"Login validation FAILED: Missing identifier or password. Identifier_val: '{identifier}', Password_empty: {not bool(password)}")
        return jsonify({"error": "Missing username/email or password"}), 400
    
    app.logger.info("Login validation PASSED: Identifier and password are present.")

    is_email = '@' in identifier
    user_doc = None
    user_ref = db.collection('users')

    try:
        if is_email:
            app.logger.info(f"Attempting login with email: {identifier.lower()}")
            query = user_ref.where('email', '==', identifier.lower()).limit(1)
        else:
            app.logger.info(f"Attempting login with username: {identifier.lower()}")
            query = user_ref.where('username_lowercase', '==', identifier.lower()).limit(1)
        
        docs = list(query.stream()) # Execute query and convert to list
        
        if not docs:
            app.logger.warning(f"Login failed: User not found for identifier '{identifier}'")
            return jsonify({"error": "Invalid credentials"}), 401 # User not found
        
        user_doc = docs[0]
        user_data = user_doc.to_dict()
        
        if not user_data or 'password_hash' not in user_data:
            app.logger.error(f"Login error: User data or password hash missing for user ID '{user_doc.id}'")
            return jsonify({"error": "User account data incomplete."}), 500

        if not check_password_hash(user_data['password_hash'], password): # Use password_raw if you don't want frontend to trim
            app.logger.warning(f"Login failed: Password mismatch for user '{user_data.get('username')}'")
            return jsonify({"error": "Invalid credentials"}), 401 # Password mismatch

        token_payload = {
            'user_id': user_doc.id,
            'username': user_data.get('username'),
            'email': user_data.get('email'),
            'tier': user_data.get('tier', 'standard'),
            'exp': datetime.now(timezone.utc) + app.config['JWT_ACCESS_TOKEN_EXPIRES']
        }
        access_token = jwt.encode(token_payload, app.config['JWT_SECRET_KEY'], algorithm='HS256')
        
        app.logger.info(f"User '{user_data.get('username')}' logged in successfully. --- LOGIN ATTEMPT END ---")
        return jsonify({
            "message": "Login successful", 
            "access_token": access_token,
            "user": {
                "username": user_data.get('username'),
                "email": user_data.get('email'),
                "tier": user_data.get('tier', 'standard')
            }
        }), 200

    except Exception as e:
        app.logger.error(f"Login general error for identifier '{identifier}': {e}", exc_info=True)
        return jsonify({"error": "Login failed due to an internal error."}), 500


# ... (rest of your app.py, including /generate_explanation, /profile, etc.)
# Ensure all other routes are present here from your original app.py

@app.route('/generate_explanation', methods=['POST'])
@token_required
@limiter.limit("60/hour") # Example: limit content generation
def generate_explanation_route(current_user_id):
    if not db: return jsonify({"error": "Database not configured"}), 500
    if not gemini_api_key: return jsonify({"error": "AI service not configured"}), 500

    data = request.get_json()
    if not data: return jsonify({"error": "No input data provided"}), 400

    word = data.get('word', '').strip()
    mode = data.get('mode', 'explain').strip().lower()
    force_refresh = data.get('refresh_cache', False)

    if not word: return jsonify({"error": "Word/concept is required"}), 400
    if mode not in ['explain', 'fact', 'quiz', 'image', 'deep_dive']:
        return jsonify({"error": "Invalid content mode requested"}), 400

    sanitized_word_id = sanitize_word_for_id(word)
    user_word_history_ref = db.collection('users').document(current_user_id).collection('word_history').document(sanitized_word_id)

    try:
        word_doc = user_word_history_ref.get()
        cached_content = {}
        is_favorite_status = False
        quiz_progress_data = []
        modes_already_generated = []

        if word_doc.exists:
            word_data = word_doc.to_dict()
            cached_content = word_data.get('generated_content_cache', {})
            is_favorite_status = word_data.get('is_favorite', False)
            quiz_progress_data = word_data.get('quiz_progress', [])
            modes_already_generated = word_data.get('modes_generated', [])
            
            # If content for the requested mode exists and no refresh is forced, return cached
            if mode in cached_content and not force_refresh:
                app.logger.info(f"Serving cached '{mode}' for '{word}' for user '{current_user_id}'")
                # Update last_explored_at timestamp without regenerating
                user_word_history_ref.set({'last_explored_at': firestore.SERVER_TIMESTAMP, 'word': word}, merge=True)
                
                return jsonify({
                    "word": word,
                    mode: cached_content[mode],
                    "source": "cache",
                    "is_favorite": is_favorite_status,
                    "full_cache": cached_content, # Send the whole cache
                    "quiz_progress": quiz_progress_data,
                    "modes_generated": modes_already_generated
                }), 200

        # Content not in cache or refresh forced, generate it
        app.logger.info(f"Generating '{mode}' for '{word}' for user '{current_user_id}' (Force refresh: {force_refresh})")
        
        generated_text_content = None
        prompt = ""
        if mode == 'explain':
            prompt = f"Explain the concept of '{word}' in 2 concise sentences with words or sub-topics that could extend the learning. If relevant, identify up to 2 key words or sub-topics within your explanation that can progress the concept along the learning curve to deepen the understanding and wrap them in <click>tags</click> like this: <click>sub-topic</click>."
        elif mode == 'fact':
            prompt = f"Tell me one very interesting and concise fun fact about '{word}'."
        elif mode == 'quiz':
            # For quiz, Gemini should return up to 3 questions, each clearly structured.
            # The backend will then split them if Gemini doesn't provide an array directly.
            prompt = f"Generate a set of up to 3 distinct multiple-choice quiz questions about '{word}'. For each question, provide the question, 4 options (A, B, C, D), and clearly indicate the correct answer (e.g., 'Correct Answer: A'). Separate each complete question block (question, options, answer) with '---QUIZ_SEPARATOR---'."
        elif mode == 'image': # Placeholder
            generated_text_content = f"Placeholder image description for {word}. Actual image generation to be implemented."
        elif mode == 'deep_dive': # Placeholder
            generated_text_content = f"Placeholder for a deep dive into {word}. More detailed content to come."

        if mode in ['explain', 'fact', 'quiz'] and prompt:
            try:
                gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')
                response = gemini_model.generate_content(prompt)
                generated_text_content = response.text
                if mode == 'quiz': # Special handling for quiz
                    # Split questions if Gemini returns them as a single string
                    quiz_questions_array = [q.strip() for q in generated_text_content.split('---QUIZ_SEPARATOR---') if q.strip()]
                    if not quiz_questions_array: # If separator fails, assume single block or error
                        quiz_questions_array = [generated_text_content] if generated_text_content.strip() else []
                    cached_content[mode] = quiz_questions_array # Store as array
                else:
                    cached_content[mode] = generated_text_content

            except Exception as e:
                app.logger.error(f"Gemini API error for '{word}', mode '{mode}': {e}")
                return jsonify({"error": f"AI content generation failed: {e}"}), 500
        elif generated_text_content: # For placeholder modes like image/deep_dive
             cached_content[mode] = generated_text_content


        # Update Firestore
        if mode not in modes_already_generated:
            modes_already_generated.append(mode)

        word_history_payload = {
            'word': word,
            'last_explored_at': firestore.SERVER_TIMESTAMP,
            'generated_content_cache': cached_content,
            'is_favorite': is_favorite_status, # Preserve existing favorite status
            'modes_generated': modes_already_generated
        }
        if not word_doc.exists: # First time exploring this word
            word_history_payload['first_explored_at'] = firestore.SERVER_TIMESTAMP
            word_history_payload['is_favorite'] = False # Default to not favorite
            word_history_payload['quiz_progress'] = [] # Initialize quiz progress

        user_word_history_ref.set(word_history_payload, merge=True)
        
        app.logger.info(f"Successfully generated and cached '{mode}' for '{word}' for user '{current_user_id}'")
        return jsonify({
            "word": word,
            mode: cached_content.get(mode), # Return the newly generated/updated content for the mode
            "source": "generated",
            "is_favorite": word_history_payload.get('is_favorite', False),
            "full_cache": cached_content,
            "quiz_progress": quiz_progress_data if word_doc.exists else [], # Return existing or new empty progress
            "modes_generated": modes_already_generated
        }), 200

    except Exception as e:
        app.logger.error(f"Error in /generate_explanation for '{word}', user '{current_user_id}': {e}", exc_info=True)
        return jsonify({"error": f"An internal error occurred: {e}"}), 500


@app.route('/profile', methods=['GET'])
@token_required
def get_user_profile(current_user_id):
    if not db: return jsonify({"error": "Database not configured"}), 500
    try:
        user_doc_ref = db.collection('users').document(current_user_id)
        user_doc = user_doc_ref.get()
        if not user_doc.exists:
            return jsonify({"error": "User not found"}), 404
        
        user_data = user_doc.to_dict()
        
        # Fetch word history
        word_history_ref = user_doc_ref.collection('word_history').order_by('last_explored_at', direction=firestore.Query.DESCENDING).stream()
        explored_words_list = []
        favorite_words_list = []
        for doc in word_history_ref:
            word_entry = doc.to_dict()
            entry_data = {
                "id": doc.id, # sanitized_word_id
                "word": word_entry.get("word"),
                "is_favorite": word_entry.get("is_favorite", False),
                "last_explored_at": word_entry.get("last_explored_at").isoformat() if word_entry.get("last_explored_at") else None,
                "modes_generated": word_entry.get("modes_generated", []),
                # Optionally include generated_content_cache if needed on profile page, but can be large
                # "generated_content_cache": word_entry.get("generated_content_cache", {}) 
            }
            explored_words_list.append(entry_data)
            if entry_data["is_favorite"]:
                favorite_words_list.append(entry_data)

        # Fetch streak history
        streak_history_ref = user_doc_ref.collection('streaks').order_by('completed_at', direction=firestore.Query.DESCENDING).limit(50).stream() # Limit to last 50
        streak_history_list = []
        for doc in streak_history_ref:
            streak_data = doc.to_dict()
            streak_history_list.append({
                "id": doc.id,
                "words": streak_data.get("words", []),
                "score": streak_data.get("score", 0),
                "completed_at": streak_data.get("completed_at").isoformat() if streak_data.get("completed_at") else None
            })
            
        profile_response = {
            "username": user_data.get("username"),
            "email": user_data.get("email"),
            "tier": user_data.get("tier", "standard"),
            "total_words_explored": len(explored_words_list),
            "explored_words": explored_words_list,
            "favorite_words": favorite_words_list,
            "streak_history": streak_history_list
        }
        return jsonify(profile_response), 200
        
    except Exception as e:
        app.logger.error(f"Error fetching profile for user '{current_user_id}': {e}", exc_info=True)
        return jsonify({"error": f"Failed to fetch profile: {e}"}), 500


@app.route('/toggle_favorite', methods=['POST'])
@token_required
def toggle_favorite_word(current_user_id):
    if not db: return jsonify({"error": "Database not configured"}), 500
    data = request.get_json()
    if not data or 'word' not in data:
        return jsonify({"error": "Word is required"}), 400
    
    word_to_toggle = data['word'].strip()
    if not word_to_toggle:
        return jsonify({"error": "Word cannot be empty"}), 400
        
    sanitized_word_id = sanitize_word_for_id(word_to_toggle)
    word_ref = db.collection('users').document(current_user_id).collection('word_history').document(sanitized_word_id)
    
    try:
        word_doc = word_ref.get()
        if not word_doc.exists:
            # If word not in history, cannot favorite (or decide to add it first)
            return jsonify({"error": "Word not found in history, explore it first."}), 404 
            
        current_is_favorite = word_doc.to_dict().get('is_favorite', False)
        new_favorite_status = not current_is_favorite
        word_ref.update({'is_favorite': new_favorite_status, 'last_explored_at': firestore.SERVER_TIMESTAMP})
        
        app.logger.info(f"User '{current_user_id}' toggled favorite for '{word_to_toggle}' to {new_favorite_status}")
        return jsonify({"message": "Favorite status updated", "word": word_to_toggle, "is_favorite": new_favorite_status}), 200
    except Exception as e:
        app.logger.error(f"Error toggling favorite for '{word_to_toggle}', user '{current_user_id}': {e}", exc_info=True)
        return jsonify({"error": f"Failed to toggle favorite: {e}"}), 500


@app.route('/save_streak', methods=['POST'])
@token_required
def save_user_streak(current_user_id):
    if not db: return jsonify({"error": "Database not configured"}), 500
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided for streak."}), 400
        
    streak_words = data.get('words')
    streak_score = data.get('score')

    if not isinstance(streak_words, list) or not streak_words:
        return jsonify({"error": "Invalid 'words' list."}), 400
    if not all(isinstance(word, str) for word in streak_words):
        return jsonify({"error": "All items in 'words' must be strings."}), 400
    if not isinstance(streak_score, int) or streak_score < 2: # Streaks of score 1 are live, not saved
        return jsonify({"error": "Invalid 'score' format or insufficient score for a streak (min 2)."}), 400
    
    try:
        user_ref = db.collection('users').document(current_user_id)
        streaks_collection_ref = user_ref.collection('streaks')
        
        streak_doc_ref = streaks_collection_ref.document() 
        streak_doc_ref.set({
            'words': streak_words,
            'score': streak_score,
            'completed_at': firestore.SERVER_TIMESTAMP
        })
        
        app.logger.info(f"Streak saved for user '{current_user_id}', streak ID: {streak_doc_ref.id}, score: {streak_score}, words: {len(streak_words)}")
        return jsonify({"message": "Streak saved successfully", "streak_id": streak_doc_ref.id}), 201
        
    except Exception as e:
        app.logger.error(f"Error saving streak for user '{current_user_id}': {e}", exc_info=True)
        return jsonify({"error": f"Failed to save streak: {e}"}), 500

@app.route('/save_quiz_attempt', methods=['POST'])
@token_required
def save_quiz_attempt_route(current_user_id):
    if not db: return jsonify({"error": "Database not configured"}), 500
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    word = data.get('word', '').strip()
    question_index = data.get('question_index')
    selected_option_key = data.get('selected_option_key', '').strip()
    is_correct = data.get('is_correct')

    if not word or question_index is None or not selected_option_key or is_correct is None:
        return jsonify({"error": "Missing required fields (word, question_index, selected_option_key, is_correct)"}), 400
    if not isinstance(question_index, int) or question_index < 0:
        return jsonify({"error": "Invalid question_index"}), 400
    if not isinstance(is_correct, bool):
        return jsonify({"error": "is_correct must be a boolean"}), 400

    sanitized_word_id = sanitize_word_for_id(word)
    word_history_ref = db.collection('users').document(current_user_id).collection('word_history').document(sanitized_word_id)

    try:
        word_doc = word_history_ref.get()
        if not word_doc.exists:
            return jsonify({"error": "Word history not found. Explore the word first."}), 404

        quiz_progress = word_doc.to_dict().get('quiz_progress', [])
        
        # Check if an attempt for this question_index already exists
        attempt_exists = False
        for i, attempt in enumerate(quiz_progress):
            if attempt.get('question_index') == question_index:
                # Update existing attempt if necessary (e.g., if re-answering was allowed)
                # For now, let's assume we overwrite or just add if it's a new attempt system.
                # If strictly one attempt, this check should prevent duplicates or handle updates.
                # quiz_progress[i] = { ... } 
                app.logger.info(f"Updating existing quiz attempt for user {current_user_id}, word {word}, q_idx {question_index}")
                quiz_progress[i] = {
                    "question_index": question_index,
                    "selected_option_key": selected_option_key,
                    "is_correct": is_correct,
                    "timestamp": datetime.now(timezone.utc).isoformat() 
                }
                attempt_exists = True
                break
        
        if not attempt_exists:
            quiz_progress.append({
                "question_index": question_index,
                "selected_option_key": selected_option_key,
                "is_correct": is_correct,
                "timestamp": datetime.now(timezone.utc).isoformat() 
            })

        word_history_ref.update({"quiz_progress": quiz_progress, "last_explored_at": firestore.SERVER_TIMESTAMP})
        
        app.logger.info(f"Quiz attempt saved for user '{current_user_id}', word '{word}', q_idx {question_index}")
        return jsonify({"message": "Quiz attempt saved", "quiz_progress": quiz_progress}), 200

    except Exception as e:
        app.logger.error(f"Error saving quiz attempt for user '{current_user_id}', word '{word}': {e}", exc_info=True)
        return jsonify({"error": f"Failed to save quiz attempt: {e}"}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    # For production, Gunicorn is recommended and will be used by Render.
    # For local dev, app.run() is fine.
    # app.run(debug=True, host='0.0.0.0', port=port)
    # When deploying to Render, Render uses its own command (e.g., gunicorn app:app)
    # so this __main__ block might not be executed directly by Render.
    # However, it's good for local testing.
    # If run directly (e.g. python app.py), it will use Flask's dev server.
    app.run(host='0.0.0.0', port=port)

