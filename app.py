# app.py
from flask import Flask, request, jsonify, current_app # Ensure current_app is imported
from flask_cors import CORS
import os
import re
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
import json
import base64
import google.generativeai as genai
import jwt
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

load_dotenv()

app = Flask(__name__)

# --- IMPORTANT: Configure CORS ---
# This setup allows credentials and specific headers/methods.
# The order of middleware (CORS, Limiter, custom decorators) can sometimes matter.
# Generally, CORS should be applied early.
CORS(app, 
    resources={r"/*": {"origins": [
        "https://tiny-tutor-app-frontend.onrender.com",
        "http://localhost:5173", # For local development
        "http://127.0.0.1:5173"  # For local development
    ]}}, 
    supports_credentials=True,
    # Expose headers that your frontend might need to read from the response
    expose_headers=["Content-Type", "Authorization"], 
    # Allow headers that your frontend will send in the request
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"] 
)

app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'fallback_secret_key_for_dev_only_change_me')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)

# --- Firebase Initialization ---
service_account_key_base64 = os.getenv('FIREBASE_SERVICE_ACCOUNT_KEY_BASE64')
db = None
if service_account_key_base64:
    try:
        decoded_key_bytes = base64.b64decode(service_account_key_base64)
        decoded_key_str = decoded_key_bytes.decode('utf-8')
        service_account_info = json.loads(decoded_key_str)
        if not firebase_admin._apps:
            cred = credentials.Certificate(service_account_info)
            firebase_admin.initialize_app(cred)
            app.logger.info("Firebase Admin SDK initialized successfully from Base64.")
        else:
            app.logger.info("Firebase Admin SDK already initialized.")
        db = firestore.client()
    except Exception as e:
        app.logger.error(f"Failed to initialize Firebase Admin SDK from Base64: {e}")
        db = None
else:
    app.logger.warning("FIREBASE_SERVICE_ACCOUNT_KEY_BASE64 not found. Firebase Admin SDK not initialized.")

# --- Gemini API Initialization ---
gemini_api_key = os.getenv('GEMINI_API_KEY')
if gemini_api_key:
    try:
        genai.configure(api_key=gemini_api_key)
        app.logger.info("Google Gemini API configured successfully.")
    except Exception as e:
        app.logger.error(f"Failed to configure Google Gemini API: {e}")
else:
    app.logger.warning("GEMINI_API_KEY not found. Google Gemini API not configured.")

# --- Rate Limiting ---
# Initialize Limiter AFTER app is created but BEFORE routes that use it,
# or ensure it's correctly applied if routes are defined in blueprints.
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"], # General limits
    storage_uri="memory://", # Consider persistent storage for production
)

# --- Helper Functions ---
def sanitize_word_for_id(word: str) -> str:
    if not isinstance(word, str): return "invalid_input"
    sanitized = word.lower()
    sanitized = re.sub(r'\s+', '_', sanitized)
    sanitized = re.sub(r'[^a-z0-9_]', '', sanitized)
    return sanitized if sanitized else "empty_word"

# --- MODIFIED token_required DECORATOR ---
def token_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # CRITICAL: Handle OPTIONS (preflight) requests first.
        # These requests are sent by the browser to check CORS permissions
        # *before* the actual request (GET, POST, etc.) that carries the token.
        # OPTIONS requests do not (and should not) contain Authorization headers.
        if request.method == 'OPTIONS':
            app.logger.info(f"OPTIONS request received for: {request.path}, allowing through for CORS handling.")
            # Flask-CORS will add the necessary headers to this default response.
            # Returning a simple 200/204 response is key.
            response = current_app.make_default_options_response()
            return response

        # For non-OPTIONS requests, proceed with token validation
        token = None
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            try:
                token = auth_header.split(" ")[1]
            except IndexError:
                app.logger.warning(f"Malformed Bearer token for {request.path}.")
                return jsonify({"error": "Bearer token malformed"}), 401
        
        if not token:
            app.logger.warning(f"Token is missing for {request.method} request to {request.path}.")
            return jsonify({"error": "Token is missing"}), 401

        try:
            payload = jwt.decode(token, app.config['JWT_SECRET_KEY'], algorithms=['HS256'], leeway=timedelta(seconds=30))
            current_user_id = payload['user_id']
            # You could also add user_data to flask.g if needed in the route
            # from flask import g
            # g.current_user_id = current_user_id
        except jwt.ExpiredSignatureError:
            app.logger.warning(f"Expired token for {request.path}.")
            return jsonify({"error": "Token has expired"}), 401
        except jwt.InvalidTokenError:
            app.logger.warning(f"Invalid token for {request.path}.")
            return jsonify({"error": "Token is invalid"}), 401
        except Exception as e:
            app.logger.error(f"Token validation error for {request.path}: {e}")
            return jsonify({"error": "Token validation failed"}), 401
            
        return f(current_user_id, *args, **kwargs) # Pass current_user_id to the wrapped function
    return decorated_function


# --- Routes ---
@app.route('/')
def home():
    return "Tiny Tutor Backend is running!"

# No token needed for signup/login
@app.route('/signup', methods=['POST'])
@limiter.limit("5 per hour") # Apply specific rate limit
def signup_user():
    # ... (your existing signup logic - ensure it's complete) ...
    if not db: return jsonify({"error": "Database not configured"}), 500
    data = request.get_json()
    if not data: return jsonify({"error": "No input data provided"}), 400
    username = data.get('username', '').strip()
    email = data.get('email', '').strip().lower() 
    password = data.get('password', '') 
    if not username or not email or not password: return jsonify({"error": "Username, email, and password are required"}), 400
    # ... (rest of your validation and user creation logic) ...
    try:
        users_ref = db.collection('users')
        existing_user_username = users_ref.where('username_lowercase', '==', username.lower()).limit(1).stream()
        if len(list(existing_user_username)) > 0: return jsonify({"error": "Username already exists"}), 409
        existing_user_email = users_ref.where('email', '==', email).limit(1).stream()
        if len(list(existing_user_email)) > 0: return jsonify({"error": "Email already registered"}), 409
        password_hash = generate_password_hash(password)
        user_doc_ref = users_ref.document()
        user_doc_ref.set({
            'username': username, 'username_lowercase': username.lower(), 'email': email,
            'password_hash': password_hash, 'tier': 'standard', 'created_at': firestore.SERVER_TIMESTAMP
        })
        return jsonify({"message": "User created successfully. Please login."}), 201
    except Exception as e:
        app.logger.error(f"Error during signup for {username}: {e}")
        return jsonify({"error": f"Signup failed: {e}"}), 500


@app.route('/login', methods=['POST'])
@limiter.limit("10 per minute") # Apply specific rate limit
def login_user():
    # ... (your existing login logic - ensure it's complete) ...
    if not db: return jsonify({"error": "Database not configured"}), 500
    data = request.get_json()
    if not data: return jsonify({"error": "No input data provided"}), 400
    identifier = str(data.get('email_or_username', '')).strip()
    password = str(data.get('password', ''))
    if not identifier or not password: return jsonify({"error": "Missing username/email or password"}), 400
    # ... (rest of your user lookup and password check logic) ...
    try:
        is_email = '@' in identifier
        user_ref = db.collection('users')
        query = user_ref.where('email' if is_email else 'username_lowercase', '==', identifier.lower()).limit(1)
        docs = list(query.stream())
        if not docs: return jsonify({"error": "Invalid credentials"}), 401
        user_doc = docs[0]
        user_data = user_doc.to_dict()
        if not user_data or not check_password_hash(user_data.get('password_hash', ''), password):
            return jsonify({"error": "Invalid credentials"}), 401
        token_payload = {
            'user_id': user_doc.id, 'username': user_data.get('username'), 'email': user_data.get('email'),
            'tier': user_data.get('tier', 'standard'),
            'exp': datetime.now(timezone.utc) + app.config['JWT_ACCESS_TOKEN_EXPIRES']
        }
        access_token = jwt.encode(token_payload, app.config['JWT_SECRET_KEY'], algorithm='HS256')
        return jsonify({
            "message": "Login successful", "access_token": access_token,
            "user": {"username": user_data.get('username'), "email": user_data.get('email'), "tier": user_data.get('tier')}
        }), 200
    except Exception as e:
        app.logger.error(f"Login error for '{identifier}': {e}", exc_info=True)
        return jsonify({"error": "Login failed."}), 500

# Ensure OPTIONS is listed for methods on routes protected by @token_required
@app.route('/generate_explanation', methods=['POST', 'OPTIONS'])
@token_required
@limiter.limit("60/hour")
def generate_explanation_route(current_user_id):
    # ... (Your existing logic) ...
    # This route should now correctly handle OPTIONS requests due to the modified decorator
    if not db: return jsonify({"error": "Database not configured"}), 500
    if not gemini_api_key: return jsonify({"error": "AI service not configured"}), 500
    data = request.get_json()
    if not data: return jsonify({"error": "No input data provided"}), 400
    word = data.get('word', '').strip()
    mode = data.get('mode', 'explain').strip().lower()
    force_refresh = data.get('refresh_cache', False)
    if not word: return jsonify({"error": "Word/concept is required"}), 400
    # ... (rest of your generation logic) ...
    try:
        # ... (your content generation and caching logic) ...
        # Ensure you return a valid JSON response
        # For brevity, assuming your logic is here
        # Example response structure:
        # return jsonify({"word": word, mode: generated_data, "source": "generated/cache", ...}), 200
        sanitized_word_id = sanitize_word_for_id(word)
        user_word_history_ref = db.collection('users').document(current_user_id).collection('word_history').document(sanitized_word_id)
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
            if mode in cached_content and not force_refresh:
                user_word_history_ref.set({'last_explored_at': firestore.SERVER_TIMESTAMP, 'word': word}, merge=True)
                return jsonify({
                    "word": word, mode: cached_content[mode], "source": "cache", "is_favorite": is_favorite_status,
                    "full_cache": cached_content, "quiz_progress": quiz_progress_data, "modes_generated": modes_already_generated
                }), 200
        
        # ... (Gemini call and content processing) ...
        generated_text_content = None
        prompt = ""
        if mode == 'explain':
            prompt = f"Explain the concept of '{word}' in 2 simple sentences with words or sub-topics that could extend the learning. If relevant, identify up to 2 key words or sub-topics within your explanation that can progress the concept along the learning curve to deepen the understanding and wrap them in <click>tags</click> like this: <click>sub-topic</click>."
        elif mode == 'fact':
            prompt = f"Tell me one very interesting and concise fun fact about '{word}'."
        elif mode == 'quiz':
            prompt = f"Generate a set of up to 3 distinct multiple-choice quiz questions about '{word}'. For each question, provide the question, 4 options (A, B, C, D), and clearly indicate the correct answer (e.g., 'Correct Answer: A'). Ensure option keys are unique (A, B, C, D) for each question. Separate each complete question block (question, options, answer) with '---QUIZ_SEPARATOR---'." # Added emphasis on unique keys
        # ... (other modes)

        if mode in ['explain', 'fact', 'quiz'] and prompt:
            gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')
            response = gemini_model.generate_content(prompt)
            generated_text_content = response.text
            if mode == 'quiz':
                quiz_questions_array = [q.strip() for q in generated_text_content.split('---QUIZ_SEPARATOR---') if q.strip()]
                cached_content[mode] = quiz_questions_array if quiz_questions_array else ([generated_text_content.strip()] if generated_text_content.strip() else [])
            else:
                cached_content[mode] = generated_text_content
        elif mode in ['image', 'deep_dive']: # Placeholder
             cached_content[mode] = f"Placeholder for {mode} of {word}"


        if mode not in modes_already_generated: modes_already_generated.append(mode)
        payload = {
            'word': word, 'last_explored_at': firestore.SERVER_TIMESTAMP,
            'generated_content_cache': cached_content, 'is_favorite': is_favorite_status,
            'modes_generated': modes_already_generated
        }
        if not word_doc.exists:
            payload.update({'first_explored_at': firestore.SERVER_TIMESTAMP, 'is_favorite': False, 'quiz_progress': []})
        
        user_word_history_ref.set(payload, merge=True)
        return jsonify({
            "word": word, mode: cached_content.get(mode), "source": "generated",
            "is_favorite": payload.get('is_favorite', False), "full_cache": cached_content,
            "quiz_progress": payload.get('quiz_progress', quiz_progress_data), "modes_generated": modes_already_generated
        }), 200

    except Exception as e:
        app.logger.error(f"Error in /generate_explanation for '{word}', user '{current_user_id}': {e}", exc_info=True)
        return jsonify({"error": f"Internal error: {e}"}), 500


@app.route('/profile', methods=['GET', 'OPTIONS']) # Added OPTIONS
@token_required
def get_user_profile(current_user_id):
    # ... (Your existing profile logic) ...
    # This route should now correctly handle OPTIONS requests
    if not db: return jsonify({"error": "Database not configured"}), 500
    try:
        user_doc_ref = db.collection('users').document(current_user_id)
        user_doc = user_doc_ref.get()
        if not user_doc.exists: return jsonify({"error": "User not found"}), 404
        user_data = user_doc.to_dict()
        # ... (fetch word history, streaks etc.) ...
        word_history_list = [] # Populate this
        favorite_words_list = [] # Populate this
        streak_history_list = [] # Populate this
        # Example:
        for doc in user_doc_ref.collection('word_history').stream():
            entry = doc.to_dict()
            entry_data = {"id": doc.id, "word": entry.get("word"), "is_favorite": entry.get("is_favorite"), "last_explored_at": entry.get("last_explored_at").isoformat() if entry.get("last_explored_at") else None}
            word_history_list.append(entry_data)
            if entry.get("is_favorite"): favorite_words_list.append(entry_data)

        return jsonify({
            "username": user_data.get("username"), "email": user_data.get("email"), "tier": user_data.get("tier"),
            "total_words_explored": len(word_history_list), "explored_words": word_history_list,
            "favorite_words": favorite_words_list, "streak_history": streak_history_list,
            "created_at": user_data.get("created_at").isoformat() if user_data.get("created_at") else None
        }), 200
    except Exception as e:
        app.logger.error(f"Error fetching profile for user '{current_user_id}': {e}", exc_info=True)
        return jsonify({"error": f"Failed to fetch profile: {e}"}), 500

@app.route('/toggle_favorite', methods=['POST', 'OPTIONS'])
@token_required
def toggle_favorite_word(current_user_id):
    # ... (Your existing logic) ...
    if not db: return jsonify({"error": "Database not configured"}), 500
    data = request.get_json()
    word_to_toggle = data.get('word', '').strip()
    if not word_to_toggle: return jsonify({"error": "Word is required"}), 400
    sanitized_word_id = sanitize_word_for_id(word_to_toggle)
    word_ref = db.collection('users').document(current_user_id).collection('word_history').document(sanitized_word_id)
    try:
        word_doc = word_ref.get()
        if not word_doc.exists: return jsonify({"error": "Word not found in history"}), 404
        current_is_favorite = word_doc.to_dict().get('is_favorite', False)
        new_favorite_status = not current_is_favorite
        word_ref.update({'is_favorite': new_favorite_status, 'last_explored_at': firestore.SERVER_TIMESTAMP})
        return jsonify({"message": "Favorite status updated", "word": word_to_toggle, "is_favorite": new_favorite_status}), 200
    except Exception as e:
        app.logger.error(f"Error toggling favorite for '{word_to_toggle}': {e}", exc_info=True)
        return jsonify({"error": f"Failed to toggle favorite: {e}"}), 500


@app.route('/save_streak', methods=['POST', 'OPTIONS'])
@token_required
def save_user_streak(current_user_id):
    # ... (Your existing logic) ...
    if not db: return jsonify({"error": "Database not configured"}), 500
    data = request.get_json()
    streak_words = data.get('words')
    streak_score = data.get('score')
    if not isinstance(streak_words, list) or not streak_words or not isinstance(streak_score, int) or streak_score < 2:
        return jsonify({"error": "Invalid streak data"}), 400
    try:
        streaks_collection_ref = db.collection('users').document(current_user_id).collection('streaks')
        streak_doc_ref = streaks_collection_ref.document()
        streak_doc_ref.set({'words': streak_words, 'score': streak_score, 'completed_at': firestore.SERVER_TIMESTAMP})
        return jsonify({"message": "Streak saved", "streak_id": streak_doc_ref.id}), 201
    except Exception as e:
        app.logger.error(f"Error saving streak for user '{current_user_id}': {e}", exc_info=True)
        return jsonify({"error": f"Failed to save streak: {e}"}), 500


@app.route('/save_quiz_attempt', methods=['POST', 'OPTIONS']) # CRITICAL: Ensure OPTIONS is here
@token_required # This decorator MUST correctly handle OPTIONS now
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
        return jsonify({"error": "Missing required fields"}), 400
    # ... (add other validations as before)

    sanitized_word_id = sanitize_word_for_id(word)
    word_history_ref = db.collection('users').document(current_user_id).collection('word_history').document(sanitized_word_id)

    try:
        word_doc = word_history_ref.get()
        quiz_progress = []
        if word_doc.exists:
            quiz_progress = word_doc.to_dict().get('quiz_progress', [])
        else: # Should not happen if quiz is generated first, but handle defensively
            app.logger.warning(f"Word history for '{sanitized_word_id}' not found for user '{current_user_id}' during quiz save. Creating it.")
            word_history_ref.set({
                'word': word, 'first_explored_at': firestore.SERVER_TIMESTAMP,
                'last_explored_at': firestore.SERVER_TIMESTAMP, 'is_favorite': False,
                'quiz_progress': [], 'modes_generated': ['quiz']
            })
        
        new_attempt = {
            "question_index": question_index,
            "selected_option_key": selected_option_key,
            "is_correct": is_correct,
            "timestamp": datetime.now(timezone.utc).isoformat() 
        }
        
        # Replace if attempt for this index exists, else append
        attempt_updated = False
        for i, attempt in enumerate(quiz_progress):
            if attempt.get('question_index') == question_index:
                quiz_progress[i] = new_attempt
                attempt_updated = True
                break
        if not attempt_updated:
            quiz_progress.append(new_attempt)
        
        # Sort to ensure order if needed, though appending should maintain it if indices are sequential
        quiz_progress.sort(key=lambda x: x['question_index'])

        word_history_ref.update({"quiz_progress": quiz_progress, "last_explored_at": firestore.SERVER_TIMESTAMP})
        
        app.logger.info(f"Quiz attempt saved for user '{current_user_id}', word '{word}', q_idx {question_index}. New progress length: {len(quiz_progress)}")
        return jsonify({"message": "Quiz attempt saved", "quiz_progress": quiz_progress}), 200 # Return the updated progress

    except Exception as e:
        app.logger.error(f"Error saving quiz attempt for user '{current_user_id}', word '{word}': {e}", exc_info=True)
        return jsonify({"error": f"Failed to save quiz attempt: {e}"}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    # For local development, you might want debug=True. Render usually handles this.
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_DEBUG', 'False').lower() == 'true')
