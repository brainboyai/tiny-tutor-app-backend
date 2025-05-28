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
app.logger.setLevel(logging.DEBUG) # Set root logger level
handler = logging.StreamHandler()
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s')
handler.setFormatter(formatter)
if not app.logger.handlers:
    app.logger.addHandler(handler)
    app.logger.propagate = False # Prevent duplicate logging if root handler is also configured

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
# Changed to look for GEMINI_API_KEY based on your Render screenshot
gemini_api_key_from_env = os.getenv('GEMINI_API_KEY')
app.logger.info(f"Attempting to load GEMINI_API_KEY. Value seen by os.getenv: '{gemini_api_key_from_env}'")
app.logger.info(f"Type of value seen by os.getenv for GEMINI_API_KEY: {type(gemini_api_key_from_env)}")
app.logger.info(f"Length of value seen if string: {len(gemini_api_key_from_env) if isinstance(gemini_api_key_from_env, str) else 'Not a string'}")

if gemini_api_key_from_env and gemini_api_key_from_env.strip(): # Check if key is not None and not just whitespace
    try:
        genai.configure(api_key=gemini_api_key_from_env) # Use the correctly named variable
        app.logger.info("Google Generative AI configured successfully.")
    except Exception as e:
        key_snippet = gemini_api_key_from_env[:5] + "..." + gemini_api_key_from_env[-5:] if isinstance(gemini_api_key_from_env, str) and len(gemini_api_key_from_env) > 10 else str(gemini_api_key_from_env)
        app.logger.error(f"Failed to configure Google Generative AI with key snippet '{key_snippet}': {e}", exc_info=True)
else:
    app.logger.warning("GEMINI_API_KEY not found, is empty, or contains only whitespace. Generative AI functionality will be disabled.")


# --- Request Logging ---
@app.before_request
def log_all_requests():
    app.logger.debug(f"Incoming Request -- Method: {request.method}, Path: {request.path}, RemoteAddr: {request.remote_addr}")
    app.logger.debug(f"Request Headers: {dict(request.headers)}")


# --- Rate Limiter ---
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)
app.logger.info("Rate limiter configured.")

# --- JWT Token Required Decorator ---
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]
            except IndexError:
                app.logger.warning("Malformed Authorization header. Token missing part.")
                return jsonify({"error": "Malformed token"}), 401

        if not token:
            app.logger.warning("Token is missing for protected route.")
            return jsonify({"error": "Token is missing"}), 401

        try:
            data = jwt.decode(token, current_app.config['JWT_SECRET_KEY'], algorithms=["HS256"])
            current_user_id = data['user_id']
        except jwt.ExpiredSignatureError:
            app.logger.warning("Token has expired.")
            return jsonify({"error": "Token has expired"}), 401
        except jwt.InvalidTokenError:
            app.logger.warning("Invalid token.")
            return jsonify({"error": "Invalid token"}), 401
        except Exception as e:
            app.logger.error(f"Token validation error: {e}", exc_info=True)
            return jsonify({"error": "Token validation failed"}), 401
        return f(current_user_id, *args, **kwargs)
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
    if not db:
        app.logger.error("Database not initialized. Cannot process signup.")
        return jsonify({"error": "Server configuration error: Database not available"}), 503
    try:
        data = request.get_json()
        if not data or not data.get('email') or not data.get('password') or not data.get('username'):
            app.logger.warning("Signup failed: Missing email, password, or username.")
            return jsonify({"error": "Email, password, and username are required"}), 400

        email = data['email'].lower()
        username = data['username']
        password = data['password']

        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            app.logger.warning(f"Signup failed for '{email}': Invalid email format.")
            return jsonify({"error": "Invalid email format"}), 400
        if len(password) < 6:
            app.logger.warning(f"Signup failed for '{email}': Password too short.")
            return jsonify({"error": "Password must be at least 6 characters long"}), 400

        users_ref = db.collection('users')
        if users_ref.where('email', '==', email).limit(1).get():
            app.logger.warning(f"Signup failed: Email '{email}' already exists.")
            return jsonify({"error": "Email already exists"}), 409
        if users_ref.where('username_lowercase', '==', username.lower()).limit(1).get():
            app.logger.warning(f"Signup failed: Username '{username}' already exists.")
            return jsonify({"error": "Username already exists"}), 409

        hashed_password = generate_password_hash(password)
        user_data = {
            'email': email,
            'username': username,
            'username_lowercase': username.lower(),
            'password_hash': hashed_password,
            'tier': 'free',
            'created_at': firestore.SERVER_TIMESTAMP,
            'total_words_explored': 0,
            'explored_words': [],
            'favorite_words': [], # This field might be redundant if derived from explored_words
            'streak_history': []
        }
        user_ref = users_ref.document()
        user_ref.set(user_data)
        user_id = user_ref.id

        app.logger.info(f"User '{username}' ({email}) signed up successfully. User ID: {user_id}")
        token_payload = {
            'user_id': user_id,
            'username': username,
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
    if not db:
        app.logger.error("Database not initialized. Cannot process login.")
        return jsonify({"error": "Server configuration error: Database not available"}), 503
    try:
        data = request.get_json()
        if not data or not data.get('email') or not data.get('password'):
            app.logger.warning("Login failed: Missing email or password.")
            return jsonify({"error": "Email and password are required"}), 400

        email = data['email'].lower()
        password = data['password']

        users_ref = db.collection('users')
        query_result = users_ref.where('email', '==', email).limit(1).stream()
        user_doc_snapshot = next(query_result, None)

        if user_doc_snapshot and check_password_hash(user_doc_snapshot.to_dict().get('password_hash'), password):
            user_id = user_doc_snapshot.id
            user_data = user_doc_snapshot.to_dict()
            token_payload = {
                'user_id': user_id,
                'username': user_data.get('username'),
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
        if user_doc.exists:
            user_data = user_doc.to_dict()
            created_at_val = user_data.get("created_at")
            profile_data = {
                "id": user_doc.id,
                "username": user_data.get("username"),
                "email": user_data.get("email"),
                "tier": user_data.get("tier", "free"),
                "total_words_explored": user_data.get("total_words_explored", 0),
                "explored_words": user_data.get("explored_words", []),
                "favorite_words": [], # Derived below
                "streak_history": user_data.get("streak_history", []),
                "created_at": created_at_val.isoformat() if isinstance(created_at_val, datetime) else str(created_at_val) if created_at_val else None
            }
            # Derive favorite_words from explored_words
            if profile_data["explored_words"]:
                profile_data["favorite_words"] = [
                    word for word in profile_data["explored_words"] if isinstance(word, dict) and word.get("is_favorite")
                ]
            app.logger.debug(f"Profile data for user {current_user_id} (before sending): {profile_data}")
            return jsonify({"user": profile_data}), 200
        else:
            app.logger.warning(f"User profile not found for user_id: {current_user_id}")
            return jsonify({"error": "User not found"}), 404
    except Exception as e:
        app.logger.error(f"Error fetching profile for user_id {current_user_id}: {e}", exc_info=True)
        return jsonify({"error": "Failed to fetch user profile"}), 500

@app.route('/users/favorites/<word_id>', methods=['POST', 'DELETE'])
@token_required
def manage_favorite(current_user_id, word_id):
    app.logger.info(f"User {current_user_id} managing favorite for word_id: {word_id}, Method: {request.method}")
    if not db: return jsonify({"error": "Server configuration error"}), 503

    user_ref = db.collection('users').document(current_user_id)
    try:
        user_doc = user_ref.get()
        if not user_doc.exists:
            app.logger.warning(f"User {current_user_id} not found for managing favorite.")
            return jsonify({"error": "User not found"}), 404

        user_data = user_doc.to_dict()
        explored_words = user_data.get("explored_words", [])
        word_found_in_list = False
        updated_explored_words_list = []

        for word_entry in explored_words:
            if isinstance(word_entry, dict) and word_entry.get("id") == word_id:
                word_found_in_list = True
                if request.method == 'POST':
                    word_entry["is_favorite"] = True
                    app.logger.info(f"Word '{word_id}' marked as favorite for user '{current_user_id}'.")
                elif request.method == 'DELETE':
                    word_entry["is_favorite"] = False
                    app.logger.info(f"Word '{word_id}' unmarked as favorite for user '{current_user_id}'.")
                word_entry["last_explored_at"] = datetime.now(timezone.utc).isoformat()
            updated_explored_words_list.append(word_entry)

        if not word_found_in_list:
            # If the word is not in explored_words, it means it hasn't been "explored" via /words/<word>/<mode>
            # which is where new words are added to this list.
            # For now, we'll prevent favoriting a word not yet in the main 'explored_words' list.
            # Alternatively, you could add it here with default values if the design allows.
            app.logger.warning(f"Word '{word_id}' not found in explored_words for user '{current_user_id}' to manage favorite.")
            return jsonify({"error": "Word not explored yet, cannot manage favorite status."}), 404

        user_ref.update({"explored_words": updated_explored_words_list})
        return jsonify({"message": f"Favorite status for '{word_id}' updated"}), 200
    except Exception as e:
        app.logger.error(f"Error managing favorite for user '{current_user_id}', word '{word_id}': {e}", exc_info=True)
        return jsonify({"error": "Failed to update favorite status"}), 500


# --- Word Interaction Routes ---
def get_word_content_from_genai(word, mode):
    app.logger.info(f"Fetching GenAI content for word: '{word}', mode: '{mode}'")
    # This global variable gemini_api_key_from_env is set at the top of the script
    if not (gemini_api_key_from_env and gemini_api_key_from_env.strip()) or not genai:
        app.logger.warning("GEMINI_API_KEY (from global var) or GenAI client not configured. Cannot fetch from GenAI.")
        return "Generative AI service is not available."

    model_name = 'gemini-2.0-flash'
    model = genai.GenerativeModel(model_name)
    prompt = ""

    if mode == 'explain':
        prompt = f"Explain the word '{word}' in a clear and concise way, suitable for a general audience. Provide etymology if interesting."
    elif mode == 'fact':
        prompt = f"Tell me an interesting and verifiable fact about '{word}'."
    elif mode == 'deep_dive':
        prompt = f"Provide a deep dive into the concept of '{word}'. Include its history, applications, and related concepts. Aim for about 200-300 words."
    elif mode == 'quiz':
        prompt = f"""Create a multiple-choice quiz question about the word '{word}'.
Provide the question, 4 options (A, B, C, D), and indicate the correct answer key (e.g., "A").
Also provide a brief explanation for the correct answer.
Format the output as a JSON object with keys: "question", "options" (an object with A,B,C,D as keys), "correct_answer_key", and "explanation".
Example:
{{
  "question": "What is the primary color of an apple?",
  "options": {{ "A": "Red", "B": "Blue", "C": "Green", "D": "Yellow" }},
  "correct_answer_key": "A",
  "explanation": "Apples are commonly red, though other colors exist."
}}
Return only the JSON object.
"""
        try:
            generation_config = genai.types.GenerationConfig(response_mime_type="application/json")
            response = model.generate_content(prompt, generation_config=generation_config)
            app.logger.debug(f"GenAI Quiz raw response for '{word}': {response.text}")
            
            # Attempt to parse the JSON response
            parsed_response_text = json.loads(response.text)
            
            # Determine if the AI returned a single quiz object or a list containing one.
            # The prompt asks for a single JSON object.
            if isinstance(parsed_response_text, dict):
                quiz_data = parsed_response_text
            elif isinstance(parsed_response_text, list) and len(parsed_response_text) > 0 and isinstance(parsed_response_text[0], dict):
                quiz_data = parsed_response_text[0] # Take the first element if it's a list of one
            else:
                app.logger.error(f"GenAI Quiz JSON for '{word}' is not a dict or a list with one dict. Data: {parsed_response_text}")
                raise ValueError("Quiz data from AI is malformed (unexpected structure).")

            # Validate the structure of the quiz_data object
            if not all(k in quiz_data for k in ["question", "options", "correct_answer_key"]):
                app.logger.error(f"GenAI Quiz JSON for '{word}' missing required keys. Data: {quiz_data}")
                raise ValueError("Quiz data from AI is malformed (missing keys).")
            if not isinstance(quiz_data["options"], dict) or not (2 <= len(quiz_data["options"]) <= 4):
                 app.logger.error(f"GenAI Quiz JSON for '{word}' options are malformed or wrong number of options. Data: {quiz_data}")
                 raise ValueError("Quiz data from AI is malformed (options).")
            return [quiz_data] # Return as a list containing one quiz object, as per frontend expectation

        except json.JSONDecodeError as je:
            resp_text = response.text if 'response' in locals() and hasattr(response, 'text') else 'N/A'
            app.logger.error(f"GenAI Quiz JSONDecodeError for '{word}': {je}. Response text: {resp_text}")
            return "Failed to generate quiz: AI returned invalid JSON."
        except ValueError as ve: # Catch our custom validation errors
            app.logger.error(f"GenAI Quiz ValueError for '{word}': {ve}")
            return f"Failed to generate quiz: {ve}" # Pass specific validation error
        except Exception as e:
            app.logger.error(f"GenAI Quiz generation error for '{word}': {e}", exc_info=True)
            return "Failed to generate quiz content."

    if not prompt: return "Invalid mode selected." # Should not happen if mode is validated before calling
    try:
        response = model.generate_content(prompt)
        app.logger.debug(f"GenAI text response for '{word}', mode '{mode}': {response.text[:100]}...")
        return response.text
    except Exception as e:
        app.logger.error(f"GenAI content generation error for word '{word}', mode '{mode}': {e}", exc_info=True)
        return f"Error generating content: {str(e)}"


@app.route('/words/<word>/<mode>', methods=['GET'])
@token_required
@limiter.limit("30 per minute")
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
        if not user_doc.exists:
            app.logger.warning(f"User {current_user_id} not found for word info request.")
            return jsonify({"error": "User not found"}), 404

        user_data = user_doc.to_dict()
        explored_words = user_data.get("explored_words", [])
        word_entry = next((w for w in explored_words if isinstance(w, dict) and w.get("id") == sanitized_word), None)
        
        content = None
        source = "cache"

        if word_entry and isinstance(word_entry.get("content"), dict) and mode in word_entry["content"] and word_entry["content"][mode] is not None:
            content = word_entry["content"][mode]
            app.logger.info(f"Found cached content for '{sanitized_word}', mode '{mode}'.")
        
        if content is None and mode == 'image':
            app.logger.info(f"Image mode for '{sanitized_word}'. Image generation not fully implemented.")
            # For now, let's return a message. If you implement image generation, this will change.
            # If GenAI is used to generate a description FOR an image, that would be handled by other modes.
            return jsonify({"message": "Image generation is in progress or not supported yet."}), 202

        if content is None: # Fetch from GenAI if not cached or if cache was null/empty
            source = "new"
            app.logger.info(f"No cache or empty cache for '{sanitized_word}', mode '{mode}'. Fetching from GenAI.")
            content = get_word_content_from_genai(sanitized_word, mode)
            
            # Check if GenAI returned an error string
            if isinstance(content, str) and ("Error generating content" in content or "Failed to generate" in content or "service is not available" in content or "AI returned invalid JSON" in content):
                 app.logger.error(f"Failed to get content from GenAI for '{sanitized_word}', mode '{mode}': {content}")
                 return jsonify({"error": content}), 500
            # Also check if content is None after GenAI call (though get_word_content_from_genai should return string)
            if content is None:
                app.logger.error(f"GenAI returned None for '{sanitized_word}', mode '{mode}'. This indicates an unexpected issue.")
                return jsonify({"error": "Failed to retrieve content from AI service."}), 500


        # Update explored_words array in the user document
        is_new_word_overall = not word_entry # True if this is the first time any mode is explored for this word by this user
        
        if word_entry: # Word exists in explored_words, update it
            word_entry.setdefault("content", {})
            word_entry["content"][mode] = content
            word_entry["last_explored_at"] = datetime.now(timezone.utc).isoformat()
            word_entry.setdefault("modes_generated", [])
            if mode not in word_entry["modes_generated"]:
                word_entry["modes_generated"].append(mode)
            
            # Find and replace the updated word_entry in the explored_words list
            updated_explored_words_list = [w if (not (isinstance(w, dict) and w.get("id") == sanitized_word)) else word_entry for w in explored_words]
        else: # Word is new to explored_words, create and add it
            word_entry = {
                "id": sanitized_word,
                "word": word, # Original word
                "first_explored_at": datetime.now(timezone.utc).isoformat(),
                "last_explored_at": datetime.now(timezone.utc).isoformat(),
                "is_favorite": False,
                "content": {mode: content},
                "modes_generated": [mode],
                "quiz_progress": []
            }
            updated_explored_words_list = explored_words + [word_entry]

        update_payload = {"explored_words": updated_explored_words_list}
        if is_new_word_overall:
            update_payload["total_words_explored"] = firestore.Increment(1)
            app.logger.info(f"Incremented total_words_explored for user '{current_user_id}'.")

        user_ref.update(update_payload)
        app.logger.info(f"Word entry for '{sanitized_word}', mode '{mode}' processed for user '{current_user_id}'.")
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
        question_index = data.get('question_index')
        selected_option_key = data.get('selected_option_key')
        is_correct = data.get('is_correct')

        if not isinstance(question_index, int) or \
           not isinstance(selected_option_key, str) or \
           not isinstance(is_correct, bool):
            app.logger.warning("Invalid quiz attempt data format.")
            return jsonify({"error": "Invalid quiz attempt data."}), 400

        user_ref = db.collection('users').document(current_user_id)
        user_doc = user_ref.get()
        if not user_doc.exists:
            app.logger.warning(f"User {current_user_id} not found for saving quiz attempt.")
            return jsonify({"error": "User not found"}), 404

        user_data = user_doc.to_dict()
        explored_words = user_data.get("explored_words", [])
        target_word_entry = None
        word_entry_index = -1

        for i, w_entry in enumerate(explored_words):
            if isinstance(w_entry, dict) and w_entry.get("id") == sanitized_word:
                target_word_entry = w_entry
                word_entry_index = i
                break
        
        is_new_word_overall_for_quiz_attempt = not target_word_entry

        if not target_word_entry:
            app.logger.info(f"Creating new word entry for '{sanitized_word}' via quiz attempt by user '{current_user_id}'.")
            target_word_entry = {
                "id": sanitized_word, "word": word,
                "first_explored_at": datetime.now(timezone.utc).isoformat(),
                "last_explored_at": datetime.now(timezone.utc).isoformat(),
                "is_favorite": False, "content": {}, "modes_generated": ["quiz"], # Mark quiz as generated
                "quiz_progress": []
            }
            # explored_words.append(target_word_entry) # Will be added/updated in the list later
        
        target_word_entry.setdefault("quiz_progress", [])
        quiz_progress_list = target_word_entry["quiz_progress"]

        new_attempt_data = {
            "question_index": question_index,
            "selected_option_key": selected_option_key,
            "is_correct": is_correct,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        existing_attempt_index = -1
        for i, attempt in enumerate(quiz_progress_list):
            if isinstance(attempt, dict) and attempt.get('question_index') == question_index:
                existing_attempt_index = i
                break
        
        if existing_attempt_index != -1:
            quiz_progress_list[existing_attempt_index] = new_attempt_data
        else:
            quiz_progress_list.append(new_attempt_data)

        quiz_progress_list.sort(key=lambda x: x.get('question_index', 0))
        target_word_entry["last_explored_at"] = datetime.now(timezone.utc).isoformat()
        
        # Update explored_words list in Firestore
        if word_entry_index != -1: # Existing word entry was found and modified
            explored_words[word_entry_index] = target_word_entry
        else: # New word entry was created for this quiz attempt
            explored_words.append(target_word_entry)

        update_payload_firestore = {"explored_words": explored_words}
        if is_new_word_overall_for_quiz_attempt: # If the word itself was new to explored_words
             update_payload_firestore["total_words_explored"] = firestore.Increment(1)

        user_ref.update(update_payload_firestore)
        app.logger.info(f"Quiz attempt saved for user '{current_user_id}', word '{sanitized_word}', q_idx {question_index}.")
        return jsonify({"message": "Quiz attempt saved", "quiz_progress": quiz_progress_list}), 200

    except Exception as e:
        app.logger.error(f"Error saving quiz attempt for user '{current_user_id}', word '{sanitized_word}': {e}", exc_info=True)
        return jsonify({"error": f"Failed to save quiz attempt: {str(e)}"}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.logger.info(f"Starting Flask development server on http://0.0.0.0:{port}")
    app.run(debug=True, host='0.0.0.0', port=port)
