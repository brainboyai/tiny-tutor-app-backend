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
import logging # Added for more verbose logging

load_dotenv()

app = Flask(__name__)

# --- Logging Configuration ---
# Ensure Gunicorn logs at a level that shows app.logger.debug messages.
# You might need to configure Gunicorn's --log-level if deploying with it.
# For Render.com, Gunicorn is common.
app.logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler() # Logs to stderr, which Render should pick up
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
if not app.logger.handlers: # Avoid adding multiple handlers during reloads
    app.logger.addHandler(handler)

app.logger.info("Flask app starting up...")

# --- CORS Configuration ---
# This is your original configuration with some explicit additions
CORS(app,
     resources={r"/*": {"origins": [
         "https://tiny-tutor-app-frontend.onrender.com",
         "http://localhost:5173",
         "http://127.0.0.1:5173"
     ]}},
     supports_credentials=True,
     expose_headers=["Content-Type", "Authorization"],
     # Added common preflight request headers to be explicit
     allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Access-Control-Request-Method", "Access-Control-Request-Headers", "Origin"],
     # Explicitly list methods, including OPTIONS
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
        if not firebase_admin._apps: # Check if already initialized
            firebase_admin.initialize_app(cred)
            app.logger.info("Firebase Admin SDK initialized successfully.")
        else:
            app.logger.info("Firebase Admin SDK already initialized.")
        db = firestore.client()
    except Exception as e:
        app.logger.error(f"Failed to initialize Firebase Admin SDK: {e}", exc_info=True)
        # Depending on your app's needs, you might want to exit or handle this gracefully
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
    # This will log details for EVERY request, helping to see if OPTIONS requests arrive
    app.logger.debug(f"Incoming Request -- Method: {request.method}, Path: {request.path}")
    app.logger.debug(f"Request Headers: {dict(request.headers)}")
    if request.method == 'OPTIONS':
        app.logger.debug("Handling OPTIONS preflight request explicitly (or letting Flask-CORS handle it).")
    # To see request body (be careful with large bodies in production logging):
    # if request.data:
    #    app.logger.debug(f"Request Body: {request.get_data(as_text=True)}")


# --- Rate Limiter (Example, adjust as needed) ---
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://" # Consider a persistent store like Redis for production
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
                app.logger.warning("Malformed Authorization header. Token missing.")
                return jsonify({"error": "Malformed token"}), 401

        if not token:
            app.logger.warning("Token is missing for protected route.")
            return jsonify({"error": "Token is missing"}), 401

        try:
            data = jwt.decode(token, current_app.config['JWT_SECRET_KEY'], algorithms=["HS256"])
            current_user_id = data['user_id']
            # Optionally, load user details here if needed for every request
            # g.current_user_id = current_user_id # Using Flask's g object
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
@limiter.limit("5 per hour") # Example rate limit for signup
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
        if len(password) < 6: # Example: Basic password policy
            app.logger.warning(f"Signup failed for '{email}': Password too short.")
            return jsonify({"error": "Password must be at least 6 characters long"}), 400

        users_ref = db.collection('users')
        # Check if email or username already exists
        if users_ref.where('email', '==', email).limit(1).get():
            app.logger.warning(f"Signup failed: Email '{email}' already exists.")
            return jsonify({"error": "Email already exists"}), 409
        if users_ref.where('username_lowercase', '==', username.lower()).limit(1).get(): # Store and check lowercase username
            app.logger.warning(f"Signup failed: Username '{username}' already exists.")
            return jsonify({"error": "Username already exists"}), 409

        hashed_password = generate_password_hash(password)
        user_data = {
            'email': email,
            'username': username,
            'username_lowercase': username.lower(), # For case-insensitive username checks
            'password_hash': hashed_password,
            'tier': 'free', # Default tier
            'created_at': firestore.SERVER_TIMESTAMP,
            'total_words_explored': 0,
            'explored_words': [], # Initialize as empty list
            'favorite_words': [], # Initialize as empty list
            'streak_history': []  # Initialize as empty list
        }
        user_ref = users_ref.document()
        user_ref.set(user_data)
        user_id = user_ref.id # Get the auto-generated ID

        app.logger.info(f"User '{username}' ({email}) signed up successfully. User ID: {user_id}")
        # Optionally, log the user in immediately by creating a token
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
@limiter.limit("10 per minute") # Example rate limit for login
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
    if not db:
        app.logger.error("Database not initialized. Cannot fetch profile.")
        return jsonify({"error": "Server configuration error: Database not available"}), 503
    try:
        user_ref = db.collection('users').document(current_user_id)
        user_doc = user_ref.get()
        if user_doc.exists:
            user_data = user_doc.to_dict()
            # Ensure sensitive data like password_hash is not returned
            profile_data = {
                "id": user_doc.id,
                "username": user_data.get("username"),
                "email": user_data.get("email"),
                "tier": user_data.get("tier", "free"),
                "total_words_explored": user_data.get("total_words_explored", 0),
                "explored_words": user_data.get("explored_words", []),
                "favorite_words": user_data.get("favorite_words", []), # This should be derived or managed separately
                "streak_history": user_data.get("streak_history", []),
                "created_at": user_data.get("created_at").isoformat() if user_data.get("created_at") else None
            }
            # Derive favorite_words list from explored_words if not stored separately
            if not profile_data["favorite_words"] and profile_data["explored_words"]:
                profile_data["favorite_words"] = [word for word in profile_data["explored_words"] if word.get("is_favorite")]

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
    if not db:
        app.logger.error("Database not initialized. Cannot manage favorites.")
        return jsonify({"error": "Server configuration error"}), 503

    user_ref = db.collection('users').document(current_user_id)
    word_history_collection_ref = user_ref.collection('word_history')
    word_doc_ref = word_history_collection_ref.document(word_id) # word_id is the sanitized word

    try:
        word_doc = word_doc_ref.get()
        if not word_doc.exists:
             app.logger.warning(f"Word '{word_id}' not found in history for user '{current_user_id}' to manage favorite.")
             # If it doesn't exist in history, it can't be a favorite yet in this model.
             # Or, you might allow adding directly if your model supports it.
             return jsonify({"error": "Word not explored yet, cannot manage favorite status."}), 404

        if request.method == 'POST': # Add to favorites
            word_doc_ref.update({"is_favorite": True, "last_explored_at": firestore.SERVER_TIMESTAMP})
            app.logger.info(f"Word '{word_id}' added to favorites for user '{current_user_id}'.")
            return jsonify({"message": "Word added to favorites"}), 200
        elif request.method == 'DELETE': # Remove from favorites
            word_doc_ref.update({"is_favorite": False, "last_explored_at": firestore.SERVER_TIMESTAMP})
            app.logger.info(f"Word '{word_id}' removed from favorites for user '{current_user_id}'.")
            return jsonify({"message": "Word removed from favorites"}), 200
    except Exception as e:
        app.logger.error(f"Error managing favorite for user '{current_user_id}', word '{word_id}': {e}", exc_info=True)
        return jsonify({"error": "Failed to update favorite status"}), 500


# --- Word Interaction Routes ---
def get_word_content_from_genai(word, mode):
    app.logger.info(f"Fetching GenAI content for word: '{word}', mode: '{mode}'")
    if not google_api_key or not genai:
        app.logger.warning("Google API key or GenAI client not configured. Cannot fetch from GenAI.")
        return "Generative AI service is not available."

    model = genai.GenerativeModel('gemini-2.0-flash') # Or your preferred model
    prompt = ""
    if mode == 'explain':
        prompt = f"Explain the word '{word}' in a clear and concise way, suitable for a general audience. Provide etymology if interesting."
    elif mode == 'fact':
        prompt = f"Tell me an interesting and verifiable fact about '{word}'."
    elif mode == 'deep_dive':
        prompt = f"Provide a deep dive into the concept of '{word}'. Include its history, applications, and related concepts. Aim for about 200-300 words."
    elif mode == 'quiz':
        # For quiz, we expect a structured response.
        # This prompt needs to be carefully crafted for the model to return structured JSON.
        # It's better to use the JSON mode of the API if available and reliable.
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
            # Using generationConfig for JSON output
            generation_config = genai.types.GenerationConfig(
                response_mime_type="application/json",
            )
            response = model.generate_content(prompt, generation_config=generation_config)
            app.logger.debug(f"GenAI Quiz raw response for '{word}': {response.text}")
            # The response.text should be a JSON string.
            quiz_data = json.loads(response.text) # Parse the JSON string
            # Validate structure
            if not all(k in quiz_data for k in ["question", "options", "correct_answer_key"]):
                app.logger.error(f"GenAI Quiz JSON for '{word}' missing required keys. Data: {quiz_data}")
                raise ValueError("Quiz data from AI is malformed (missing keys).")
            if not isinstance(quiz_data["options"], dict) or len(quiz_data["options"]) != 4:
                 app.logger.error(f"GenAI Quiz JSON for '{word}' options are malformed. Data: {quiz_data}")
                 raise ValueError("Quiz data from AI is malformed (options).")

            return [quiz_data] # Return as a list containing one quiz object, as per frontend expectation
        except json.JSONDecodeError as je:
            app.logger.error(f"GenAI Quiz JSONDecodeError for '{word}': {je}. Response text: {response.text if 'response' in locals() else 'N/A'}")
            return "Failed to generate quiz: AI returned invalid JSON."
        except ValueError as ve: # Catch our custom validation errors
            app.logger.error(f"GenAI Quiz ValueError for '{word}': {ve}")
            return f"Failed to generate quiz: {ve}"
        except Exception as e:
            app.logger.error(f"GenAI Quiz generation error for '{word}': {e}", exc_info=True)
            return "Failed to generate quiz content."


    if not prompt:
        return "Invalid mode selected."

    try:
        response = model.generate_content(prompt)
        app.logger.debug(f"GenAI text response for '{word}', mode '{mode}': {response.text[:100]}...") # Log snippet
        return response.text
    except Exception as e:
        app.logger.error(f"GenAI content generation error for word '{word}', mode '{mode}': {e}", exc_info=True)
        return f"Error generating content: {e}"


@app.route('/words/<word>/<mode>', methods=['GET'])
@token_required
@limiter.limit("30 per minute") # Rate limit for word content fetching
def get_word_info(current_user_id, word, mode):
    app.logger.info(f"User '{current_user_id}' requesting info for word: '{word}', mode: '{mode}'")
    if not db:
        app.logger.error("Database not initialized. Cannot process word info request.")
        return jsonify({"error": "Server configuration error"}), 503

    sanitized_word = re.sub(r'[^a-zA-Z0-9\s-]', '', word).strip().lower()
    if not sanitized_word:
        app.logger.warning("Invalid word provided for fetching info.")
        return jsonify({"error": "Invalid word"}), 400

    valid_modes = ['explain', 'image', 'fact', 'quiz', 'deep_dive']
    if mode not in valid_modes:
        app.logger.warning(f"Invalid mode '{mode}' requested for word '{sanitized_word}'.")
        return jsonify({"error": "Invalid mode"}), 400

    user_ref = db.collection('users').document(current_user_id)
    word_history_collection_ref = user_ref.collection('word_history')
    word_doc_ref = word_history_collection_ref.document(sanitized_word)

    try:
        word_doc = word_doc_ref.get()
        content = None
        source = "cache"

        if word_doc.exists:
            word_data = word_doc.to_dict()
            if mode in word_data.get('content', {}) and word_data['content'][mode]:
                content = word_data['content'][mode]
                app.logger.info(f"Found cached content for '{sanitized_word}', mode '{mode}'.")
            # Check if modes_generated list exists and if the current mode is in it
            elif mode in word_data.get('modes_generated', []):
                 # This case implies content was generated but might be null/empty, or was cleared.
                 # For now, let's assume if mode is in modes_generated, content should exist or be re-fetched.
                 # If content is None here, it means we should re-fetch.
                 app.logger.info(f"Mode '{mode}' was previously generated for '{sanitized_word}' but content is missing/null. Will re-fetch.")
                 pass # Fall through to fetch

        if content is None and mode == 'image': # Image generation is special
            # For images, we might just trigger generation and return a message
            # This part needs to be implemented if you have an image generation service
            app.logger.info(f"Image mode for '{sanitized_word}'. Image generation not fully implemented in this example.")
            # Simulate triggering image generation
            # In a real scenario, you'd call an async task or an image generation API
            # For now, let's assume it's handled by GenAI or another service.
            # If you want to use GenAI for image descriptions that then get turned into images by frontend:
            # content = get_word_content_from_genai(sanitized_word, "image_description_prompt")
            # For now, returning a placeholder or triggering a GenAI image if supported
            return jsonify({"message": "Image generation for this word is not yet supported or is in progress."}), 202 # Accepted


        if content is None: # Fetch from GenAI if not cached or image mode
            source = "new"
            app.logger.info(f"No cache for '{sanitized_word}', mode '{mode}'. Fetching from GenAI.")
            content = get_word_content_from_genai(sanitized_word, mode)
            if "Error generating content" in content or "Failed to generate" in content or "service is not available" in content:
                 app.logger.error(f"Failed to get content from GenAI for '{sanitized_word}', mode '{mode}': {content}")
                 return jsonify({"error": content}), 500


        # Update Firestore document
        word_update_data = {
            f'content.{mode}': content,
            'last_explored_at': firestore.SERVER_TIMESTAMP,
            'modes_generated': firestore.ArrayUnion([mode]) # Add mode to list of generated modes
        }
        if not word_doc.exists:
            word_initial_data = {
                'word': word, # Original word
                'id': sanitized_word,
                'first_explored_at': firestore.SERVER_TIMESTAMP,
                'is_favorite': False,
                'quiz_progress': [],
                'content': {mode: content},
                'modes_generated': [mode],
                'last_explored_at': firestore.SERVER_TIMESTAMP
            }
            word_doc_ref.set(word_initial_data)
            app.logger.info(f"New word history entry created for '{sanitized_word}', user '{current_user_id}'.")
        else:
            word_doc_ref.update(word_update_data)
            app.logger.info(f"Word history entry updated for '{sanitized_word}', mode '{mode}', user '{current_user_id}'.")

        # Update total words explored count - this could be optimized
        # Consider transactions or batched writes if this becomes a bottleneck
        user_doc_snapshot = user_ref.get(["total_words_explored", "explored_words"])
        if user_doc_snapshot.exists:
            user_data = user_doc_snapshot.to_dict()
            current_explored_words = user_data.get("explored_words", [])
            
            # Check if word_id (sanitized_word) is already in the list of explored word objects
            word_already_in_main_list = any(entry.get("id") == sanitized_word for entry in current_explored_words)

            if not word_already_in_main_list:
                new_word_entry_for_list = {
                    "id": sanitized_word,
                    "word": word, # original word
                    "first_explored_at": datetime.now(timezone.utc).isoformat(), # Or use server timestamp if preferred
                    "last_explored_at": datetime.now(timezone.utc).isoformat(),
                    "is_favorite": False # Initial favorite status
                }
                user_ref.update({
                    "total_words_explored": firestore.Increment(1),
                    "explored_words": firestore.ArrayUnion([new_word_entry_for_list])
                })
                app.logger.info(f"Incremented total_words_explored for user '{current_user_id}'.")


        return jsonify({"word": sanitized_word, "mode": mode, "content": content, "source": source}), 200

    except Exception as e:
        app.logger.error(f"Error fetching info for word '{sanitized_word}', mode '{mode}', user '{current_user_id}': {e}", exc_info=True)
        return jsonify({"error": f"Failed to get information for '{word}': {e}"}), 500


@app.route('/words/<word>/quiz/attempt', methods=['POST'])
@token_required
def save_quiz_attempt(current_user_id, word):
    app.logger.info(f"User '{current_user_id}' saving quiz attempt for word: '{word}'")
    if not db:
        app.logger.error("Database not initialized. Cannot save quiz attempt.")
        return jsonify({"error": "Server configuration error"}), 503

    sanitized_word = re.sub(r'[^a-zA-Z0-9\s-]', '', word).strip().lower()
    if not sanitized_word:
        app.logger.warning("Invalid word provided for saving quiz attempt.")
        return jsonify({"error": "Invalid word"}), 400

    try:
        data = request.get_json()
        question_index = data.get('question_index')
        selected_option_key = data.get('selected_option_key')
        is_correct = data.get('is_correct')

        if not all(isinstance(x, int) for x in [question_index]) or \
           not isinstance(selected_option_key, str) or \
           not isinstance(is_correct, bool):
            app.logger.warning("Invalid quiz attempt data.")
            return jsonify({"error": "Invalid quiz attempt data. Ensure question_index, selected_option_key, and is_correct are provided correctly."}), 400

        user_ref = db.collection('users').document(current_user_id)
        word_history_ref = user_ref.collection('word_history').document(sanitized_word)
        word_doc = word_history_ref.get()

        quiz_progress = []
        if word_doc.exists:
            quiz_progress = word_doc.to_dict().get('quiz_progress', [])
        else:
            # If word history doesn't exist, create it. This might happen if quiz is attempted before other modes.
            app.logger.info(f"Creating new word history for '{sanitized_word}' due to quiz attempt by user '{current_user_id}'.")
            word_history_ref.set({
                'word': word,
                'id': sanitized_word,
                'first_explored_at': firestore.SERVER_TIMESTAMP,
                'last_explored_at': firestore.SERVER_TIMESTAMP,
                'is_favorite': False,
                'content': {},
                'quiz_progress': [], # Will be populated below
                'modes_generated': ['quiz'] # Mark quiz as generated
            })
            # No need to re-fetch word_doc here, quiz_progress is initialized as empty list

        new_attempt = {
            "question_index": question_index,
            "selected_option_key": selected_option_key,
            "is_correct": is_correct,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        attempt_updated = False
        for i, attempt in enumerate(quiz_progress):
            if attempt.get('question_index') == question_index:
                quiz_progress[i] = new_attempt
                attempt_updated = True
                break
        if not attempt_updated:
            quiz_progress.append(new_attempt)

        quiz_progress.sort(key=lambda x: x['question_index']) # Keep attempts sorted

        word_history_ref.update({"quiz_progress": quiz_progress, "last_explored_at": firestore.SERVER_TIMESTAMP})

        app.logger.info(f"Quiz attempt saved for user '{current_user_id}', word '{sanitized_word}', q_idx {question_index}. New progress length: {len(quiz_progress)}")
        return jsonify({"message": "Quiz attempt saved", "quiz_progress": quiz_progress}), 200

    except Exception as e:
        app.logger.error(f"Error saving quiz attempt for user '{current_user_id}', word '{sanitized_word}': {e}", exc_info=True)
        return jsonify({"error": f"Failed to save quiz attempt: {e}"}), 500


if __name__ == '__main__':
    # This is for local development. Render.com will use Gunicorn or another WSGI server.
    port = int(os.environ.get('PORT', 5001)) # Changed default local port to avoid common conflicts
    app.logger.info(f"Starting Flask development server on http://localhost:{port}")
    app.run(debug=True, host='0.0.0.0', port=port) # debug=True is fine for local
