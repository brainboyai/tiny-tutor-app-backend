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
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
if not app.logger.handlers:
    app.logger.addHandler(handler)

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
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'fallback_secret_key_for_dev_only_change_me_for_prod')
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
google_api_key = os.getenv('GOOGLE_API_KEY')
if google_api_key:
    try:
        genai.configure(api_key=google_api_key)
        app.logger.info("Google Generative AI configured.")
    except Exception as e:
        app.logger.error(f"Failed to configure Google Generative AI: {e}", exc_info=True)
else:
    app.logger.warning("GOOGLE_API_KEY not found. Generative AI functionality will be disabled.")

# --- Request Logging ---
@app.before_request
def log_all_requests():
    app.logger.debug(f"Incoming Request -- Method: {request.method}, Path: {request.path}")
    app.logger.debug(f"Request Headers: {dict(request.headers)}")
    if request.method == 'OPTIONS':
        app.logger.debug("Handling OPTIONS preflight request (Flask-CORS should manage response).")

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
                app.logger.warning("Malformed Authorization header.")
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
            'streak_history': [] # Initialize streak history
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
            profile_data = {
                "id": user_doc.id,
                "username": user_data.get("username"),
                "email": user_data.get("email"),
                "tier": user_data.get("tier", "free"),
                "total_words_explored": user_data.get("total_words_explored", 0),
                "explored_words": user_data.get("explored_words", []),
                "favorite_words": [word for word in user_data.get("explored_words", []) if word.get("is_favorite")], # Derived
                "streak_history": user_data.get("streak_history", []),
                "created_at": user_data.get("created_at").isoformat() if user_data.get("created_at") else None
            }
            app.logger.debug(f"Profile data for user {current_user_id}: {profile_data}")
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
    # Favorites are now managed as a flag within the 'explored_words' array in the main user document
    try:
        user_doc = user_ref.get()
        if not user_doc.exists:
            return jsonify({"error": "User not found"}), 404

        explored_words = user_doc.to_dict().get("explored_words", [])
        word_found = False
        updated_explored_words = []

        for word_entry in explored_words:
            if word_entry.get("id") == word_id:
                word_found = True
                if request.method == 'POST': # Add to favorites
                    word_entry["is_favorite"] = True
                    app.logger.info(f"Word '{word_id}' marked as favorite for user '{current_user_id}'.")
                elif request.method == 'DELETE': # Remove from favorites
                    word_entry["is_favorite"] = False
                    app.logger.info(f"Word '{word_id}' unmarked as favorite for user '{current_user_id}'.")
            updated_explored_words.append(word_entry)

        if not word_found and request.method == 'POST':
            # This case should ideally not happen if favoriting only explored words.
            # If it can, you'd need to decide how to handle adding a new word entry here.
            app.logger.warning(f"Attempt to favorite word '{word_id}' not in explored list for user '{current_user_id}'.")
            return jsonify({"error": "Word not explored yet, cannot mark as favorite."}), 404
        
        if word_found:
            user_ref.update({"explored_words": updated_explored_words})
            return jsonify({"message": f"Favorite status updated for {word_id}"}), 200
        else: # Should only be reachable if DELETE and word_found is False
            return jsonify({"error": "Word not found in explored list"}), 404

    except Exception as e:
        app.logger.error(f"Error managing favorite for user '{current_user_id}', word '{word_id}': {e}", exc_info=True)
        return jsonify({"error": "Failed to update favorite status"}), 500

# --- Word Interaction Routes ---
def get_word_content_from_genai(word, mode):
    app.logger.info(f"Fetching GenAI content for word: '{word}', mode: '{mode}'")
    if not google_api_key or not genai:
        app.logger.warning("Google API key or GenAI client not configured.")
        return "Generative AI service is not available."

    model = genai.GenerativeModel('gemini-2.0-flash')
    prompt = ""
    if mode == 'explain':
        # UPDATED PROMPT for clickable words
        prompt = f"Explain the concept of '{word}' in 2 simple sentences with words or sub-topics that could extend the learning. If relevant, identify up to 2 key words or sub-topics within your explanation that can progress the concept along the learning curve to deepen the understanding and wrap them in <click>tags</click> like this: <click>sub-topic</click>."
    elif mode == 'fact':
        prompt = f"Tell me an interesting and verifiable fact about '{word}'."
    elif mode == 'deep_dive':
        prompt = f"Provide a deep dive into the concept of '{word}'. Include its history, applications, and related concepts. Aim for about 200-300 words."
    elif mode == 'quiz':
        # UPDATED PROMPT for multiple quiz questions (e.g., 3)
        prompt = f"""Create an array of 3 unique multiple-choice quiz questions about the word '{word}'.
Each question object in the array should have the following JSON structure:
{{
  "question": "string",
  "options": {{ "A": "string", "B": "string", "C": "string", "D": "string" }},
  "correct_answer_key": "string (A, B, C, or D)",
  "explanation": "string (brief explanation for the correct answer)"
}}
Return only the JSON array.
Example of a single question object:
{{
  "question": "What is the primary color of an apple?",
  "options": {{ "A": "Red", "B": "Blue", "C": "Green", "D": "Yellow" }},
  "correct_answer_key": "A",
  "explanation": "Apples are commonly red, though other colors exist."
}}
"""
        try:
            generation_config = genai.types.GenerationConfig(
                response_mime_type="application/json",
            )
            response = model.generate_content(prompt, generation_config=generation_config)
            app.logger.debug(f"GenAI Quiz raw response for '{word}': {response.text}")
            quiz_data_array = json.loads(response.text)

            if not isinstance(quiz_data_array, list):
                app.logger.error(f"GenAI Quiz JSON for '{word}' is not an array. Data: {quiz_data_array}")
                raise ValueError("Quiz data from AI is not an array.")

            for quiz_data in quiz_data_array: # Validate each question object
                if not all(k in quiz_data for k in ["question", "options", "correct_answer_key"]):
                    app.logger.error(f"GenAI Quiz JSON object in array for '{word}' missing required keys. Data: {quiz_data}")
                    raise ValueError("Quiz data object from AI is malformed (missing keys).")
                if not isinstance(quiz_data["options"], dict) or not all(k in quiz_data["options"] for k in ["A", "B", "C", "D"]): # Ensuring 4 options A-D
                     app.logger.error(f"GenAI Quiz JSON object for '{word}' options are malformed. Data: {quiz_data}")
                     raise ValueError("Quiz data object from AI is malformed (options).")
            return quiz_data_array
        except json.JSONDecodeError as je:
            app.logger.error(f"GenAI Quiz JSONDecodeError for '{word}': {je}. Response text: {response.text if 'response' in locals() else 'N/A'}")
            return "Failed to generate quiz: AI returned invalid JSON."
        except ValueError as ve:
            app.logger.error(f"GenAI Quiz ValueError for '{word}': {ve}")
            return f"Failed to generate quiz: {ve}"
        except Exception as e:
            app.logger.error(f"GenAI Quiz generation error for '{word}': {e}", exc_info=True)
            return "Failed to generate quiz content."

    if not prompt: return "Invalid mode selected."
    try:
        response = model.generate_content(prompt)
        app.logger.debug(f"GenAI text response for '{word}', mode '{mode}': {response.text[:100]}...")
        return response.text
    except Exception as e:
        app.logger.error(f"GenAI content generation error for word '{word}', mode '{mode}': {e}", exc_info=True)
        return f"Error generating content: {e}"

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
    # Word specific data is now stored within the 'explored_words' array in the user document.
    # We'll fetch the whole user document, find the word, and then its content.

    try:
        user_doc = user_ref.get()
        content = None
        source = "cache" # Assume cache initially

        if user_doc.exists:
            user_data = user_doc.to_dict()
            explored_words_list = user_data.get("explored_words", [])
            word_entry = next((w for w in explored_words_list if w.get("id") == sanitized_word), None)

            if word_entry and mode in word_entry.get("content", {}):
                content = word_entry["content"][mode]
                app.logger.info(f"Found cached content for '{sanitized_word}', mode '{mode}'.")
            else:
                app.logger.info(f"No cache or mode content for '{sanitized_word}', mode '{mode}'. Will fetch.")
        else: # User document doesn't exist, should not happen if token_required works
            app.logger.error(f"User document for {current_user_id} not found in get_word_info.")
            return jsonify({"error": "User not found"}), 404


        if content is None and mode == 'image':
            app.logger.info(f"Image mode for '{sanitized_word}'. Placeholder response.")
            return jsonify({"message": "Image generation for this word is not yet supported or is in progress."}), 202

        if content is None: # Fetch from GenAI if not cached
            source = "new"
            content = get_word_content_from_genai(sanitized_word, mode)
            if isinstance(content, str) and ("Error generating content" in content or "Failed to generate" in content or "service is not available" in content):
                 app.logger.error(f"Failed to get content from GenAI for '{sanitized_word}', mode '{mode}': {content}")
                 return jsonify({"error": content}), 500

            # Update Firestore document
            # This part needs to update the specific word_entry within the explored_words array
            updated_explored_words = []
            word_found_in_list = False
            current_time_iso = datetime.now(timezone.utc).isoformat()

            for w_entry in explored_words_list:
                if w_entry.get("id") == sanitized_word:
                    word_found_in_list = True
                    if "content" not in w_entry: w_entry["content"] = {}
                    w_entry["content"][mode] = content
                    w_entry["last_explored_at"] = current_time_iso
                    w_entry["modes_generated"] = list(set(w_entry.get("modes_generated", []) + [mode]))
                updated_explored_words.append(w_entry)

            if not word_found_in_list:
                new_word_data = {
                    "id": sanitized_word,
                    "word": word, # Original word
                    "first_explored_at": current_time_iso,
                    "last_explored_at": current_time_iso,
                    "is_favorite": False,
                    "quiz_progress": [],
                    "content": {mode: content},
                    "modes_generated": [mode]
                }
                updated_explored_words.append(new_word_data)
                user_ref.update({"total_words_explored": firestore.Increment(1)})
                app.logger.info(f"New word '{sanitized_word}' added to explored_words for user '{current_user_id}'.")

            user_ref.update({"explored_words": updated_explored_words})
            app.logger.info(f"Explored_words updated for '{sanitized_word}', mode '{mode}', user '{current_user_id}'.")

        return jsonify({"word": sanitized_word, "mode": mode, "content": content, "source": source}), 200
    except Exception as e:
        app.logger.error(f"Error fetching info for word '{sanitized_word}', mode '{mode}', user '{current_user_id}': {e}", exc_info=True)
        return jsonify({"error": f"Failed to get information for '{word}': {e}"}), 500

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
            app.logger.warning("Invalid quiz attempt data.")
            return jsonify({"error": "Invalid quiz attempt data."}), 400

        user_ref = db.collection('users').document(current_user_id)
        user_doc = user_ref.get()
        if not user_doc.exists: return jsonify({"error": "User not found"}), 404

        explored_words = user_doc.to_dict().get("explored_words", [])
        updated_explored_words = []
        word_found = False
        current_quiz_progress = []

        for word_entry in explored_words:
            if word_entry.get("id") == sanitized_word:
                word_found = True
                current_quiz_progress = word_entry.get("quiz_progress", [])
                new_attempt = {
                    "question_index": question_index,
                    "selected_option_key": selected_option_key,
                    "is_correct": is_correct,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                attempt_updated = False
                for i, attempt in enumerate(current_quiz_progress):
                    if attempt.get('question_index') == question_index:
                        current_quiz_progress[i] = new_attempt
                        attempt_updated = True
                        break
                if not attempt_updated:
                    current_quiz_progress.append(new_attempt)
                
                current_quiz_progress.sort(key=lambda x: x['question_index'])
                word_entry["quiz_progress"] = current_quiz_progress
                word_entry["last_explored_at"] = datetime.now(timezone.utc).isoformat()
            updated_explored_words.append(word_entry)

        if not word_found: # Should ideally not happen if quiz is for an explored word
            app.logger.warning(f"Quiz attempt for non-existent word '{sanitized_word}' in user '{current_user_id}' explored list.")
            return jsonify({"error": "Word not found in explored history to save quiz attempt."}), 404
            
        user_ref.update({"explored_words": updated_explored_words})
        app.logger.info(f"Quiz attempt saved for user '{current_user_id}', word '{sanitized_word}', q_idx {question_index}.")
        return jsonify({"message": "Quiz attempt saved", "quiz_progress": current_quiz_progress}), 200
    except Exception as e:
        app.logger.error(f"Error saving quiz attempt for user '{current_user_id}', word '{sanitized_word}': {e}", exc_info=True)
        return jsonify({"error": f"Failed to save quiz attempt: {e}"}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.logger.info(f"Starting Flask development server on http://localhost:{port}")
    app.run(debug=True, host='0.0.0.0', port=port)
