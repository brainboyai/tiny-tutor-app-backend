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
import requests # For Gemini API calls (if you were using requests directly)
import google.generativeai as genai # Using the official SDK
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
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'fallback_secret_key_for_dev_only_change_me')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)

# --- Firebase Initialization ---
service_account_key_base64 = os.getenv('FIREBASE_SERVICE_ACCOUNT_KEY_BASE64')
db = None # Firestore database client

if service_account_key_base64:
    try:
        service_account_json_str = base64.b64decode(service_account_key_base64).decode('utf-8')
        service_account_info = json.loads(service_account_json_str)
        cred = credentials.Certificate(service_account_info)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        app.logger.info("Firebase initialized successfully.")
    except Exception as e:
        app.logger.error(f"Error initializing Firebase: {e}")
        db = None # Ensure db is None if initialization fails
else:
    app.logger.warning("FIREBASE_SERVICE_ACCOUNT_KEY_BASE64 not found. Firebase will not be initialized.")

# --- Google Gemini API Configuration ---
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest') # Or your preferred model
    app.logger.info("Google Gemini API configured.")
else:
    gemini_model = None
    app.logger.warning("GEMINI_API_KEY not found. AI content generation will be disabled.")

# --- Helper Functions ---
def sanitize_word_for_id(word):
    """Sanitizes a word to be used as a Firestore document ID."""
    sanitized = re.sub(r'[^\w\s-]', '', word.lower().strip())
    sanitized = re.sub(r'[-\s]+', '-', sanitized)
    return sanitized if sanitized else "untitled"

def generate_gemini_content(concept: str, mode: str, existing_explanation: str = None):
    """
    Generates content using the Gemini API based on the concept and mode.
    For 'quiz' mode, it now attempts to generate up to 3 quiz questions.
    """
    if not gemini_model:
        return "AI service is not available."

    prompt = ""
    if mode == "explain":
        prompt = f"Explain the concept of '{concept}' in 2 concise sentences. If relevant, identify up to 2 key sub-topics within your explanation and wrap them in <click>tags</click> like this: <click>sub-topic</click>."
    elif mode == "fact":
        prompt = f"Provide a single, concise, interesting, and verifiable fact about '{concept}'."
    elif mode == "quiz":
        # *** MODIFIED PROMPT FOR MULTIPLE QUIZZES ***
        # Ask for up to 3 questions, clearly separated.
        # The explanation is passed to help generate relevant quiz questions.
        base_quiz_prompt = f"Generate up to 3 distinct multiple-choice quiz questions about '{concept}'."
        if existing_explanation:
             base_quiz_prompt += f" The explanation provided for '{concept}' is: \"{existing_explanation}\". Ensure questions are related to this explanation or general knowledge about the concept."
        else:
            base_quiz_prompt += " Ensure questions test general knowledge about the concept."

        prompt = f"""{base_quiz_prompt}
For each quiz question:
1. Start with "Question:" followed by the question.
2. Provide four options, labeled A), B), C), and D).
3. After the options, on a new line, write "Correct:" followed by the letter of the correct option (e.g., "Correct: A").
4. Clearly separate each complete quiz question block (Question, Options, Correct Answer) with the exact separator "---QUIZ_SEPARATOR---".

Example of one quiz block:
Question: What is the capital of France?
A) London
B) Berlin
C) Paris
D) Madrid
Correct: C

If you generate more than one quiz, ensure they are separated by "---QUIZ_SEPARATOR---".
"""
    elif mode == "image": # Placeholder, actual image generation would use a different model/API
        return f"Placeholder image description for {concept}."
    elif mode == "deep": # Placeholder
        return f"Placeholder deep dive content for {concept}."
    else:
        return "Invalid content mode."

    try:
        app.logger.info(f"Sending prompt to Gemini for concept '{concept}', mode '{mode}'.")
        # For safety, especially with user input, consider adding safety_settings
        # response = gemini_model.generate_content(prompt, safety_settings={'HARASSMENT':'BLOCK_NONE'}) # Example
        response = gemini_model.generate_content(prompt)
        
        if not response.candidates or not response.candidates[0].content.parts:
            app.logger.warning(f"Gemini response for '{concept}' (mode: {mode}) was empty or malformed: {response}")
            return "Could not generate content at this time (empty response from AI)."

        generated_text = "".join(part.text for part in response.candidates[0].content.parts if hasattr(part, 'text'))

        if not generated_text.strip():
             app.logger.warning(f"Gemini generated empty text for '{concept}' (mode: {mode})")
             return "AI generated empty content. Try rephrasing or a different concept."

        # *** PARSING FOR MULTIPLE QUIZZES ***
        if mode == "quiz":
            quiz_strings = generated_text.split("---QUIZ_SEPARATOR---")
            valid_quizzes = []
            for q_str in quiz_strings:
                q_str_trimmed = q_str.strip()
                # Basic validation: check if it looks like a quiz
                if q_str_trimmed and "Question:" in q_str_trimmed and "Correct:" in q_str_trimmed and "A)" in q_str_trimmed:
                    valid_quizzes.append(q_str_trimmed)
            
            if not valid_quizzes:
                app.logger.warning(f"Failed to parse any valid quiz questions from Gemini output for '{concept}'. Raw output: {generated_text}")
                return ["Error: Could not parse valid quiz questions from AI response."] # Send as array with error
            app.logger.info(f"Successfully parsed {len(valid_quizzes)} quiz questions for '{concept}'.")
            return valid_quizzes # Return list of quiz strings
        
        return generated_text.strip()

    except Exception as e:
        app.logger.error(f"Error calling Gemini API for concept '{concept}', mode '{mode}': {e}")
        # Check for specific API errors if possible, e.g., from response.prompt_feedback
        if hasattr(response, 'prompt_feedback') and response.prompt_feedback.block_reason:
             return f"Content generation blocked. Reason: {response.prompt_feedback.block_reason_message or response.prompt_feedback.block_reason}"
        return f"An error occurred while generating content: {str(e)}"


# --- JWT Token Required Decorator ---
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            try:
                token = request.headers['Authorization'].split(" ")[1]
            except IndexError:
                return jsonify({"error": "Bearer token malformed."}), 401
        
        if not token:
            return jsonify({"error": "Token is missing."}), 401
        
        try:
            # data = jwt.decode(token, app.config['JWT_SECRET_KEY'], algorithms=["HS256"])
            # For compatibility with frontend's jwt-decode which doesn't typically verify signature by default
            # but relies on backend to do so. Here, we are verifying.
            unverified_claims = jwt.decode(token, algorithms=["HS256"], options={"verify_signature": False}) # Get claims first
            data = jwt.decode(token, app.config['JWT_SECRET_KEY'], algorithms=["HS256"], audience=unverified_claims.get('aud')) # Then verify with audience if present

            current_user_id = data.get('user_id')
            if not current_user_id:
                 return jsonify({"error": "Token is invalid (missing user_id)."}), 401
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token has expired."}), 401
        except jwt.InvalidTokenError as e:
            app.logger.error(f"Invalid token error: {e}")
            return jsonify({"error": f"Token is invalid: {e}"}), 401
        except Exception as e:
            app.logger.error(f"Token processing error: {e}")
            return jsonify({"error": "Token processing error."}), 401
            
        return f(current_user_id, *args, **kwargs)
    return decorated

# --- Routes ---
@app.route('/')
def home():
    return "Tiny Tutor App Backend is running!"

@app.route('/signup', methods=['POST'])
def signup():
    if not db: return jsonify({"error": "Database service not available."}), 503
    data = request.get_json()
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')

    if not username or not email or not password:
        return jsonify({"error": "Missing username, email, or password"}), 400

    users_ref = db.collection('users')
    # Check if username exists
    username_query = users_ref.where('username_lowercase', '==', username.lower()).limit(1).stream()
    if len(list(username_query)) > 0:
        return jsonify({"error": "Username already exists"}), 409
    
    # Check if email exists
    email_query = users_ref.where('email', '==', email.lower()).limit(1).stream()
    if len(list(email_query)) > 0:
        return jsonify({"error": "Email already registered"}), 409

    hashed_password = generate_password_hash(password)
    user_id = sanitize_word_for_id(username) # Or use a UUID

    # Create a new user document with a specific ID (e.g., sanitized username or UUID)
    # For this example, let's use a Firestore auto-generated ID for simplicity and uniqueness guarantee
    user_doc_ref = users_ref.document()
    user_doc_ref.set({
        'username': username,
        'username_lowercase': username.lower(), # For case-insensitive username checks
        'email': email.lower(),
        'password_hash': hashed_password,
        'tier': 'free', # Default tier
        'created_at': firestore.SERVER_TIMESTAMP
    })
    return jsonify({"message": "User created successfully"}), 201


@app.route('/login', methods=['POST'])
def login():
    if not db: return jsonify({"error": "Database service not available."}), 503
    data = request.get_json()
    username_or_email = data.get('usernameOrEmail')
    password = data.get('password')

    if not username_or_email or not password:
        return jsonify({"error": "Missing username/email or password"}), 400

    users_ref = db.collection('users')
    user_doc = None
    
    # Try finding by username first
    query_username = users_ref.where('username_lowercase', '==', username_or_email.lower()).limit(1).stream()
    user_list_username = list(query_username)
    if user_list_username:
        user_doc = user_list_username[0]
    else:
        # If not found by username, try by email
        query_email = users_ref.where('email', '==', username_or_email.lower()).limit(1).stream()
        user_list_email = list(query_email)
        if user_list_email:
            user_doc = user_list_email[0]

    if not user_doc or not check_password_hash(user_doc.to_dict().get('password_hash', ''), password):
        return jsonify({"error": "Invalid username/email or password"}), 401

    user_data = user_doc.to_dict()
    token_payload = {
        'user_id': user_doc.id, # Use Firestore document ID as user_id in token
        'username': user_data.get('username'),
        'email': user_data.get('email'),
        'tier': user_data.get('tier', 'free'),
        'exp': datetime.now(timezone.utc) + app.config['JWT_ACCESS_TOKEN_EXPIRES'],
        'iat': datetime.now(timezone.utc),
        'aud': 'tiny-tutor-user' # Example audience
    }
    token = jwt.encode(token_payload, app.config['JWT_SECRET_KEY'], algorithm="HS256")
    return jsonify({"token": token})


@app.route('/generate_explanation', methods=['POST'])
@token_required
def generate_explanation_route(current_user_id):
    if not db: return jsonify({"error": "Database service not available."}), 503
    if not gemini_model: return jsonify({"error": "AI content generation service is not available."}), 503

    data = request.get_json()
    question = data.get('question', '').strip()
    mode = data.get('mode', 'explain').strip()
    force_refresh = data.get('force_refresh', False)

    if not question:
        return jsonify({"error": "No question provided."}), 400
    
    sanitized_word_id = sanitize_word_for_id(question)
    user_ref = db.collection('users').document(current_user_id)
    word_history_ref = user_ref.collection('word_history').document(sanitized_word_id)
    word_doc = word_history_ref.get()
    
    response_data = {"word": question, "mode": mode, "source": "cache", "content": None, "full_cache": {}}
    
    cached_content = None
    existing_explanation_for_quiz = None

    if word_doc.exists:
        word_data = word_doc.to_dict()
        response_data["full_cache"] = word_data.get('generated_content_cache', {})
        
        # Try to get existing explanation if we are generating a quiz and need context
        if mode == 'quiz' and 'explain' in response_data["full_cache"]:
            existing_explanation_for_quiz = response_data["full_cache"]['explain']

        if mode in response_data["full_cache"] and not force_refresh:
            cached_content = response_data["full_cache"][mode]
            # Ensure quiz content from cache is an array if it exists
            if mode == 'quiz' and cached_content and not isinstance(cached_content, list):
                 app.logger.warning(f"Cached quiz for '{question}' was not a list. Forcing refresh.")
                 cached_content = None # Force refresh if format is wrong
            elif mode == 'quiz' and cached_content and isinstance(cached_content, list) and not all(isinstance(item, str) for item in cached_content):
                 app.logger.warning(f"Cached quiz for '{question}' contained non-string items. Forcing refresh.")
                 cached_content = None # Force refresh if format is wrong


    if cached_content is not None and not force_refresh:
        response_data["content"] = cached_content
        app.logger.info(f"Serving '{mode}' for '{question}' from cache for user '{current_user_id}'.")
    else:
        app.logger.info(f"Generating '{mode}' for '{question}' for user '{current_user_id}'. Force refresh: {force_refresh}")
        # Pass existing explanation if generating quiz and explanation exists
        ai_content = generate_gemini_content(question, mode, existing_explanation=existing_explanation_for_quiz)
        
        response_data["source"] = "generated"
        response_data["content"] = ai_content 
        
        # Update cache
        if word_doc.exists:
            word_data['generated_content_cache'][mode] = ai_content
            word_data['last_explored_at'] = firestore.SERVER_TIMESTAMP
            if mode not in word_data.get('modes_generated', []):
                word_data.get('modes_generated', []).append(mode)
            word_history_ref.update({
                'generated_content_cache': word_data['generated_content_cache'],
                'last_explored_at': firestore.SERVER_TIMESTAMP,
                'modes_generated': firestore.ArrayUnion([mode])
            })
            response_data["full_cache"] = word_data['generated_content_cache']
        else:
            word_history_ref.set({
                'word': question,
                'first_explored_at': firestore.SERVER_TIMESTAMP,
                'last_explored_at': firestore.SERVER_TIMESTAMP,
                'is_favorite': False,
                'modes_generated': [mode],
                'generated_content_cache': {mode: ai_content}
            })
            response_data["full_cache"] = {mode: ai_content}
        
        # If an explanation was generated, extract sub-topics
        if mode == "explain" and isinstance(ai_content, str):
            sub_topics = re.findall(r"<click>(.*?)</click>", ai_content)
            if sub_topics:
                word_history_ref.update({'explicit_connections': firestore.ArrayUnion(sub_topics)})

    return jsonify(response_data), 200


@app.route('/toggle_favorite', methods=['POST'])
@token_required
def toggle_favorite(current_user_id):
    # ... (Implementation remains largely the same as your existing one) ...
    if not db: return jsonify({"error": "Database service not available."}), 503
    data = request.get_json()
    word = data.get('word', '').strip()
    is_favorite = data.get('is_favorite')

    if not word or is_favorite is None:
        return jsonify({"error": "Missing 'word' or 'is_favorite' status."}), 400
    if not isinstance(is_favorite, bool):
        return jsonify({"error": "'is_favorite' must be a boolean."}), 400

    sanitized_word_id = sanitize_word_for_id(word)
    user_ref = db.collection('users').document(current_user_id)
    word_history_ref = user_ref.collection('word_history').document(sanitized_word_id)
    
    try:
        word_doc = word_history_ref.get()
        if word_doc.exists:
            word_history_ref.update({'is_favorite': is_favorite})
            action = "favorited" if is_favorite else "unfavorited"
            app.logger.info(f"Word '{word}' {action} by user '{current_user_id}'.")
            return jsonify({"message": f"Word '{word}' {action} successfully."}), 200
        else:
            # If word not in history, but user wants to favorite (e.g. from a shared link in future)
            # For now, we assume it must exist if being toggled.
            app.logger.warning(f"Attempt to toggle favorite for non-existent word '{word}' by user '{current_user_id}'.")
            return jsonify({"error": "Word not found in user's history."}), 404
    except Exception as e:
        app.logger.error(f"Error toggling favorite for word '{word}', user '{current_user_id}': {e}")
        return jsonify({"error": f"Failed to toggle favorite: {e}"}), 500

@app.route('/profile', methods=['GET'])
@token_required
def get_profile(current_user_id):
    # ... (Implementation remains largely the same as your existing one) ...
    if not db: return jsonify({"error": "Database service not available."}), 503
    try:
        user_doc_ref = db.collection('users').document(current_user_id)
        user_doc = user_doc_ref.get()
        if not user_doc.exists:
            return jsonify({"error": "User not found."}), 404
        
        user_data = user_doc.to_dict()
        
        profile_info = {
            "username": user_data.get('username'),
            "tier": user_data.get('tier', 'free'),
        }

        # Fetch explored words
        explored_words_list = []
        word_history_collection = user_doc_ref.collection('word_history').order_by('last_explored_at', direction=firestore.Query.DESCENDING).stream()
        for doc in word_history_collection:
            word_item = doc.to_dict()
            explored_words_list.append({
                "id": doc.id, # Sanitized word ID
                "word": word_item.get('word'),
                "is_favorite": word_item.get('is_favorite', False),
                "last_explored_at": word_item.get('last_explored_at').isoformat() if word_item.get('last_explored_at') else None,
                "generated_content_cache": word_item.get('generated_content_cache', {}) # Send cache for profile clicks
            })
        
        profile_info["explored_words_list"] = explored_words_list
        profile_info["explored_words_count"] = len(explored_words_list)
        profile_info["favorite_words_list"] = [w for w in explored_words_list if w["is_favorite"]]

        # Fetch streak history
        streak_history_list = []
        streaks_collection = user_doc_ref.collection('streaks').order_by('completed_at', direction=firestore.Query.DESCENDING).limit(50).stream() # Limit for performance
        for doc in streaks_collection:
            streak_data = doc.to_dict()
            streak_history_list.append({
                "id": doc.id,
                "words": streak_data.get('words', []),
                "score": streak_data.get('score', 0),
                "completed_at": streak_data.get('completed_at').isoformat() if streak_data.get('completed_at') else None,
            })
        profile_info["streak_history"] = streak_history_list
        
        return jsonify(profile_info), 200

    except Exception as e:
        app.logger.error(f"Error fetching profile for user '{current_user_id}': {e}")
        return jsonify({"error": f"Failed to fetch profile: {e}"}), 500


@app.route('/save_streak', methods=['POST'])
@token_required
def save_streak(user_id):
    # ... (Implementation remains largely the same as your existing one) ...
    if not db: return jsonify({"error": "Database service not available."}), 503
    data = request.get_json()
    streak_words = data.get('words')
    streak_score = data.get('score')

    if not isinstance(streak_words, list) or not streak_words:
        return jsonify({"error": "Invalid 'words' format or empty list."}), 400
    if not all(isinstance(word, str) for word in streak_words):
        return jsonify({"error": "All items in 'words' must be strings."}), 400
    if not isinstance(streak_score, int) or streak_score < 2: # Streaks of score 1 are live, not saved
        return jsonify({"error": "Invalid 'score' format or insufficient score for a streak (min 2)."}), 400
    
    try:
        user_ref = db.collection('users').document(user_id)
        streaks_collection_ref = user_ref.collection('streaks')
        
        streak_doc_ref = streaks_collection_ref.document() 
        streak_doc_ref.set({
            'words': streak_words,
            'score': streak_score,
            'completed_at': firestore.SERVER_TIMESTAMP
        })
        
        app.logger.info(f"Streak saved for user '{user_id}', streak ID: {streak_doc_ref.id}, score: {streak_score}, words: {len(streak_words)}")
        return jsonify({"message": "Streak saved successfully", "streak_id": streak_doc_ref.id}), 201
        
    except Exception as e:
        app.logger.error(f"Error saving streak for user '{user_id}': {e}")
        return jsonify({"error": f"Failed to save streak: {e}"}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    # For Render, Gunicorn is typically used via Procfile, so app.run is for local dev.
    # app.run(debug=True, host='0.0.0.0', port=port) # Local dev
    app.run(host='0.0.0.0', port=port) # For Render, it might pick up debug from FLASK_DEBUG
