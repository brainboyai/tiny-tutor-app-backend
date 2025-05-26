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
# import requests # Using SDK now
import google.generativeai as genai
import jwt # PyJWT for encoding/decoding
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps # For JWT decorator

# Load environment variables from .env file
load_dotenv()

# Initialize Flask App FIRST
app = Flask(__name__)

# Configure CORS
CORS(app, resources={r"/*": {"origins": [
    "https://tiny-tutor-app-frontend.onrender.com",
    "http://localhost:5173",
    "http://127.0.0.1:5173"
]}}, supports_credentials=True)


# --- JWT Configuration & Helper ---
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'fallback_secret_key_for_dev_only_change_me')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)

# --- Firebase Initialization ---
service_account_key_base64 = os.getenv('FIREBASE_SERVICE_ACCOUNT_KEY_BASE64')
db = None

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
        db = None
else:
    app.logger.warning("FIREBASE_SERVICE_ACCOUNT_KEY_BASE64 not found. Firebase will not be initialized.")

# --- Google Gemini API Configuration ---
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')
    app.logger.info("Google Gemini API configured.")
else:
    gemini_model = None
    app.logger.warning("GEMINI_API_KEY not found. AI content generation will be disabled.")

# --- Helper Functions ---
def sanitize_word_for_id(word):
    sanitized = re.sub(r'[^\w\s-]', '', word.lower().strip())
    sanitized = re.sub(r'[-\s]+', '-', sanitized)
    return sanitized if sanitized else "untitled"

def generate_gemini_content(concept: str, mode: str, existing_explanation: str = None):
    if not gemini_model:
        return "AI service is not available."
    prompt = ""
    if mode == "explain":
        prompt = f"Explain the concept of '{concept}' in 2-3 concise sentences with words or sub-topics that could extend the learning. If relevant, identify up to 2-3 key words or sub-topics within your explanation that deepen the understanding and wrap them in <click>tags</click> like this: <click>sub-topic</click>."
    elif mode == "fact":
        prompt = f"Provide a single, concise, interesting, and verifiable fact about '{concept}'."
    elif mode == "quiz":
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
    elif mode == "image": return f"Placeholder image description for {concept}."
    elif mode == "deep": return f"Placeholder deep dive content for {concept}."
    else: return "Invalid content mode."

    try:
        app.logger.info(f"Sending prompt to Gemini for concept '{concept}', mode '{mode}'.")
        response = gemini_model.generate_content(prompt)
        if not response.candidates or not response.candidates[0].content.parts:
            app.logger.warning(f"Gemini response for '{concept}' (mode: {mode}) was empty or malformed: {response}")
            return "Could not generate content at this time (empty response from AI)."
        generated_text = "".join(part.text for part in response.candidates[0].content.parts if hasattr(part, 'text'))
        if not generated_text.strip():
             app.logger.warning(f"Gemini generated empty text for '{concept}' (mode: {mode})")
             return "AI generated empty content. Try rephrasing or a different concept."
        if mode == "quiz":
            quiz_strings = generated_text.split("---QUIZ_SEPARATOR---")
            valid_quizzes = []
            for q_str in quiz_strings:
                q_str_trimmed = q_str.strip()
                if q_str_trimmed and "Question:" in q_str_trimmed and "Correct:" in q_str_trimmed and "A)" in q_str_trimmed:
                    valid_quizzes.append(q_str_trimmed)
            if not valid_quizzes:
                app.logger.warning(f"Failed to parse any valid quiz questions from Gemini output for '{concept}'. Raw output: {generated_text}")
                return ["Error: Could not parse valid quiz questions from AI response."]
            app.logger.info(f"Successfully parsed {len(valid_quizzes)} quiz questions for '{concept}'.")
            return valid_quizzes
        return generated_text.strip()
    except Exception as e:
        app.logger.error(f"Error calling Gemini API for concept '{concept}', mode '{mode}': {e}")
        if hasattr(response, 'prompt_feedback') and response.prompt_feedback.block_reason:
             return f"Content generation blocked. Reason: {response.prompt_feedback.block_reason_message or response.prompt_feedback.block_reason}"
        return f"An error occurred while generating content: {str(e)}"

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            try: token = request.headers['Authorization'].split(" ")[1]
            except IndexError: return jsonify({"error": "Bearer token malformed."}), 401
        if not token: return jsonify({"error": "Token is missing."}), 401
        try:
            unverified_claims = jwt.decode(token, algorithms=["HS256"], options={"verify_signature": False})
            data = jwt.decode(token, app.config['JWT_SECRET_KEY'], algorithms=["HS256"], audience=unverified_claims.get('aud'))
            current_user_id = data.get('user_id')
            if not current_user_id: return jsonify({"error": "Token is invalid (missing user_id)."}), 401
        except jwt.ExpiredSignatureError: return jsonify({"error": "Token has expired."}), 401
        except jwt.InvalidTokenError as e: app.logger.error(f"Invalid token error: {e}"); return jsonify({"error": f"Token is invalid: {e}"}), 401
        except Exception as e: app.logger.error(f"Token processing error: {e}"); return jsonify({"error": "Token processing error."}), 401
        return f(current_user_id, *args, **kwargs)
    return decorated

@app.route('/')
def home(): return "Tiny Tutor App Backend is running!"

@app.route('/signup', methods=['POST'])
def signup():
    if not db: return jsonify({"error": "Database service not available."}), 503
    data = request.get_json()
    username, email, password = data.get('username'), data.get('email'), data.get('password')
    if not all([username, email, password]): return jsonify({"error": "Missing username, email, or password"}), 400
    users_ref = db.collection('users')
    if len(list(users_ref.where('username_lowercase', '==', username.lower()).limit(1).stream())) > 0:
        return jsonify({"error": "Username already exists"}), 409
    if len(list(users_ref.where('email', '==', email.lower()).limit(1).stream())) > 0:
        return jsonify({"error": "Email already registered"}), 409
    user_doc_ref = users_ref.document()
    user_doc_ref.set({
        'username': username, 'username_lowercase': username.lower(), 'email': email.lower(),
        'password_hash': generate_password_hash(password), 'tier': 'free', 'created_at': firestore.SERVER_TIMESTAMP
    })
    return jsonify({"message": "User created successfully"}), 201

@app.route('/login', methods=['POST'])
def login():
    if not db: return jsonify({"error": "Database service not available."}), 503
    data = request.get_json()
    username_or_email, password = data.get('usernameOrEmail'), data.get('password')
    if not username_or_email or not password: return jsonify({"error": "Missing username/email or password"}), 400
    users_ref = db.collection('users')
    user_doc = None
    user_list_username = list(users_ref.where('username_lowercase', '==', username_or_email.lower()).limit(1).stream())
    if user_list_username: user_doc = user_list_username[0]
    else:
        user_list_email = list(users_ref.where('email', '==', username_or_email.lower()).limit(1).stream())
        if user_list_email: user_doc = user_list_email[0]
    if not user_doc or not check_password_hash(user_doc.to_dict().get('password_hash', ''), password):
        return jsonify({"error": "Invalid username/email or password"}), 401
    user_data = user_doc.to_dict()
    token_payload = {
        'user_id': user_doc.id, 'username': user_data.get('username'), 'email': user_data.get('email'),
        'tier': user_data.get('tier', 'free'), 'exp': datetime.now(timezone.utc) + app.config['JWT_ACCESS_TOKEN_EXPIRES'],
        'iat': datetime.now(timezone.utc), 'aud': 'tiny-tutor-user'
    }
    token = jwt.encode(token_payload, app.config['JWT_SECRET_KEY'], algorithm="HS256")
    return jsonify({"token": token})

@app.route('/generate_explanation', methods=['POST'])
@token_required
def generate_explanation_route(current_user_id):
    if not db: return jsonify({"error": "Database service not available."}), 503
    if not gemini_model: return jsonify({"error": "AI content generation service is not available."}), 503
    data = request.get_json()
    question, mode, force_refresh = data.get('question', '').strip(), data.get('mode', 'explain').strip(), data.get('force_refresh', False)
    if not question: return jsonify({"error": "No question provided."}), 400
    
    sanitized_word_id = sanitize_word_for_id(question)
    word_history_ref = db.collection('users').document(current_user_id).collection('word_history').document(sanitized_word_id)
    word_doc = word_history_ref.get()
    
    response_data = {"word": question, "mode": mode, "source": "cache", "content": None, "full_cache": {}}
    cached_content, existing_explanation_for_quiz = None, None

    if word_doc.exists:
        word_data = word_doc.to_dict()
        response_data["full_cache"] = word_data.get('generated_content_cache', {})
        # *** INCLUDE QUIZ PROGRESS IN FULL CACHE ***
        response_data["full_cache"]["quiz_progress"] = word_data.get('quiz_progress', []) 
        
        if mode == 'quiz' and 'explain' in response_data["full_cache"]:
            existing_explanation_for_quiz = response_data["full_cache"]['explain']
        if mode in response_data["full_cache"] and not force_refresh:
            cached_content = response_data["full_cache"][mode]
            if mode == 'quiz': # Ensure cached quiz is list of strings
                if not isinstance(cached_content, list) or not all(isinstance(item, str) for item in cached_content if cached_content):
                    app.logger.warning(f"Cached quiz for '{question}' (user {current_user_id}) was not a valid list of strings. Forcing refresh.")
                    cached_content = None 
    
    if cached_content is not None and not force_refresh:
        response_data["content"] = cached_content
        app.logger.info(f"Serving '{mode}' for '{question}' from cache for user '{current_user_id}'.")
    else:
        app.logger.info(f"Generating '{mode}' for '{question}' for user '{current_user_id}'. Force refresh: {force_refresh}")
        ai_content = generate_gemini_content(question, mode, existing_explanation=existing_explanation_for_quiz)
        response_data["source"] = "generated"
        response_data["content"] = ai_content
        
        update_data = {
            'last_explored_at': firestore.SERVER_TIMESTAMP,
            'modes_generated': firestore.ArrayUnion([mode])
        }
        if 'generated_content_cache' not in response_data["full_cache"]: response_data["full_cache"] = {}
        response_data["full_cache"][mode] = ai_content
        update_data['generated_content_cache'] = response_data["full_cache"]

        if word_doc.exists:
            word_history_ref.update(update_data)
        else:
            set_data = {
                'word': question, 'first_explored_at': firestore.SERVER_TIMESTAMP,
                'is_favorite': False, 'quiz_progress': [] # Initialize quiz_progress for new words
            }
            set_data.update(update_data) # Add generated content and other fields
            word_history_ref.set(set_data)
        
        if mode == "explain" and isinstance(ai_content, str):
            sub_topics = re.findall(r"<click>(.*?)</click>", ai_content)
            if sub_topics: word_history_ref.update({'explicit_connections': firestore.ArrayUnion(sub_topics)})
            
    return jsonify(response_data), 200

@app.route('/save_quiz_attempt', methods=['POST'])
@token_required
def save_quiz_attempt(current_user_id):
    if not db: return jsonify({"error": "Database service not available."}), 503
    data = request.get_json()
    word = data.get('word', '').strip()
    question_index = data.get('question_index') # 0-indexed
    selected_option_key = data.get('selected_option_key')
    is_correct = data.get('is_correct')

    if not word: return jsonify({"error": "Missing 'word'."}), 400
    if question_index is None or not isinstance(question_index, int) or question_index < 0:
        return jsonify({"error": "Invalid 'question_index'."}), 400
    if not selected_option_key or not isinstance(selected_option_key, str):
        return jsonify({"error": "Missing or invalid 'selected_option_key'."}), 400
    if is_correct is None or not isinstance(is_correct, bool):
        return jsonify({"error": "Missing or invalid 'is_correct' status."}), 400

    sanitized_word_id = sanitize_word_for_id(word)
    word_history_ref = db.collection('users').document(current_user_id).collection('word_history').document(sanitized_word_id)

    try:
        word_doc = word_history_ref.get()
        if not word_doc.exists:
            # This case should ideally not happen if quiz content was generated, as the doc would be created.
            # But handle defensively.
            app.logger.error(f"Attempt to save quiz attempt for non-existent word history: '{word}' by user '{current_user_id}'.")
            # Optionally, create the word_history doc here if it's a valid scenario
            # For now, assume it should exist if quizzes are being attempted.
            return jsonify({"error": "Word history not found. Cannot save quiz attempt."}), 404

        word_data = word_doc.to_dict()
        quiz_progress = word_data.get('quiz_progress', [])
        
        # Ensure quiz_progress is a list
        if not isinstance(quiz_progress, list):
            quiz_progress = []

        # Create the new attempt record
        new_attempt = {
            "question_index": question_index,
            "selected_option_key": selected_option_key,
            "is_correct": is_correct,
            "timestamp": datetime.now(timezone.utc).isoformat() # Store as ISO string
        }

        # Check if an attempt for this question_index already exists
        existing_attempt_index = -1
        for i, attempt in enumerate(quiz_progress):
            if isinstance(attempt, dict) and attempt.get("question_index") == question_index:
                existing_attempt_index = i
                break
        
        if existing_attempt_index != -1:
            # Update existing attempt
            quiz_progress[existing_attempt_index] = new_attempt
            app.logger.info(f"Updating quiz attempt for word '{word}', q_idx {question_index}, user '{current_user_id}'.")
        else:
            # Add new attempt
            quiz_progress.append(new_attempt)
            app.logger.info(f"Adding new quiz attempt for word '{word}', q_idx {question_index}, user '{current_user_id}'.")
            # Sort by question_index to keep it orderly, though not strictly necessary for functionality
            quiz_progress.sort(key=lambda x: x.get("question_index", 0))


        word_history_ref.update({'quiz_progress': quiz_progress, 'last_explored_at': firestore.SERVER_TIMESTAMP})
        
        return jsonify({"message": "Quiz attempt saved successfully.", "quiz_progress": quiz_progress}), 200

    except Exception as e:
        app.logger.error(f"Error saving quiz attempt for word '{word}', user '{current_user_id}': {e}")
        return jsonify({"error": f"Failed to save quiz attempt: {str(e)}"}), 500


@app.route('/toggle_favorite', methods=['POST'])
@token_required
def toggle_favorite(current_user_id):
    # ... (same as before) ...
    if not db: return jsonify({"error": "Database service not available."}), 503
    data = request.get_json()
    word, is_favorite = data.get('word', '').strip(), data.get('is_favorite')
    if not word or is_favorite is None: return jsonify({"error": "Missing 'word' or 'is_favorite' status."}), 400
    if not isinstance(is_favorite, bool): return jsonify({"error": "'is_favorite' must be a boolean."}), 400
    sanitized_word_id = sanitize_word_for_id(word)
    word_history_ref = db.collection('users').document(current_user_id).collection('word_history').document(sanitized_word_id)
    try:
        word_doc = word_history_ref.get()
        if word_doc.exists:
            word_history_ref.update({'is_favorite': is_favorite})
            action = "favorited" if is_favorite else "unfavorited"
            app.logger.info(f"Word '{word}' {action} by user '{current_user_id}'.")
            return jsonify({"message": f"Word '{word}' {action} successfully."}), 200
        else:
            app.logger.warning(f"Attempt to toggle favorite for non-existent word '{word}' by user '{current_user_id}'.")
            return jsonify({"error": "Word not found in user's history."}), 404
    except Exception as e:
        app.logger.error(f"Error toggling favorite for word '{word}', user '{current_user_id}': {e}")
        return jsonify({"error": f"Failed to toggle favorite: {e}"}), 500

@app.route('/profile', methods=['GET'])
@token_required
def get_profile(current_user_id):
    # ... (same as before, ensure quiz_progress is handled if needed in profile view directly) ...
    if not db: return jsonify({"error": "Database service not available."}), 503
    try:
        user_doc_ref = db.collection('users').document(current_user_id)
        user_doc = user_doc_ref.get()
        if not user_doc.exists: return jsonify({"error": "User not found."}), 404
        user_data = user_doc.to_dict()
        profile_info = {"username": user_data.get('username'), "tier": user_data.get('tier', 'free')}
        explored_words_list = []
        word_history_collection = user_doc_ref.collection('word_history').order_by('last_explored_at', direction=firestore.Query.DESCENDING).stream()
        for doc in word_history_collection:
            word_item = doc.to_dict()
            explored_words_list.append({
                "id": doc.id, "word": word_item.get('word'), "is_favorite": word_item.get('is_favorite', False),
                "last_explored_at": word_item.get('last_explored_at').isoformat() if word_item.get('last_explored_at') else None,
                "generated_content_cache": word_item.get('generated_content_cache', {}),
                "quiz_progress": word_item.get('quiz_progress', []) # Include quiz_progress if needed for profile display
            })
        profile_info["explored_words_list"] = explored_words_list
        profile_info["explored_words_count"] = len(explored_words_list)
        profile_info["favorite_words_list"] = [w for w in explored_words_list if w["is_favorite"]]
        streak_history_list = []
        streaks_collection = user_doc_ref.collection('streaks').order_by('completed_at', direction=firestore.Query.DESCENDING).limit(50).stream()
        for doc in streaks_collection:
            streak_data = doc.to_dict()
            streak_history_list.append({
                "id": doc.id, "words": streak_data.get('words', []), "score": streak_data.get('score', 0),
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
    # ... (same as before) ...
    if not db: return jsonify({"error": "Database service not available."}), 503
    data = request.get_json()
    streak_words, streak_score = data.get('words'), data.get('score')
    if not isinstance(streak_words, list) or not streak_words or not all(isinstance(word, str) for word in streak_words):
        return jsonify({"error": "Invalid 'words' format."}), 400
    if not isinstance(streak_score, int) or streak_score < 2:
        return jsonify({"error": "Invalid 'score' format or insufficient score (min 2)."}), 400
    try:
        user_ref = db.collection('users').document(user_id)
        streaks_collection_ref = user_ref.collection('streaks')
        streak_doc_ref = streaks_collection_ref.document() 
        streak_doc_ref.set({ 'words': streak_words, 'score': streak_score, 'completed_at': firestore.SERVER_TIMESTAMP })
        app.logger.info(f"Streak saved for user '{user_id}', streak ID: {streak_doc_ref.id}, score: {streak_score}, words: {len(streak_words)}")
        return jsonify({"message": "Streak saved successfully", "streak_id": streak_doc_ref.id}), 201
    except Exception as e:
        app.logger.error(f"Error saving streak for user '{user_id}': {e}")
        return jsonify({"error": f"Failed to save streak: {e}"}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port)
