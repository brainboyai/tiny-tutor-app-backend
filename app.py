from flask import Flask, request, jsonify, current_app
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
import logging

load_dotenv()

app = Flask(__name__)

# --- Logging Configuration ---
app.logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler()
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s')
handler.setFormatter(formatter)
if not app.logger.handlers:
    app.logger.addHandler(handler)
    app.logger.propagate = False 

app.logger.info("Flask app starting up...")

# --- CORS Configuration ---
CORS(app,
     resources={r"/*": {"origins": [
         "https://tiny-tutor-app-frontend.onrender.com",
         "http://localhost:5173",
         "http://127.0.0.1:5173"
     ]}},
     supports_credentials=True,
     expose_headers=["Content-Type", "Authorization"],
     allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Access-Control-Request-Method", "Access-Control-Request-Headers", "Origin"],
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"]
)
app.logger.info("CORS configured.")

# --- App Configuration ---
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'fallback_secret_key_for_dev_only_change_me_for_prod_strong_key')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)
app.logger.info("JWT configuration loaded.")

# --- Firebase Initialization ---
service_account_key_base64 = os.getenv('FIREBASE_SERVICE_ACCOUNT_KEY_BASE64')
db = None
if service_account_key_base64:
    try:
        decoded_key_bytes = base64.b64decode(service_account_key_base64)
        service_account_info = json.loads(decoded_key_bytes.decode('utf-8'))
        cred = credentials.Certificate(service_account_info)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
            app.logger.info("Firebase Admin SDK initialized successfully.")
        else:
            app.logger.info("Firebase Admin SDK already initialized.")
        db = firestore.client()
    except Exception as e:
        app.logger.error(f"Failed to initialize Firebase Admin SDK: {e}", exc_info=True)
else:
    app.logger.warning("FIREBASE_SERVICE_ACCOUNT_KEY_BASE64 not found. Firebase functionality will be disabled.")

# --- Generative AI Configuration ---
gemini_api_key_from_env = os.getenv('GEMINI_API_KEY') # Ensure this matches your .env file
app.logger.info(f"Attempting to load GEMINI_API_KEY. Value seen by os.getenv: '{'SET' if gemini_api_key_from_env else 'NOT SET'}'")

if gemini_api_key_from_env and gemini_api_key_from_env.strip():
    try:
        genai.configure(api_key=gemini_api_key_from_env)
        app.logger.info("Google Generative AI configured successfully.")
    except Exception as e:
        app.logger.error(f"Failed to configure Google Generative AI: {e}", exc_info=True)
else:
    app.logger.warning("GEMINI_API_KEY not found, is empty, or contains only whitespace. Generative AI functionality will be disabled.")

# --- Request Logging ---
@app.before_request
def log_all_requests():
    app.logger.debug(f"Incoming Request -- Method: {request.method}, Path: {request.path}, RemoteAddr: {request.remote_addr}")
    app.logger.debug(f"Request Headers: {dict(request.headers)}")

# --- Rate Limiter ---
limiter = Limiter(get_remote_address, app=app, default_limits=["200 per day", "50 per hour"], storage_uri="memory://")
app.logger.info("Rate limiter configured.")

# --- JWT Token Required Decorator ---
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # Handle OPTIONS requests for CORS preflight
        if request.method == 'OPTIONS':
            # Flask-CORS should handle this, but this ensures OPTIONS requests pass through if not already handled.
            # A more robust way is to ensure Flask-CORS handles it by being initialized before routes.
            app.logger.debug(f"OPTIONS request received for: {request.path}, letting Flask-CORS handle.")
            # If Flask-CORS is correctly configured, it adds headers. We just need to return an OK response.
            # However, Flask-CORS typically intercepts and responds directly.
            # This explicit handling might be redundant or could conflict if Flask-CORS is fully managing it.
            # For now, let's assume Flask-CORS handles the response headers.
            # If issues persist, one might return current_app.make_default_options_response()
            # or a simple jsonify({}), 200 after Flask-CORS has added headers.
            return # Let Flask-CORS handle the response or return a simple 200 OK.

        token = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]
            except IndexError:
                app.logger.warning("Malformed Authorization header.")
                return jsonify({"error": "Malformed token"}), 401
        if not token: return jsonify({"error": "Token is missing"}), 401
        try:
            data = jwt.decode(token, current_app.config['JWT_SECRET_KEY'], algorithms=["HS256"])
            kwargs['current_user_id'] = data['user_id']
        except jwt.ExpiredSignatureError: return jsonify({"error": "Token has expired"}), 401
        except jwt.InvalidTokenError: return jsonify({"error": "Invalid token"}), 401
        except Exception as e:
            app.logger.error(f"Token validation error: {e}", exc_info=True)
            return jsonify({"error": "Token validation failed"}), 401
        return f(*args, **kwargs)
    return decorated

# --- Routes ---
@app.route('/')
def home():
    app.logger.info("Home route accessed.")
    return jsonify(message="Welcome to Tiny Tutor AI Backend!"), 200

# --- Authentication Routes ---
@app.route('/auth/signup', methods=['POST'])
@limiter.limit("5 per hour")
def signup():
    app.logger.info(f"Signup attempt received for path: {request.path}")
    if not db: return jsonify({"error": "Server configuration error: Database not available"}), 503
    try:
        data = request.get_json()
        if not data or not data.get('email') or not data.get('password') or not data.get('username'):
            return jsonify({"error": "Email, password, and username are required"}), 400
        email = data['email'].lower()
        username = data['username']
        password = data['password']
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email): return jsonify({"error": "Invalid email format"}), 400
        if len(password) < 6: return jsonify({"error": "Password must be at least 6 characters long"}), 400

        users_ref = db.collection('users')
        if users_ref.where('email', '==', email).limit(1).get(): return jsonify({"error": "Email already exists"}), 409
        if users_ref.where('username_lowercase', '==', username.lower()).limit(1).get(): return jsonify({"error": "Username already exists"}), 409

        hashed_password = generate_password_hash(password)
        user_data = {
            'email': email, 'username': username, 'username_lowercase': username.lower(),
            'password_hash': hashed_password, 'tier': 'free', 
            'created_at': firestore.SERVER_TIMESTAMP, 'total_words_explored': 0,
            'explored_words': [], 'streak_history': [] # Initialized, but actual history from subcollection
        }
        user_ref = users_ref.document()
        user_ref.set(user_data)
        user_id = user_ref.id
        app.logger.info(f"User '{username}' ({email}) signed up successfully. User ID: {user_id}")
        token_payload = {
            'user_id': user_id, 'username': username,
            'exp': datetime.now(timezone.utc) + current_app.config['JWT_ACCESS_TOKEN_EXPIRES']
        }
        token = jwt.encode(token_payload, current_app.config['JWT_SECRET_KEY'], algorithm='HS256')
        return jsonify({"message": "Signup successful", "token": token, "username": username}), 201
    except Exception as e:
        app.logger.error(f"Signup error: {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred during signup."}), 500

@app.route('/auth/login', methods=['POST'])
@limiter.limit("10 per minute")
def login():
    app.logger.info(f"Login attempt received for path: {request.path}")
    if not db: return jsonify({"error": "Server configuration error: Database not available"}), 503
    try:
        data = request.get_json()
        if not data or not data.get('email') or not data.get('password'):
            return jsonify({"error": "Email and password are required"}), 400
        email = data['email'].lower() # Assuming login with email
        password = data['password']
        users_ref = db.collection('users')
        query_result = users_ref.where('email', '==', email).limit(1).stream()
        user_doc_snapshot = next(query_result, None)

        if user_doc_snapshot and check_password_hash(user_doc_snapshot.to_dict().get('password_hash'), password):
            user_id = user_doc_snapshot.id
            user_data = user_doc_snapshot.to_dict()
            token_payload = {
                'user_id': user_id, 'username': user_data.get('username'),
                'exp': datetime.now(timezone.utc) + current_app.config['JWT_ACCESS_TOKEN_EXPIRES']
            }
            token = jwt.encode(token_payload, current_app.config['JWT_SECRET_KEY'], algorithm='HS256')
            app.logger.info(f"User '{email}' logged in successfully. User ID: {user_id}")
            return jsonify({"message": "Login successful", "token": token, "username": user_data.get('username')}), 200
        else:
            app.logger.warning(f"Failed login attempt for email: '{email}'. Invalid credentials.")
            return jsonify({"error": "Invalid email or password"}), 401
    except Exception as e:
        app.logger.error(f"Login error: {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred during login."}), 500

# --- User Profile Routes ---
@app.route('/users/profile', methods=['GET'])
@token_required
def get_user_profile(current_user_id):
    app.logger.info(f"Fetching profile for user_id: {current_user_id}")
    if not db: return jsonify({"error": "Server configuration error: Database not available"}), 503
    try:
        user_ref = db.collection('users').document(current_user_id)
        user_doc = user_ref.get()
        if not user_doc.exists: return jsonify({"error": "User not found"}), 404
        
        user_data = user_doc.to_dict()
        created_at_val = user_data.get("created_at")
        explored_words_from_db = user_data.get("explored_words", [])
        if not isinstance(explored_words_from_db, list): explored_words_from_db = []
        valid_explored_words = [ew for ew in explored_words_from_db if isinstance(ew, dict)]

        # Fetch streak history from subcollection
        streak_history_list = []
        streaks_query = user_ref.collection('streaks').order_by('completed_at', direction=firestore.Query.DESCENDING).limit(50).stream()
        for streak_doc in streaks_query:
            streak_data = streak_doc.to_dict()
            completed_at_ts = streak_data.get("completed_at")
            streak_history_list.append({
                "id": streak_doc.id,
                "words": streak_data.get("words", []),
                "score": streak_data.get("score", 0),
                "completed_at": completed_at_ts.isoformat() if isinstance(completed_at_ts, datetime) else str(completed_at_ts) if completed_at_ts else None
            })
        app.logger.debug(f"Fetched {len(streak_history_list)} streak entries for user {current_user_id}")

        profile_data = {
            "id": user_doc.id, "username": user_data.get("username"), "email": user_data.get("email"),
            "tier": user_data.get("tier", "free"), "total_words_explored": user_data.get("total_words_explored", 0),
            "explored_words": valid_explored_words,
            "favorite_words": [word for word in valid_explored_words if word.get("is_favorite")],
            "streak_history": streak_history_list, # Populated from subcollection
            "created_at": created_at_val.isoformat() if isinstance(created_at_val, datetime) else str(created_at_val) if created_at_val else None
        }
        app.logger.debug(f"Profile data for user {current_user_id} (before sending): {profile_data}")
        return jsonify({"user": profile_data}), 200
    except Exception as e:
        app.logger.error(f"Error fetching profile for user_id {current_user_id}: {e}", exc_info=True)
        return jsonify({"error": "Failed to fetch user profile"}), 500

# --- Streak Saving Route (from old app.py) ---
@app.route('/save_streak', methods=['POST']) # OPTIONS handled by global CORS
@token_required
def save_user_streak(current_user_id):
    app.logger.info(f"User {current_user_id} attempting to save streak.")
    if not db: return jsonify({"error": "Database not configured"}), 500
    data = request.get_json()
    streak_words = data.get('words')
    streak_score = data.get('score')

    if not isinstance(streak_words, list) or not streak_words or not isinstance(streak_score, int) or streak_score < 1: # Min score 1 for a streak
        app.logger.warning(f"Invalid streak data for user {current_user_id}. Words: {streak_words}, Score: {streak_score}")
        return jsonify({"error": "Invalid streak data: words must be a non-empty list, score must be a positive integer."}), 400
    
    try:
        streaks_collection_ref = db.collection('users').document(current_user_id).collection('streaks')
        streak_doc_ref = streaks_collection_ref.document() # Auto-generate ID for new streak
        streak_doc_ref.set({
            'words': streak_words, 
            'score': streak_score, 
            'completed_at': firestore.SERVER_TIMESTAMP # Use server timestamp
        })
        app.logger.info(f"Streak saved for user '{current_user_id}'. Score: {streak_score}, Words: {len(streak_words)}. ID: {streak_doc_ref.id}")
        return jsonify({"message": "Streak saved successfully", "streak_id": streak_doc_ref.id}), 201
    except Exception as e:
        app.logger.error(f"Error saving streak for user '{current_user_id}': {e}", exc_info=True)
        return jsonify({"error": f"Failed to save streak: {str(e)}"}), 500


@app.route('/users/favorites/<word_id>', methods=['POST', 'DELETE'])
@token_required
def manage_favorite(current_user_id, word_id):
    app.logger.info(f"User {current_user_id} managing favorite for word_id: {word_id}, Method: {request.method}")
    if not db: return jsonify({"error": "Server configuration error"}), 503
    user_ref = db.collection('users').document(current_user_id)
    try:
        user_doc = user_ref.get()
        if not user_doc.exists: return jsonify({"error": "User not found"}), 404
        user_data = user_doc.to_dict()
        explored_words = user_data.get("explored_words", [])
        if not isinstance(explored_words, list): explored_words = []
        
        word_found_in_list = False
        updated_explored_words_list = []
        for word_entry in explored_words:
            if isinstance(word_entry, dict) and word_entry.get("id") == word_id:
                word_found_in_list = True
                new_fav_status = request.method == 'POST'
                if word_entry.get("is_favorite") == new_fav_status: # No change needed
                    app.logger.info(f"Favorite status for '{word_id}' for user '{current_user_id}' already {new_fav_status}.")
                else:
                    word_entry["is_favorite"] = new_fav_status
                    word_entry["last_explored_at"] = datetime.now(timezone.utc).isoformat()
                    app.logger.info(f"Word '{word_id}' favorite status set to {new_fav_status} for user '{current_user_id}'.")
            updated_explored_words_list.append(word_entry)

        if not word_found_in_list and request.method == 'POST':
            return jsonify({"error": "Word not explored yet, cannot mark as favorite."}), 404
        
        if word_found_in_list:
            user_ref.update({"explored_words": updated_explored_words_list})
            return jsonify({"message": f"Favorite status for '{word_id}' updated"}), 200
        elif not word_found_in_list and request.method == 'DELETE':
            return jsonify({"error": "Word not found in explored list to unfavorite."}), 404
        else:
            return jsonify({"error": "Could not update favorite status."}), 500
    except Exception as e:
        app.logger.error(f"Error managing favorite for user '{current_user_id}', word '{word_id}': {e}", exc_info=True)
        return jsonify({"error": "Failed to update favorite status"}), 500

# --- Word Interaction Routes ---
def get_word_content_from_genai(word, mode):
    app.logger.info(f"Fetching GenAI content for word: '{word}', mode: '{mode}'")
    if not (gemini_api_key_from_env and gemini_api_key_from_env.strip()) or not genai:
        app.logger.warning("GEMINI_API_KEY or GenAI client not configured.")
        return "Generative AI service is not available."
    model = genai.GenerativeModel('gemini-2.0-flash')
    prompt = ""
    if mode == 'explain':
        prompt = f"Explain the concept of '{word}' in 2 simple sentences with words or sub-topics that could extend the learning. If relevant, identify up to 2 key words or sub-topics within your explanation that can progress the concept along the learning curve to deepen the understanding and wrap them in <click>tags</click> like this: <click>sub-topic</click>."
    elif mode == 'fact':
        prompt = f"Tell me an interesting and verifiable fact about '{word}'."
    elif mode == 'deep_dive':
        prompt = f"Provide a  dive into the concept of '{word}'. Include its history, applications, and related concepts. Aim for about 10 words."
    elif mode == 'quiz':
        prompt = f"""Create an array of 3 unique multiple-choice quiz questions about the word '{word}'.
Each question object in the array should have the following JSON structure:
{{
  "question": "string",
  "options": {{ "A": "string", "B": "string", "C": "string", "D": "string" }},
  "correct_answer_key": "string (A, B, C, or D)",
  "explanation": "string (brief explanation for the correct answer)"
}}
Return only the JSON array. Ensure options A, B, C, D are always present.
"""
        try:
            generation_config = genai.types.GenerationConfig(response_mime_type="application/json")
            response = model.generate_content(prompt, generation_config=generation_config)
            app.logger.debug(f"GenAI Quiz raw response for '{word}': {response.text}")
            quiz_data_array = json.loads(response.text)
            if not isinstance(quiz_data_array, list): raise ValueError("Quiz data from AI is not an array.")
            valid_questions = []
            for quiz_data in quiz_data_array:
                if not isinstance(quiz_data, dict): continue
                if not all(k in quiz_data for k in ["question", "options", "correct_answer_key"]): continue
                if not isinstance(quiz_data["options"], dict) or not all(k in quiz_data["options"] for k in ["A", "B", "C", "D"]): continue
                valid_questions.append(quiz_data)
            if not valid_questions: raise ValueError("AI failed to generate any valid quiz questions.")
            return valid_questions
        except Exception as e:
            app.logger.error(f"GenAI Quiz generation error for '{word}': {e}", exc_info=True)
            return f"Failed to generate quiz: {str(e)}"

    if not prompt: return "Invalid mode selected."
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        app.logger.error(f"GenAI content generation error for word '{word}', mode '{mode}': {e}", exc_info=True)
        return f"Error generating content: {str(e)}"

@app.route('/words/<word>/<mode>', methods=['GET'])
@token_required
def get_word_info(current_user_id, word, mode):
    app.logger.info(f"User '{current_user_id}' requesting info for word: '{word}', mode: '{mode}'")
    if not db: return jsonify({"error": "Server configuration error"}), 503
    sanitized_word = re.sub(r'[^a-zA-Z0-9\s-]', '', word).strip().lower()
    if not sanitized_word: return jsonify({"error": "Invalid word"}), 400
    valid_modes = ['explain', 'image', 'fact', 'quiz', 'deep_dive']
    if mode not in valid_modes: return jsonify({"error": "Invalid mode"}), 400

    user_ref = db.collection('users').document(current_user_id)
    try:
        user_doc = user_ref.get()
        if not user_doc.exists: return jsonify({"error": "User not found"}), 404
        user_data = user_doc.to_dict()
        explored_words = user_data.get("explored_words", [])
        if not isinstance(explored_words, list): explored_words = []
        
        word_entry_index = -1
        for i, w_entry in enumerate(explored_words):
            if isinstance(w_entry, dict) and w_entry.get("id") == sanitized_word:
                word_entry_index = i; break
        
        word_entry_data = explored_words[word_entry_index] if word_entry_index != -1 else None
        content, source = None, "cache"

        if word_entry_data and isinstance(word_entry_data.get("content"), dict) and mode in word_entry_data["content"] and word_entry_data["content"][mode] is not None:
            content = word_entry_data["content"][mode]
        
        if content is None and mode == 'image':
            return jsonify({"message": "Image generation is in progress or not supported yet."}), 202

        if content is None:
            source = "new"
            content = get_word_content_from_genai(sanitized_word, mode)
            if isinstance(content, str) and ("Error generating content" in content or "Failed to generate" in content or "service is not available" in content or "AI returned invalid JSON" in content):
                 return jsonify({"error": content}), 500
            if content is None: return jsonify({"error": "Failed to retrieve content from AI service."}), 500

        current_time_iso = datetime.now(timezone.utc).isoformat()
        is_new_word_overall = False
        if word_entry_index != -1:
            target_entry = explored_words[word_entry_index]
            target_entry.setdefault("content", {})
            target_entry["content"][mode] = content
            target_entry["last_explored_at"] = current_time_iso
            target_entry.setdefault("modes_generated", [])
            if mode not in target_entry["modes_generated"]: target_entry["modes_generated"].append(mode)
        else:
            new_entry = {
                "id": sanitized_word, "word": word, "first_explored_at": current_time_iso,
                "last_explored_at": current_time_iso, "is_favorite": False, 
                "content": {mode: content}, "modes_generated": [mode], "quiz_progress": []
            }
            explored_words.append(new_entry)
            is_new_word_overall = True
        
        update_payload = {"explored_words": explored_words}
        if is_new_word_overall: update_payload["total_words_explored"] = firestore.Increment(1)
        user_ref.update(update_payload)
        
        # Streak logic: Increment today's streak or start a new one
        # This is a simplified version. A more robust one would handle multi-day streaks.
        # For now, we'll just log an activity for the day.
        # The actual streak calculation and saving to 'streaks' subcollection happens on frontend call to /save_streak
        app.logger.info(f"Word '{word}' explored by user '{current_user_id}'. Streak update handled by frontend via /save_streak.")

        return jsonify({"word": sanitized_word, "mode": mode, "content": content, "source": source}), 200
    except Exception as e:
        app.logger.error(f"Error in get_word_info for '{sanitized_word}', mode '{mode}', user '{current_user_id}': {e}", exc_info=True)
        return jsonify({"error": f"Failed to get information for '{word}': {str(e)}"}), 500

@app.route('/words/<word>/quiz/attempt', methods=['POST'])
@token_required
def save_quiz_attempt(current_user_id, word):
    app.logger.info(f"User '{current_user_id}' saving quiz attempt for word: '{word}'")
    if not db: return jsonify({"error": "Server configuration error"}), 503
    sanitized_word = re.sub(r'[^a-zA-Z0-9\s-]', '', word).strip().lower()
    if not sanitized_word: return jsonify({"error": "Invalid word"}), 400
    try:
        data = request.get_json()
        question_index, selected_option_key, is_correct = data.get('question_index'), data.get('selected_option_key'), data.get('is_correct')
        if not isinstance(question_index, int) or not isinstance(selected_option_key, str) or not isinstance(is_correct, bool):
            return jsonify({"error": "Invalid quiz attempt data."}), 400
        user_ref = db.collection('users').document(current_user_id)
        user_doc = user_ref.get(); 
        if not user_doc.exists: return jsonify({"error": "User not found"}), 404
        
        user_data = user_doc.to_dict()
        explored_words = user_data.get("explored_words", [])
        if not isinstance(explored_words, list): explored_words = []
        
        target_word_entry, word_entry_idx = None, -1
        for i, entry in enumerate(explored_words):
            if isinstance(entry, dict) and entry.get("id") == sanitized_word:
                target_word_entry, word_entry_idx = entry, i; break
        
        current_time_iso = datetime.now(timezone.utc).isoformat()
        if not target_word_entry:
            target_word_entry = {"id": sanitized_word, "word": word, "first_explored_at": current_time_iso, "quiz_progress": [], "modes_generated": ["quiz"], "content": {}}
        
        target_word_entry.setdefault("quiz_progress", [])
        if not isinstance(target_word_entry["quiz_progress"], list): target_word_entry["quiz_progress"] = []
        
        new_attempt = {"question_index": question_index, "selected_option_key": selected_option_key, "is_correct": is_correct, "timestamp": current_time_iso}
        
        attempt_idx = next((i for i, att in enumerate(target_word_entry["quiz_progress"]) if isinstance(att, dict) and att.get("question_index") == question_index), -1)
        if attempt_idx != -1: target_word_entry["quiz_progress"][attempt_idx] = new_attempt
        else: target_word_entry["quiz_progress"].append(new_attempt)
        
        target_word_entry["quiz_progress"].sort(key=lambda x: x.get('question_index', 0))
        target_word_entry["last_explored_at"] = current_time_iso
        if "quiz" not in target_word_entry.get("modes_generated", []): 
            target_word_entry.setdefault("modes_generated", []).append("quiz")

        if word_entry_idx != -1: explored_words[word_entry_idx] = target_word_entry
        else: explored_words.append(target_word_entry)
            
        user_ref.update({"explored_words": explored_words})
        return jsonify({"message": "Quiz attempt saved", "quiz_progress": target_word_entry["quiz_progress"]}), 200
    except Exception as e:
        app.logger.error(f"Error saving quiz attempt for user '{current_user_id}', word '{sanitized_word}': {e}", exc_info=True)
        return jsonify({"error": f"Failed to save quiz attempt: {str(e)}"}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.logger.info(f"Starting Flask development server on http://0.0.0.0:{port}")
    app.run(debug=True, host='0.0.0.0', port=port) # debug=True for local dev
