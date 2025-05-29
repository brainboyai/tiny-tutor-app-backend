from flask import Flask, request, jsonify, current_app, g
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
import traceback # For more detailed error logging

load_dotenv()

app = Flask(__name__)

# --- Logging Configuration ---
if not app.debug or os.environ.get("FLASK_ENV") == "production":
    app.logger.setLevel(logging.INFO)
else:
    app.logger.setLevel(logging.DEBUG)

handler = logging.StreamHandler()
handler.setLevel(app.logger.level)
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(funcName)s - %(message)s'
)
handler.setFormatter(formatter)

if app.logger.hasHandlers():
    app.logger.handlers.clear()

app.logger.addHandler(handler)
app.logger.propagate = False

app.logger.info("Flask app starting up...")
app.logger.info(f"Flask environment: {os.environ.get('FLASK_ENV')}")
app.logger.info(f"Debug mode: {app.debug}")
app.logger.info(f"Logger level: {logging.getLevelName(app.logger.getEffectiveLevel())}")


# --- CORS Configuration ---
app.logger.info("Configuring CORS...")
CORS(app,
     resources={r"/*": {"origins": [
         "https://tiny-tutor-app-frontend.onrender.com",
         "http://localhost:5173",
         "http://127.0.0.1:5173"
     ]}},
     supports_credentials=True,
     expose_headers=["Content-Type", "Authorization"],
     allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Accept", "Origin"],
     max_age=86400
)
app.logger.info("CORS configured.")

# --- Firebase Initialization ---
app.logger.info("Initializing Firebase...")
try:
    firebase_creds_base64 = os.environ.get('FIREBASE_CREDENTIALS_BASE64')
    if not firebase_creds_base64:
        app.logger.error("FIREBASE_CREDENTIALS_BASE64 environment variable not found.")
        raise ValueError("FIREBASE_CREDENTIALS_BASE64 not set")

    decoded_creds = base64.b64decode(firebase_creds_base64)
    service_account_info = json.loads(decoded_creds)
    cred = credentials.Certificate(service_account_info)
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    app.logger.info("Firebase initialized successfully.")
except ValueError as ve:
    app.logger.error(f"Configuration error: {ve}")
    db = None
except Exception as e:
    app.logger.error(f"Error initializing Firebase: {e}", exc_info=True)
    db = None

# --- API Keys and Configuration ---
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    app.logger.warning("SECRET_KEY environment variable is not set. Authentication will not work.")

GOOGLE_GEMINI_API_KEY = os.environ.get('GOOGLE_GEMINI_API_KEY')
if GOOGLE_GEMINI_API_KEY:
    try:
        genai.configure(api_key=GOOGLE_GEMINI_API_KEY)
        app.logger.info("Google Gemini API configured.")
    except Exception as e:
        app.logger.error(f"Error configuring Google Gemini API: {e}", exc_info=True)
else:
    app.logger.warning("GOOGLE_GEMINI_API_KEY environment variable is not set. AI features may not work.")

# --- Rate Limiter ---
app.logger.info("Initializing Rate Limiter...")
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour", "10 per minute"],
    storage_uri="memory://",
)
app.logger.info("Rate Limiter initialized.")

# --- Helper Functions ---
def get_sanitized_word_id(word_text):
    if not isinstance(word_text, str):
        return "invalid_word_type"
    sanitized = re.sub(r'[^\w\s-]', '', word_text.lower().strip())
    sanitized = re.sub(r'\s+', '-', sanitized)
    return sanitized[:100]

# --- Authentication Decorator ---
def token_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.method == 'OPTIONS':
            app.logger.debug(f"OPTIONS request detected in token_required for {request.path}, passing to route handler.")
            return f(*args, **kwargs)

        app.logger.debug(f"Token_required decorator called for: {request.method} {request.path}")
        token = None
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(" ")[1]

        if not token:
            app.logger.warning(f"Token is missing for {request.path}. Auth header: {auth_header}")
            return jsonify({'message': 'Token is missing!'}), 401

        if not SECRET_KEY:
            app.logger.error("SECRET_KEY is not configured on the server.")
            return jsonify({"error": "Server configuration error: missing secret key"}), 500
        
        if not db:
            app.logger.error("Firestore client (db) is not initialized. Cannot authenticate user.")
            return jsonify({"error": "Server error: Database not available"}), 500

        try:
            data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            current_user_id = data.get('user_id')
            if not current_user_id:
                app.logger.warning(f"user_id not found in JWT payload. Data: {data}")
                return jsonify({'message': 'Invalid token payload!'}), 401

            users_ref = db.collection('users')
            user_doc_snapshot = users_ref.document(current_user_id).get()
            if not user_doc_snapshot.exists:
                app.logger.warning(f"User {current_user_id} not found in Firestore during token validation.")
                return jsonify({'message': 'User not found!'}), 401
            
            g.current_user_id = current_user_id
            g.user_doc = user_doc_snapshot.to_dict()
            app.logger.debug(f"User {current_user_id} authenticated successfully for {request.path}")

        except jwt.ExpiredSignatureError:
            app.logger.warning(f"Expired token received for {request.path}")
            return jsonify({'message': 'Token has expired!'}), 401
        except jwt.InvalidTokenError as e:
            app.logger.warning(f"Invalid token received for {request.path}: {e}")
            return jsonify({'message': 'Invalid token!'}), 401
        except Exception as e:
            app.logger.error(f"Unexpected error during token processing for {request.path}: {e}", exc_info=True)
            return jsonify({'message': f'Token processing error: {str(e)}'}), 500
        
        return f(*args, **kwargs)
    return decorated_function

# --- Routes ---

@app.route('/')
@limiter.limit("5 per minute")
def home():
    app.logger.info("Home route accessed.")
    return jsonify({"message": "Welcome to Tiny Tutor AI Backend!"}), 200

@app.route('/test_db')
@limiter.exempt
def test_db_connection():
    app.logger.info("Testing database connection...")
    if not db:
        app.logger.error("Firestore client (db) is not initialized for /test_db.")
        return jsonify({"error": "Firestore client not initialized"}), 500
    try:
        collections = list(db.collections())
        app.logger.info(f"Successfully connected to Firestore. Collections count: {len(collections)}")
        return jsonify({"message": "Successfully connected to Firestore!", "collections_count": len(collections)}), 200
    except Exception as e:
        app.logger.error(f"Failed to connect to Firestore: {e}", exc_info=True)
        return jsonify({"error": f"Failed to connect to Firestore: {str(e)}"}), 500

@app.route('/auth/signup', methods=['POST', 'OPTIONS']) # MODIFIED ROUTE
@limiter.limit("5 per hour")
def signup():
    if request.method == 'OPTIONS':
        app.logger.debug("OPTIONS request to /auth/signup")
        return _build_cors_preflight_response()

    if request.method == 'POST':
        app.logger.info("Signup attempt received.")
        if not db:
            app.logger.error("Firestore client (db) is not initialized for /auth/signup.")
            return jsonify({"error": "Server error: Database not available"}), 500
        try:
            data = request.get_json()
            if not data:
                app.logger.warning("Signup attempt with no JSON data.")
                return jsonify({"error": "Request body must be JSON"}), 400

            email = data.get('email')
            password = data.get('password')
            username = data.get('username', email.split('@')[0])

            if not email or not password:
                app.logger.warning(f"Signup attempt with missing email or password. Email: {email is not None}")
                return jsonify({"error": "Email and password are required"}), 400

            users_ref = db.collection('users')
            existing_user_by_email = users_ref.where('email', '==', email).limit(1).stream()
            if len(list(existing_user_by_email)) > 0:
                app.logger.warning(f"Signup attempt for already existing email: {email}")
                return jsonify({"error": "Email already exists"}), 409

            existing_user_by_username = users_ref.where('username', '==', username).limit(1).stream()
            if len(list(existing_user_by_username)) > 0:
                username_suffix = 1
                original_username = username
                while len(list(users_ref.where('username', '==', username).limit(1).stream())) > 0:
                    username = f"{original_username}{username_suffix}"
                    username_suffix += 1
                    if username_suffix > 100:
                        app.logger.error(f"Could not generate unique username for {original_username}")
                        return jsonify({"error": "Username already exists, could not generate a unique one."}), 409

            hashed_password = generate_password_hash(password)
            user_id = users_ref.document().id

            user_data = {
                'id': user_id,
                'email': email,
                'username': username,
                'password_hash': hashed_password,
                'created_at': firestore.SERVER_TIMESTAMP,
                'last_login_at': None,
                'explored_words': [],
                'daily_streaks': [],
                'current_live_streak': {'score': 0, 'last_word_at': None, 'words_in_streak': []},
                'preferences': {'learning_mode': 'general'}
            }
            users_ref.document(user_id).set(user_data)
            app.logger.info(f"User {email} (ID: {user_id}) signed up successfully.")
            return jsonify({"message": "User created successfully", "userId": user_id, "username": username}), 201

        except Exception as e:
            app.logger.error(f"Error during signup: {e}", exc_info=True)
            return jsonify({"error": f"An unexpected error occurred: {str(e)}"}), 500
    return jsonify({"error": "Method not allowed"}), 405


@app.route('/auth/login', methods=['POST', 'OPTIONS']) # MODIFIED ROUTE
@limiter.limit("10 per hour")
def login():
    if request.method == 'OPTIONS':
        app.logger.debug("OPTIONS request to /auth/login")
        return _build_cors_preflight_response()
    if request.method == 'POST':
        app.logger.info("Login attempt received.")
        if not db:
            app.logger.error("Firestore client (db) is not initialized for /auth/login.")
            return jsonify({"error": "Server error: Database not available"}), 500
        try:
            data = request.get_json()
            if not data:
                return jsonify({"error": "Request body must be JSON"}), 400

            email = data.get('email')
            password = data.get('password')

            if not email or not password:
                return jsonify({"error": "Email and password are required"}), 400

            users_ref = db.collection('users')
            query_result = list(users_ref.where('email', '==', email).limit(1).stream())

            if not query_result:
                app.logger.warning(f"Login attempt for non-existent email: {email}")
                return jsonify({"error": "Invalid credentials"}), 401

            user_doc_snapshot = query_result[0]
            user_data = user_doc_snapshot.to_dict()

            if not check_password_hash(user_data.get('password_hash', ''), password):
                app.logger.warning(f"Invalid password for email: {email}")
                return jsonify({"error": "Invalid credentials"}), 401

            if not SECRET_KEY:
                app.logger.error("SECRET_KEY is not configured on the server for login.")
                return jsonify({"error": "Server configuration error"}), 500

            user_doc_snapshot.reference.update({'last_login_at': firestore.SERVER_TIMESTAMP})

            token_payload = {
                'user_id': user_doc_snapshot.id,
                'email': user_data['email'],
                'username': user_data.get('username'),
                'exp': datetime.now(timezone.utc) + timedelta(hours=24)
            }
            token = jwt.encode(token_payload, SECRET_KEY, algorithm="HS256")
            
            app.logger.info(f"User {email} (ID: {user_doc_snapshot.id}) logged in successfully.")
            return jsonify({
                "message": "Login successful",
                "token": token,
                "userId": user_doc_snapshot.id,
                "username": user_data.get('username'),
                "email": user_data.get('email')
            }), 200

        except Exception as e:
            app.logger.error(f"Error during login: {e}", exc_info=True)
            return jsonify({"error": f"An unexpected error occurred: {str(e)}"}), 500
    return jsonify({"error": "Method not allowed"}), 405


@app.route('/users/profile', methods=['GET', 'OPTIONS'])
@token_required
def get_user_profile():
    if request.method == 'OPTIONS':
        app.logger.debug("OPTIONS request to /users/profile")
        return _build_cors_preflight_response()
    if request.method == 'GET':
        current_user_id = getattr(g, 'current_user_id', None)
        app.logger.info(f"Fetching profile for user ID: {current_user_id}")
        if not db:
            app.logger.error("Firestore client (db) is not initialized for /users/profile.")
            return jsonify({"error": "Server error: Database not available"}), 500
        try:
            user_ref = db.collection('users').document(current_user_id)
            user_doc = user_ref.get()
            if user_doc.exists:
                user_data = user_doc.to_dict()
                profile_data = {
                    key: value for key, value in user_data.items()
                    if key != 'password_hash'
                }
                if 'created_at' in profile_data and isinstance(profile_data['created_at'], datetime):
                    profile_data['created_at'] = profile_data['created_at'].isoformat()
                if 'last_login_at' in profile_data and isinstance(profile_data['last_login_at'], datetime):
                    profile_data['last_login_at'] = profile_data['last_login_at'].isoformat()
                
                if 'explored_words' in profile_data and isinstance(profile_data['explored_words'], list):
                    for item in profile_data['explored_words']:
                        if 'last_explored_at' in item and isinstance(item['last_explored_at'], datetime):
                            item['last_explored_at'] = item['last_explored_at'].isoformat()
                        if 'quiz_progress' in item and isinstance(item['quiz_progress'], list):
                            for attempt in item['quiz_progress']:
                                if 'timestamp' in attempt and isinstance(attempt['timestamp'], datetime):
                                    attempt['timestamp'] = attempt['timestamp'].isoformat()
                
                if 'daily_streaks' in profile_data and isinstance(profile_data['daily_streaks'], list):
                     for streak_item in profile_data['daily_streaks']:
                        if 'completed_at' in streak_item and isinstance(streak_item['completed_at'], datetime):
                            streak_item['completed_at'] = streak_item['completed_at'].isoformat()

                if 'current_live_streak' in profile_data and isinstance(profile_data['current_live_streak'], dict):
                    live_streak = profile_data['current_live_streak']
                    if 'last_word_at' in live_streak and isinstance(live_streak['last_word_at'], datetime):
                        live_streak['last_word_at'] = live_streak['last_word_at'].isoformat()

                app.logger.debug(f"Returning profile for user {current_user_id}")
                return jsonify(profile_data), 200
            else:
                app.logger.warning(f"User profile not found for ID: {current_user_id} in /users/profile")
                return jsonify({"error": "User not found"}), 404
        except Exception as e:
            app.logger.error(f"Error fetching user profile for {current_user_id}: {e}", exc_info=True)
            return jsonify({"error": f"An error occurred: {str(e)}"}), 500
    return jsonify({"error": "Method not allowed"}), 405


@app.route('/users/update_username', methods=['POST', 'OPTIONS'])
@token_required
def update_username():
    if request.method == 'OPTIONS':
        app.logger.debug("OPTIONS request to /users/update_username")
        return _build_cors_preflight_response()
    if request.method == 'POST':
        current_user_id = getattr(g, 'current_user_id', None)
        app.logger.info(f"Username update attempt for user ID: {current_user_id}")

        if not db:
            app.logger.error("Firestore client (db) is not initialized for /users/update_username.")
            return jsonify({"error": "Server error: Database not available"}), 500
        try:
            data = request.get_json()
            if not data:
                return jsonify({"error": "Request body must be JSON"}), 400
            
            new_username = data.get('newUsername')
            if not new_username or not isinstance(new_username, str) or len(new_username.strip()) < 3:
                return jsonify({"error": "New username must be a string and at least 3 characters long"}), 400
            
            new_username = new_username.strip()

            users_ref = db.collection('users')
            query = users_ref.where('username', '==', new_username).limit(1).stream()
            existing_user = next(query, None)

            if existing_user and existing_user.id != current_user_id:
                return jsonify({"error": "Username already taken"}), 409

            user_ref = users_ref.document(current_user_id)
            user_ref.update({'username': new_username})
            app.logger.info(f"Username updated successfully for user {current_user_id} to {new_username}")
            return jsonify({"message": "Username updated successfully", "newUsername": new_username}), 200
        except Exception as e:
            app.logger.error(f"Error updating username for user {current_user_id}: {e}", exc_info=True)
            return jsonify({"error": f"An error occurred: {str(e)}"}), 500
    return jsonify({"error": "Method not allowed"}), 405


# --- Gemini Model Helper ---
def get_gemini_model(model_name="gemini-1.5-flash-latest"):
    if not GOOGLE_GEMINI_API_KEY:
        app.logger.error("GOOGLE_GEMINI_API_KEY not set. Cannot access Gemini model.")
        return None
    try:
        model = genai.GenerativeModel(model_name)
        return model
    except Exception as e:
        app.logger.error(f"Error initializing Gemini model '{model_name}': {e}", exc_info=True)
        return None

# --- Word Exploration Routes ---
@app.route('/words/<word>/<mode>', methods=['GET', 'OPTIONS'])
@limiter.limit("30 per hour")
@token_required
def get_word_content(word, mode):
    if request.method == 'OPTIONS':
        app.logger.debug(f"OPTIONS request to /words/{word}/{mode}")
        return _build_cors_preflight_response()
    if request.method == 'GET':
        current_user_id = getattr(g, 'current_user_id', None)
        app.logger.info(f"Request for word '{word}', mode '{mode}' by user {current_user_id}")

        if not db:
            app.logger.error("Firestore client (db) is not initialized for /words/<word>/<mode>.")
            return jsonify({"error": "Server error: Database not available"}), 500

        sanitized_word = get_sanitized_word_id(word)
        user_ref = db.collection('users').document(current_user_id)
        
        content_data = {"word": word, "mode": mode, "content": None, "error": None}
        
        try:
            model = get_gemini_model()
            if not model:
                return jsonify({"error": "AI model not available"}), 503

            prompt = ""
            if mode == 'explain':
                prompt = f"Explain the meaning of the word '{word}' in a clear and concise way, suitable for a general audience. Provide one example sentence using the word."
            elif mode == 'story':
                prompt = f"Write a very short story (2-3 paragraphs) that prominently features and helps to understand the meaning of the word '{word}'."
            elif mode == 'image_prompt':
                prompt = f"Create a concise, descriptive prompt for an AI image generator to visually represent the core meaning or concept of the word '{word}'. The prompt should be suitable for models like DALL-E or Midjourney. Focus on key visual elements."
            elif mode == 'fact':
                prompt = f"Provide one interesting and verifiable fact related to the word '{word}' or its concept."
            elif mode == 'quiz':
                prompt = f"""Generate 3 multiple-choice quiz questions to test understanding of the word '{word}'.
                For each question, provide:
                1. The question text.
                2. Four options (A, B, C, D).
                3. The correct answer (A, B, C, or D).
                Format the output as a JSON array of objects, where each object has "question", "options" (an array of 4 strings), and "correctAnswer" (a string like "A").
                Example for a different word:
                [
                    {{"question": "What is a synonym for 'ephemeral'?", "options": ["Lasting forever", "Short-lived", "Very important", "Commonplace"], "correctAnswer": "B"}},
                    {{"question": "Which sentence uses 'ephemeral' correctly?", "options": ["The ephemeral nature of trends means they change quickly.", "He built an ephemeral house of stone.", "Their love was ephemeral and lasted a lifetime.", "Ephemeral knowledge is passed down for generations."], "correctAnswer": "A"}},
                    {{"question": "An ephemeral feeling is one that:", "options": ["Is very strong", "Is confusing", "Doesn't last long", "Is always negative"], "correctAnswer": "C"}}
                ]
                Now, generate for the word '{word}'."""
                generation_config = genai.types.GenerationConfig(response_mime_type="application/json")
                response = model.generate_content(prompt, generation_config=generation_config)
                
            else:
                app.logger.warning(f"Invalid mode '{mode}' requested for word '{word}'.")
                return jsonify({"error": "Invalid mode"}), 400

            if mode != 'quiz':
                response = model.generate_content(prompt)
            
            if response and response.candidates:
                if mode == 'quiz':
                    try:
                        quiz_data_str = response.text
                        app.logger.debug(f"Raw quiz data string from Gemini for '{word}': {quiz_data_str}")
                        
                        match = re.search(r'```json\s*([\s\S]*?)\s*```', quiz_data_str)
                        if match:
                            quiz_data_str = match.group(1)
                        
                        quiz_questions = json.loads(quiz_data_str)
                        
                        if not isinstance(quiz_questions, list) or \
                           not all(isinstance(q, dict) and 'question' in q and 'options' in q and 'correctAnswer' in q for q in quiz_questions):
                            app.logger.error(f"Quiz data for '{word}' has incorrect structure: {quiz_questions}")
                            raise ValueError("Quiz data has incorrect structure")
                        
                        content_data["content"] = quiz_questions
                        app.logger.info(f"Successfully generated quiz for '{word}'.")
                    except (json.JSONDecodeError, ValueError) as e:
                        app.logger.error(f"Failed to parse or validate quiz JSON for '{word}': {e}. Raw response: {response.text}", exc_info=True)
                        content_data["error"] = "Failed to generate valid quiz content."
                        content_data["content"] = None
                        return jsonify({"error": "AI failed to generate valid quiz data. Please try again.", "details": str(e), "raw_response": response.text if response else "No response"}), 500
                    except Exception as e:
                        app.logger.error(f"Unexpected error processing quiz for '{word}': {e}. Raw response: {response.text if response else 'No response'}", exc_info=True)
                        return jsonify({"error": "An unexpected error occurred while generating the quiz.", "details": str(e)}), 500

                else:
                    content_data["content"] = response.text
                    app.logger.info(f"Successfully generated content for word '{word}', mode '{mode}'.")
            else:
                app.logger.warning(f"No content generated by AI for word '{word}', mode '{mode}'. Response: {response}")
                content_data["error"] = "AI could not generate content for this request."
                return jsonify({"error": "AI failed to generate content. Please try again."}), 502


            user_doc_data = getattr(g, 'user_doc', user_ref.get().to_dict())
            explored_words = user_doc_data.get('explored_words', [])
            word_entry_idx = next((i for i, ew in enumerate(explored_words) if ew.get('id') == sanitized_word), -1)
            
            current_time_iso = datetime.now(timezone.utc).isoformat()

            if word_entry_idx != -1:
                if mode not in explored_words[word_entry_idx].get('modes_generated', []):
                    explored_words[word_entry_idx].setdefault('modes_generated', []).append(mode)
                explored_words[word_entry_idx]['last_explored_at'] = current_time_iso
            else:
                explored_words.append({
                    'id': sanitized_word,
                    'word': word,
                    'last_explored_at': current_time_iso,
                    'modes_generated': [mode],
                    'is_favorite': False,
                    'quiz_progress': []
                })
            
            user_ref.update({'explored_words': explored_words})
            app.logger.debug(f"User's explored words updated for '{word}', mode '{mode}'.")
            
            return jsonify(content_data), 200

        except genai.types.generation_types.BlockedPromptException as bpe:
            app.logger.warning(f"Prompt blocked by API for word '{word}', mode '{mode}': {bpe}")
            return jsonify({"error": "Request blocked due to safety settings. Please try a different word or mode."}), 400
        except Exception as e:
            app.logger.error(f"Error in /words/{word}/{mode}: {e}", exc_info=True)
            return jsonify({"error": f"An unexpected error occurred: {str(e)}"}), 500
    return jsonify({"error": "Method not allowed"}), 405


@app.route('/words/<word>/favorite', methods=['POST', 'OPTIONS'])
@token_required
def toggle_favorite_word(word):
    if request.method == 'OPTIONS':
        app.logger.debug(f"OPTIONS request to /words/{word}/favorite")
        return _build_cors_preflight_response()
    if request.method == 'POST':
        current_user_id = getattr(g, 'current_user_id', None)
        app.logger.info(f"Toggling favorite status for word '{word}' by user {current_user_id}")

        if not db:
            app.logger.error("Firestore client (db) is not initialized for /words/<word>/favorite.")
            return jsonify({"error": "Server error: Database not available"}), 500

        sanitized_word = get_sanitized_word_id(word)
        user_ref = db.collection('users').document(current_user_id)

        try:
            user_doc_data = getattr(g, 'user_doc', user_ref.get().to_dict())
            explored_words = user_doc_data.get('explored_words', [])
            word_entry_idx = next((i for i, ew in enumerate(explored_words) if ew.get('id') == sanitized_word), -1)
            
            current_time_iso = datetime.now(timezone.utc).isoformat()
            is_favorite_now = False

            if word_entry_idx != -1:
                current_is_favorite = explored_words[word_entry_idx].get('is_favorite', False)
                explored_words[word_entry_idx]['is_favorite'] = not current_is_favorite
                explored_words[word_entry_idx]['last_explored_at'] = current_time_iso
                is_favorite_now = not current_is_favorite
            else:
                explored_words.append({
                    'id': sanitized_word,
                    'word': word,
                    'last_explored_at': current_time_iso,
                    'modes_generated': [],
                    'is_favorite': True,
                    'quiz_progress': []
                })
                is_favorite_now = True
            
            user_ref.update({'explored_words': explored_words})
            app.logger.info(f"Word '{word}' favorite status set to {is_favorite_now} for user {current_user_id}.")
            return jsonify({"message": "Favorite status updated", "word": word, "is_favorite": is_favorite_now, "explored_words": explored_words}), 200

        except Exception as e:
            app.logger.error(f"Error toggling favorite for word '{word}': {e}", exc_info=True)
            return jsonify({"error": f"An unexpected error occurred: {str(e)}"}), 500
    return jsonify({"error": "Method not allowed"}), 405


@app.route('/words/<word>/quiz/attempt', methods=['POST', 'OPTIONS'])
@token_required
def save_quiz_attempt(word):
    if request.method == 'OPTIONS':
        app.logger.debug(f"OPTIONS request to /words/{word}/quiz/attempt")
        return _build_cors_preflight_response()
    if request.method == 'POST':
        current_user_id = getattr(g, 'current_user_id', None)
        app.logger.info(f"Saving quiz attempt for word '{word}' by user {current_user_id}")

        if not db:
            app.logger.error("Firestore client (db) is not initialized for /words/<word>/quiz/attempt.")
            return jsonify({"error": "Server error: Database not available"}), 500

        sanitized_word = get_sanitized_word_id(word)
        user_ref = db.collection('users').document(current_user_id)

        try:
            data = request.get_json()
            if not data:
                return jsonify({"error": "Request body must be JSON"}), 400

            question_index = data.get('questionIndex')
            answer = data.get('answer')
            is_correct = data.get('isCorrect')

            if question_index is None or answer is None or is_correct is None:
                return jsonify({"error": "Missing questionIndex, answer, or isCorrect in request"}), 400

            user_doc_data = getattr(g, 'user_doc', user_ref.get().to_dict())
            explored_words = user_doc_data.get('explored_words', [])
            word_entry_idx = next((i for i, ew in enumerate(explored_words) if ew.get('id') == sanitized_word), -1)
            
            current_time_iso = datetime.now(timezone.utc).isoformat()

            if word_entry_idx == -1:
                target_word_entry = {
                    'id': sanitized_word,
                    'word': word,
                    'last_explored_at': current_time_iso,
                    'modes_generated': ['quiz'],
                    'is_favorite': False,
                    'quiz_progress': []
                }
                explored_words.append(target_word_entry)
                word_entry_idx = len(explored_words) -1 
            
            target_word_entry = explored_words[word_entry_idx]
            
            if 'quiz_progress' not in target_word_entry or not isinstance(target_word_entry['quiz_progress'], list):
                target_word_entry['quiz_progress'] = []

            new_attempt = {"question_index": question_index, "answer": answer, "is_correct": is_correct, "timestamp": current_time_iso}
            
            attempt_idx = next((i for i, att in enumerate(target_word_entry["quiz_progress"]) if isinstance(att, dict) and att.get("question_index") == question_index), -1)
            
            if attempt_idx != -1:
                target_word_entry["quiz_progress"][attempt_idx] = new_attempt
            else:
                target_word_entry["quiz_progress"].append(new_attempt)
            
            target_word_entry["quiz_progress"].sort(key=lambda x: x.get('question_index', float('inf')))
            
            target_word_entry["last_explored_at"] = current_time_iso
            if "quiz" not in target_word_entry.get("modes_generated", []): 
                target_word_entry.setdefault("modes_generated", []).append("quiz")
            
            explored_words[word_entry_idx] = target_word_entry
                
            user_ref.update({"explored_words": explored_words})
            app.logger.info(f"Quiz attempt for word '{word}', question {question_index} saved for user {current_user_id}.")
            return jsonify({"message": "Quiz attempt saved", "quiz_progress": target_word_entry["quiz_progress"]}), 200

        except Exception as e:
            app.logger.error(f"Error saving quiz attempt for user '{current_user_id}', word '{sanitized_word}': {e}", exc_info=True)
            return jsonify({"error": f"Failed to save quiz attempt: {str(e)}"}), 500
    return jsonify({"error": "Method not allowed"}), 405

# --- Streak Management ---
@app.route('/users/streak/update', methods=['POST', 'OPTIONS'])
@token_required
def update_streak():
    if request.method == 'OPTIONS':
        return _build_cors_preflight_response()
    if request.method == 'POST':
        current_user_id = getattr(g, 'current_user_id', None)
        app.logger.info(f"Updating streak for user {current_user_id}")
        if not db: return jsonify({"error": "Server error: Database not available"}), 500

        try:
            data = request.get_json()
            word_learned = data.get('word')
            is_correct_quiz_answer = data.get('isCorrectQuizAnswer', False)

            if not word_learned:
                return jsonify({"error": "Word learned is required"}), 400
            
            user_ref = db.collection('users').document(current_user_id)
            user_doc_data = getattr(g, 'user_doc', user_ref.get().to_dict())
            
            live_streak = user_doc_data.get('current_live_streak', {'score': 0, 'last_word_at': None, 'words_in_streak': []})
            daily_streaks_history = user_doc_data.get('daily_streaks', [])
            
            current_time = datetime.now(timezone.utc)
            current_date_str = current_time.strftime('%Y-%m-%d')
            
            reset_live_streak = True
            if live_streak.get('last_word_at'):
                try:
                    last_word_dt = datetime.fromisoformat(live_streak['last_word_at'])
                    if last_word_dt.date() == current_time.date():
                        reset_live_streak = False
                except (ValueError, TypeError):
                    app.logger.warning(f"Invalid last_word_at format for user {current_user_id}: {live_streak.get('last_word_at')}")
            
            if reset_live_streak:
                if live_streak.get('score', 0) > 0 and live_streak.get('last_word_at'):
                    try:
                        old_streak_dt = datetime.fromisoformat(live_streak['last_word_at'])
                        old_streak_date_str = old_streak_dt.strftime('%Y-%m-%d')
                        if old_streak_date_str != current_date_str:
                            existing_daily_idx = next((i for i, ds in enumerate(daily_streaks_history) if ds.get('date') == old_streak_date_str), -1)
                            if existing_daily_idx != -1:
                                if live_streak['score'] > daily_streaks_history[existing_daily_idx].get('score',0):
                                     daily_streaks_history[existing_daily_idx]['score'] = live_streak['score']
                                     daily_streaks_history[existing_daily_idx]['words'] = list(set(daily_streaks_history[existing_daily_idx].get('words',[]) + live_streak.get('words_in_streak',[])))
                                     daily_streaks_history[existing_daily_idx]['completed_at'] = old_streak_dt.isoformat()
                            else:
                                daily_streaks_history.append({
                                    'id': db.collection('_').document().id,
                                    'date': old_streak_date_str,
                                    'score': live_streak['score'],
                                    'words': live_streak.get('words_in_streak', []),
                                    'completed_at': old_streak_dt.isoformat()
                                })
                    except Exception as e:
                        app.logger.error(f"Error processing old streak for user {current_user_id}: {e}")

                live_streak['score'] = 0
                live_streak['words_in_streak'] = []

            if word_learned not in live_streak.get('words_in_streak', []):
                 live_streak['score'] += 1
                 live_streak.setdefault('words_in_streak', []).append(word_learned)

            live_streak['last_word_at'] = current_time.isoformat()

            user_ref.update({
                'current_live_streak': live_streak,
                'daily_streaks': daily_streaks_history
            })
            app.logger.info(f"Streak updated for user {current_user_id}. Live streak score: {live_streak['score']}")
            return jsonify({"message": "Streak updated", "current_live_streak": live_streak}), 200

        except Exception as e:
            app.logger.error(f"Error updating streak for user {current_user_id}: {e}", exc_info=True)
            return jsonify({"error": f"An unexpected error occurred: {str(e)}"}), 500
    return jsonify({"error": "Method not allowed"}), 405


def _build_cors_preflight_response():
    response = jsonify({'message': 'CORS preflight successful'})
    response.headers.add("Access-Control-Allow-Origin", request.headers.get("Origin", "*"))
    response.headers.add('Access-Control-Allow-Headers', request.headers.get("Access-Control-Request-Headers", "Content-Type,Authorization"))
    response.headers.add('Access-Control-Allow-Methods', request.headers.get("Access-Control-Request-Method", "GET,POST,PUT,DELETE,OPTIONS"))
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    response.headers.add('Access-Control-Max-Age', '86400')
    app.logger.debug(f"Built manual CORS preflight response for {request.path}. Origin: {response.headers.get('Access-Control-Allow-Origin')}")
    return response, 200

@app.route('/<path:u_path>', methods=['OPTIONS'])
@app.route('/', methods=['OPTIONS'], defaults={'u_path': ''})
def options_handler(u_path):
    app.logger.debug(f"Global OPTIONS handler caught request for path: {u_path if u_path else '/'}")
    return _build_cors_preflight_response()


@app.errorhandler(404)
def not_found_error(error):
    app.logger.warning(f"404 Not Found: {request.url} - {error}")
    return jsonify({"error": "Not Found", "message": str(error)}), 404

@app.errorhandler(405)
def method_not_allowed_error(error):
    app.logger.warning(f"405 Method Not Allowed: {request.method} for {request.url} - {error}")
    return jsonify({"error": "Method Not Allowed", "message": str(error)}), 405
    
@app.errorhandler(500)
def internal_error(error):
    app.logger.error(f"500 Internal Server Error: {request.url} - {error}", exc_info=True)
    return jsonify({"error": "Internal Server Error", "message": "An unexpected error occurred on the server."}), 500

@app.errorhandler(Exception)
def unhandled_exception(e):
    app.logger.error(f"Unhandled Exception: {request.url} - {e}", exc_info=True)
    return jsonify({"error": "An Unexpected Application Error Occurred", "message": "The server encountered an unexpected condition."}), 500


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5001))
    app.logger.info(f"Application ready to be served (typically by Gunicorn on Render on port {port})")
