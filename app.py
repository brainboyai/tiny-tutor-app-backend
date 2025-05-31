# app.py
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

load_dotenv()

app = Flask(__name__)

CORS(app,
     resources={r"/*": {"origins": [
         "https://tiny-tutor-app-frontend.onrender.com",
         "http://localhost:5173",
         "http://127.0.0.1:5173"
     ]}},
     supports_credentials=True,
     expose_headers=["Content-Type", "Authorization"],
     allow_headers=["Content-Type", "Authorization", "X-Requested-With"]
)

app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'fallback_secret_key_for_dev_only_change_me')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)

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

gemini_api_key = os.getenv('GEMINI_API_KEY')
if gemini_api_key:
    try:
        genai.configure(api_key=gemini_api_key)
        app.logger.info("Google Gemini API configured successfully.")
    except Exception as e:
        app.logger.error(f"Failed to configure Google Gemini API: {e}")
else:
    app.logger.warning("GEMINI_API_KEY not found. Google Gemini API not configured.")

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://",
)

def sanitize_word_for_id(word: str) -> str:
    if not isinstance(word, str): return "invalid_input"
    sanitized = word.lower()
    sanitized = re.sub(r'\s+', '_', sanitized)
    sanitized = re.sub(r'[^a-z0-9_]', '', sanitized)
    return sanitized if sanitized else "empty_word"

def token_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.method == 'OPTIONS':
            app.logger.info(f"OPTIONS request received for: {request.path}, allowing through for CORS handling.")
            response = current_app.make_default_options_response()
            return response

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
        except jwt.ExpiredSignatureError:
            app.logger.warning(f"Expired token for {request.path}.")
            return jsonify({"error": "Token has expired"}), 401
        except jwt.InvalidTokenError:
            app.logger.warning(f"Invalid token for {request.path}.")
            return jsonify({"error": "Token is invalid"}), 401
        except Exception as e:
            app.logger.error(f"Token validation error for {request.path}: {e}")
            return jsonify({"error": "Token validation failed"}), 401

        return f(current_user_id, *args, **kwargs)
    return decorated_function


@app.route('/')
def home():
    return "Tiny Tutor Backend is running!"

@app.route('/signup', methods=['POST'])
@limiter.limit("5 per hour")
def signup_user():
    if not db: return jsonify({"error": "Database not configured"}), 500
    data = request.get_json()
    if not data: return jsonify({"error": "No input data provided"}), 400
    username = data.get('username', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    if not username or not email or not password: return jsonify({"error": "Username, email, and password are required"}), 400
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
        current_app.logger.error(f"Error during signup for {username}: {e}")
        return jsonify({"error": f"Signup failed: {e}"}), 500


@app.route('/login', methods=['POST'])
@limiter.limit("10 per minute")
def login_user():
    if not db: return jsonify({"error": "Database not configured"}), 500
    data = request.get_json()
    if not data: return jsonify({"error": "No input data provided"}), 400
    identifier = str(data.get('email_or_username', '')).strip()
    password = str(data.get('password', ''))
    if not identifier or not password: return jsonify({"error": "Missing username/email or password"}), 400
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
        current_app.logger.error(f"Login error for '{identifier}': {e}", exc_info=True)
        return jsonify({"error": "Login failed."}), 500

# vvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvv
# START OF MODIFIED SECTION in /generate_explanation
# vvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvv
@app.route('/generate_explanation', methods=['POST', 'OPTIONS'])
@token_required
@limiter.limit("60/hour")
def generate_explanation_route(current_user_id):
    if not db: return jsonify({"error": "Database not configured"}), 500
    if not gemini_api_key: return jsonify({"error": "AI service not configured"}), 500

    data = request.get_json()
    if not data: return jsonify({"error": "No input data provided"}), 400

    word = data.get('word', '').strip()
    mode = data.get('mode', 'explain').strip().lower()
    force_refresh = data.get('refresh_cache', False)
    streak_context_list = data.get('streakContext', []) # Expect list of strings

    if not word: return jsonify({"error": "Word/concept is required"}), 400

    sanitized_word_id = sanitize_word_for_id(word)
    user_word_history_ref = db.collection('users').document(current_user_id).collection('word_history').document(sanitized_word_id)

    try:
        word_doc = user_word_history_ref.get()
        cached_content_from_db = {} # This will hold content from DB, or be updated with generic content
        is_favorite_status = False
        quiz_progress_data = []
        modes_already_generated = []

        if word_doc.exists:
            word_data = word_doc.to_dict()
            cached_content_from_db = word_data.get('generated_content_cache', {})
            is_favorite_status = word_data.get('is_favorite', False)
            quiz_progress_data = word_data.get('quiz_progress', [])
            modes_already_generated = word_data.get('modes_generated', [])

        # Determine if this specific call is for a contextual explanation
        is_contextual_explain_call = mode == 'explain' and bool(streak_context_list)

        # Cache Check Logic:
        # Serve from cache if:
        # 1. It's NOT a contextual explanation call (i.e., it's generic explain or another mode)
        # AND 2. It's NOT a force_refresh request
        # AND 3. The content for the mode exists in the cache
        if not is_contextual_explain_call and not force_refresh and mode in cached_content_from_db:
            current_app.logger.info(f"Serving '{mode}' for '{word}' from cache for user '{current_user_id}'.")
            user_word_history_ref.set({'last_explored_at': firestore.SERVER_TIMESTAMP, 'word': word}, merge=True) # Update last_explored_at
            return jsonify({
                "word": word,
                mode: cached_content_from_db[mode],
                "source": "cache",
                "is_favorite": is_favorite_status,
                "full_cache": cached_content_from_db,
                "quiz_progress": quiz_progress_data,
                "modes_generated": modes_already_generated
            }), 200

        current_app.logger.info(f"Generating '{mode}' for '{word}' (Contextual: {is_contextual_explain_call}, ForceRefresh: {force_refresh}) for user '{current_user_id}'. Context: {streak_context_list if is_contextual_explain_call else 'N/A'}")

        generated_text_content = None # For text-based modes
        quiz_questions_array = [] # For quiz mode
        prompt = ""

        if mode == 'explain':
            if not streak_context_list: # Primary word or generic explain
                primary_word_for_prompt = word
                prompt = f"""Your task is to define '{primary_word_for_prompt}'.
Instructions: Define '{primary_word_for_prompt}' in exactly two sentences using the simplest, most basic, and direct language suitable for a complete beginner with no prior knowledge; focus on fundamental aspects. Within these sentences, embed the maximum number of distinct, foundational sub-topics (key terms, core concepts, related ideas) crucial for deeper understanding; these sub-topics must not be mere synonyms or rephrasing of '{primary_word_for_prompt}'. If '{primary_word_for_prompt}' involves mathematics, physics, chemistry, or similar fields, embed any critical fundamental formulas or equations (using LaTeX, e.g., $E=mc^2$) as sub-topics. Wrap all sub-topics (textual, formulas, equations) in <click>tags</click> (e.g., <click>energy conversion</click>, <click>$A=\pi r^2$</click>). Your response must consist strictly of the two definition sentences containing the embedded clickable sub-topics. Do not include any headers, introductory phrases, or these instructions in your output.
Example of the expected output format: Photosynthesis is a &lt;click>biological process&lt;/click> in &lt;click>plants&lt;/click> and other organisms converting &lt;click>light energy&lt;/click> into &lt;click>chemical energy&lt;/click>, often represented by &lt;click>6CO_2+6H_2O+textLightrightarrowC_6H_12O_6+6O_2&lt;/click>. This process uses &lt;click>carbon dioxide&lt;/click> and &lt;click>water&lt;/click> to produce &lt;click>glucose&lt;/click> (a &lt;click>sugar&lt;/click>) and &lt;click>oxygen&lt;/click>.

"""
            else: # Subsequent word in a streak (contextual)
                current_word_for_prompt = word
                context_string = ", ".join(streak_context_list)
                all_relevant_words_for_reiteration_check = [current_word_for_prompt] + streak_context_list
                reiteration_check_string = ", ".join(all_relevant_words_for_reiteration_check)
                prompt = f"""Your task is to define '{current_word_for_prompt}', specifically considering its context provided by '{context_string}'.
Instructions: Define '{current_word_for_prompt}' in exactly two sentences using the simplest, most basic, and direct language suitable for a complete beginner; focus on its core aspects as they specifically relate to '{context_string}'. Within these sentences, embed the maximum number of distinct, foundational sub-topics (key terms, core concepts, related ideas) crucial for understanding '{current_word_for_prompt}' within this given context. Crucially, these embedded sub-topics must not be a simple reiteration of any words found in '{reiteration_check_string}'. If '{current_word_for_prompt}' (when considered in '{context_string}') involves mathematics, physics, chemistry, or similar fields, embed any critical fundamental formulas or equations (using LaTeX, e.g., $E=mc^2$) as sub-topics. Wrap all sub-topics (textual, formulas, equations) in <click>tags</click> (e.g., <click>relevant concept</click>, <click>$y=mx+c$</click>). Your response must consist strictly of the two definition sentences containing the embedded clickable sub-topics. Do not include any headers, introductory phrases, or these instructions in your output.
Example of the expected output format: Photosynthesis is a &lt;click>biological process&lt;/click> in &lt;click>plants&lt;/click> and other organisms converting &lt;click>light energy&lt;/click> into &lt;click>chemical energy&lt;/click>, often represented by &lt;click>6CO2​+6H2​O+Light→C6​H12​O6​+6O2​&lt;/click>. This process uses &lt;click>carbon dioxide&lt;/click> and &lt;click>water&lt;/click> to produce &lt;click>glucose&lt;/click> (a &lt;click>sugar&lt;/click>) and &lt;click>oxygen&lt;/click>.

"""
        elif mode == 'fact':
            prompt = f"Tell me one very interesting and concise fun fact about '{word}'."
        elif mode == 'quiz':
            prompt = (
                f"Generate a set of exactly 3 distinct multiple-choice quiz questions about '{word}'. "
                "For each question, strictly follow this exact format, including newlines:\n"
                "**Question [Number]:** [Your Question Text Here]\n"
                "A) [Option A Text]\n"
                "B) [Option B Text]\n"
                "C) [Option C Text]\n"
                "D) [Option D Text]\n"
                "Correct Answer: [Single Letter A, B, C, or D]\n"
                "Ensure option keys are unique (A, B, C, D) for each question. "
                "The text for each option (A, B, C, D) should start immediately after the 'A) ', 'B) ', 'C) ', 'D) ' marker. "
                "Do not include option markers like 'A)' or 'B)' *within* the text of the options themselves. "
                "Separate each complete question block (from **Question... to Correct Answer:...) with '---QUIZ_SEPARATOR---'."
            )
        elif mode == 'image':
             generated_text_content = f"Placeholder image description for {word}. Actual image generation to be implemented."
        elif mode == 'deep_dive':
             generated_text_content = f"Placeholder for a deep dive into {word}. More detailed content to come."

        # This holds the content for the current specific request, to be returned to the frontend
        current_request_content_holder = {}

        if mode in ['explain', 'fact', 'quiz'] and prompt:
            if not genai.get_model('models/gemini-1.5-flash-latest'): # Check model availability
                current_app.logger.error("Gemini model 'gemini-1.5-flash-latest' not found or not configured for content generation.")
                return jsonify({"error": "AI model not available"}), 503

            gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')
            response = gemini_model.generate_content(prompt)
            llm_output_text = response.text # Store raw output first

            if mode == 'quiz':
                quiz_questions_array = [q.strip() for q in llm_output_text.split('---QUIZ_SEPARATOR---') if q.strip()]
                if not (1 <= len(quiz_questions_array) <= 3) and '---QUIZ_SEPARATOR---' in llm_output_text:
                     current_app.logger.warning(f"Quiz separator found, but split resulted in {len(quiz_questions_array)} questions for '{word}'. Using raw output as single block if non-empty.")
                     quiz_questions_array = [llm_output_text.strip()] if llm_output_text.strip() else []
                elif not quiz_questions_array and llm_output_text.strip():
                    quiz_questions_array = [llm_output_text.strip()]

                current_request_content_holder[mode] = quiz_questions_array
                cached_content_from_db[mode] = quiz_questions_array # Quizzes are always cached if generated/refreshed
                if force_refresh:
                    quiz_progress_data = [] # Reset progress
            else: # explain, fact
                generated_text_content = llm_output_text
                current_request_content_holder[mode] = generated_text_content
                # --- Caching Option A: Only update DB cache for generic explanations or other modes ---
                if not is_contextual_explain_call: # This includes generic explain, fact
                    cached_content_from_db[mode] = generated_text_content

        elif mode in ['image', 'deep_dive'] and generated_text_content: # For placeholder modes
             current_request_content_holder[mode] = generated_text_content
             # These are not contextual, so they update the cache
             cached_content_from_db[mode] = generated_text_content

        if mode not in modes_already_generated:
            modes_already_generated.append(mode)

        payload_for_db = {
            'word': word,
            'last_explored_at': firestore.SERVER_TIMESTAMP,
            'modes_generated': modes_already_generated,
            'generated_content_cache': cached_content_from_db # This now correctly excludes contextual explanations
        }

        if not word_doc.exists:
            payload_for_db.update({
                'first_explored_at': firestore.SERVER_TIMESTAMP,
                'is_favorite': False,
                'quiz_progress': []
            })
            is_favorite_status = False # Ensure set for response if new
        else: # Carry over existing values if not otherwise set
            payload_for_db['is_favorite'] = is_favorite_status
            payload_for_db['quiz_progress'] = quiz_progress_data


        if mode == 'quiz' and force_refresh:
            payload_for_db['quiz_progress'] = [] # Ensure reset in DB
            quiz_progress_data = [] # And for current response

        user_word_history_ref.set(payload_for_db, merge=True)

        response_payload = {
            "word": word,
            mode: current_request_content_holder.get(mode), # The specific content generated for this request
            "source": "generated",
            "is_favorite": payload_for_db.get('is_favorite', is_favorite_status),
            "full_cache": cached_content_from_db, # Reflects what's in the DB generic cache
            "quiz_progress": payload_for_db.get('quiz_progress', quiz_progress_data),
            "modes_generated": modes_already_generated
        }
        return jsonify(response_payload), 200

    except Exception as e:
        current_app.logger.error(f"Error in /generate_explanation for '{word}', user '{current_user_id}': {e}", exc_info=True)
        return jsonify({"error": f"Internal error: {e}"}), 500
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
# END OF MODIFIED SECTION in /generate_explanation
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

@app.route('/profile', methods=['GET', 'OPTIONS'])
@token_required
def get_user_profile(current_user_id):
    if not db: return jsonify({"error": "Database not configured"}), 500
    try:
        user_doc_ref = db.collection('users').document(current_user_id)
        user_doc = user_doc_ref.get()
        if not user_doc.exists: return jsonify({"error": "User not found"}), 404
        user_data = user_doc.to_dict()

        word_history_list = []
        favorite_words_list = []
        word_history_query = user_doc_ref.collection('word_history').order_by('last_explored_at', direction=firestore.Query.DESCENDING).stream()
        for doc in word_history_query:
            entry = doc.to_dict()
            entry_data = {
                "id": doc.id,
                "word": entry.get("word"),
                "is_favorite": entry.get("is_favorite", False),
                "last_explored_at": entry.get("last_explored_at").isoformat() if entry.get("last_explored_at") else None,
                "modes_generated": entry.get("modes_generated", [])
            }
            word_history_list.append(entry_data)
            if entry_data["is_favorite"]:
                favorite_words_list.append(entry_data)

        streak_history_list = []
        streak_history_query = user_doc_ref.collection('streaks').order_by('completed_at', direction=firestore.Query.DESCENDING).limit(50).stream()
        for doc in streak_history_query:
            streak = doc.to_dict()
            streak_history_list.append({
                "id": doc.id,
                "words": streak.get("words", []),
                "score": streak.get("score", 0),
                "completed_at": streak.get("completed_at").isoformat() if streak.get("completed_at") else None,
                "subject": streak.get("subject") # Include subject if it exists
            })

        return jsonify({
            "username": user_data.get("username"), "email": user_data.get("email"), "tier": user_data.get("tier"),
            "total_words_explored": len(word_history_list), "explored_words": word_history_list,
            "favorite_words": favorite_words_list, "streak_history": streak_history_list,
            "created_at": user_data.get("created_at").isoformat() if user_data.get("created_at") else None
        }), 200
    except Exception as e:
        current_app.logger.error(f"Error fetching profile for user '{current_user_id}': {e}", exc_info=True)
        return jsonify({"error": f"Failed to fetch profile: {e}"}), 500

@app.route('/toggle_favorite', methods=['POST', 'OPTIONS'])
@token_required
def toggle_favorite_word(current_user_id):
    if not db: return jsonify({"error": "Database not configured"}), 500
    data = request.get_json()
    word_to_toggle = data.get('word', '').strip()
    if not word_to_toggle: return jsonify({"error": "Word is required"}), 400
    sanitized_word_id = sanitize_word_for_id(word_to_toggle)
    word_ref = db.collection('users').document(current_user_id).collection('word_history').document(sanitized_word_id)
    try:
        word_doc = word_ref.get()
        if not word_doc.exists:
            app.logger.info(f"Word '{word_to_toggle}' not in history for user '{current_user_id}'. Creating and favoriting.")
            word_ref.set({
                'word': word_to_toggle,
                'first_explored_at': firestore.SERVER_TIMESTAMP,
                'last_explored_at': firestore.SERVER_TIMESTAMP,
                'is_favorite': True,
                'generated_content_cache': {},
                'quiz_progress': [],
                'modes_generated': []
            }, merge=True)
            return jsonify({"message": "Word added to history and favorited", "word": word_to_toggle, "is_favorite": True}), 200

        current_is_favorite = word_doc.to_dict().get('is_favorite', False)
        new_favorite_status = not current_is_favorite
        word_ref.update({'is_favorite': new_favorite_status, 'last_explored_at': firestore.SERVER_TIMESTAMP})
        return jsonify({"message": "Favorite status updated", "word": word_to_toggle, "is_favorite": new_favorite_status}), 200
    except Exception as e:
        current_app.logger.error(f"Error toggling favorite for '{word_to_toggle}': {e}", exc_info=True)
        return jsonify({"error": f"Failed to toggle favorite: {e}"}), 500


@app.route('/save_streak', methods=['POST', 'OPTIONS'])
@token_required
def save_user_streak(current_user_id):
    if not db: return jsonify({"error": "Database not configured"}), 500
    data = request.get_json()
    streak_words = data.get('words')
    streak_score = data.get('score')
    if not isinstance(streak_words, list) or not streak_words or not isinstance(streak_score, int) or streak_score < 2:
        return jsonify({"error": "Invalid streak data"}), 400
    try:
        streaks_collection_ref = db.collection('users').document(current_user_id).collection('streaks')
        streak_doc_ref = streaks_collection_ref.document()
        # Note: Subject classification logic would be added here if/when implemented
        streak_doc_ref.set({'words': streak_words, 'score': streak_score, 'completed_at': firestore.SERVER_TIMESTAMP})
        return jsonify({"message": "Streak saved", "streak_id": streak_doc_ref.id}), 201
    except Exception as e:
        current_app.logger.error(f"Error saving streak for user '{current_user_id}': {e}", exc_info=True)
        return jsonify({"error": f"Failed to save streak: {e}"}), 500


@app.route('/save_quiz_attempt', methods=['POST', 'OPTIONS'])
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
        return jsonify({"error": "Missing required fields"}), 400

    sanitized_word_id = sanitize_word_for_id(word)
    word_history_ref = db.collection('users').document(current_user_id).collection('word_history').document(sanitized_word_id)

    try:
        word_doc = word_history_ref.get()
        quiz_progress = []
        if word_doc.exists:
            quiz_progress = word_doc.to_dict().get('quiz_progress', [])
        else:
            current_app.logger.warning(f"Word history for '{sanitized_word_id}' not found for user '{current_user_id}' during quiz save. Creating it.")
            word_history_ref.set({
                'word': word, 'first_explored_at': firestore.SERVER_TIMESTAMP,
                'last_explored_at': firestore.SERVER_TIMESTAMP, 'is_favorite': False,
                'quiz_progress': [], 'modes_generated': ['quiz'] # Assume quiz mode was generated
            })

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

        quiz_progress.sort(key=lambda x: x['question_index'])

        word_history_ref.update({"quiz_progress": quiz_progress, "last_explored_at": firestore.SERVER_TIMESTAMP})

        current_app.logger.info(f"Quiz attempt saved for user '{current_user_id}', word '{word}', q_idx {question_index}. New progress length: {len(quiz_progress)}")
        return jsonify({"message": "Quiz attempt saved", "quiz_progress": quiz_progress}), 200

    except Exception as e:
        current_app.logger.error(f"Error saving quiz attempt for user '{current_user_id}', word '{word}': {e}", exc_info=True)
        return jsonify({"error": f"Failed to save quiz attempt: {e}"}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_DEBUG', 'False').lower() == 'true')