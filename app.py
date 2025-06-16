# app.py

import base64
import json
import os
import re
from datetime import datetime, timedelta, timezone
from functools import wraps
import time

import firebase_admin
import google.generativeai as genai
import jwt
from dotenv import load_dotenv
from firebase_admin import credentials, firestore
from flask import Flask, jsonify, request, current_app
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash

# --- Importing all our new logic modules ---
from game_generator import generate_game_for_topic
from story_generator import generate_story_node
from explore_generator import generate_explanation, generate_quiz_from_text
from firestore_handler import (
    get_user_profile_data,
    toggle_favorite_status,
    save_streak_to_db,
    save_quiz_attempt_to_db,
    sanitize_word_for_id
)

# --- Standard App Initialization ---
load_dotenv()
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": ["https://tiny-tutor-app-frontend.onrender.com", "http://localhost:5173", "http://127.0.0.1:5173"]}}, supports_credentials=True, expose_headers=["Content-Type", "Authorization"], allow_headers=["Content-Type", "Authorization", "X-Requested-With"])
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'fallback_secret_key_for_dev_only_change_me')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)

# Firebase initialization
service_account_key_base64 = os.getenv('FIREBASE_SERVICE_ACCOUNT_KEY_BASE64')
db = None
if service_account_key_base64:
    try:
        decoded_key_bytes = base64.b64decode(service_account_key_base64)
        service_account_info = json.loads(decoded_key_bytes.decode('utf-8'))
        if not firebase_admin._apps:
            cred = credentials.Certificate(service_account_info)
            firebase_admin.initialize_app(cred)
        db = firestore.client()
        app.logger.info("Firebase Admin SDK initialized successfully.")
    except Exception as e:
        app.logger.error(f"Failed to initialize Firebase Admin SDK: {e}")
else:
    app.logger.warning("FIREBASE_SERVICE_ACCOUNT_KEY_BASE64 not found.")

# Gemini API configuration
gemini_api_key = os.getenv('GEMINI_API_KEY')
if gemini_api_key:
    genai.configure(api_key=gemini_api_key)
else:
    app.logger.warning("GEMINI_API_KEY not found.")

# Rate limiter setup
limiter = Limiter(get_remote_address, app=app, default_limits=["200 per day", "60 per hour"], storage_uri="memory://")

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            try:
                token = request.headers['Authorization'].split(" ")[1]
            except IndexError:
                return jsonify({"error": "Bearer token malformed"}), 401
        if not token:
            return jsonify({"error": "Token is missing"}), 401
        try:
            data = jwt.decode(token, app.config['JWT_SECRET_KEY'], algorithms=["HS256"])
            current_user_id = data['user_id']
        except Exception as e:
            return jsonify({"error": "Token is invalid or expired", "details": str(e)}), 401
        return f(current_user_id, *args, **kwargs)
    return decorated

# --- Core Feature Routes ---

@app.route('/generate_explanation', methods=['POST'])
@token_required
@limiter.limit("150/hour")
def generate_explanation_route(current_user_id):
    data = request.get_json()
    word = data.get('word', '').strip()
    mode = data.get('mode', 'explain').strip()
    # ADD THIS LINE
    language = data.get('language', 'en') 

    # --- ADD THIS DEBUGGING LINE ---
    # We are using the app's logger to be sure it appears.
    current_app.logger.warning(f"LANGUAGE RECEIVED IN REQUEST: {language}")

    if not word: return jsonify({"error": "Word/concept is required"}), 400

    try:
        if mode == 'explain':
            # PASS 'language' TO THE GENERATOR
            explanation = generate_explanation(word, data.get('streakContext'), language, nonce=time.time())
            return jsonify({"word": word, "explain": explanation, "source": "generated"}), 200
        
        elif mode == 'quiz':
            explanation_text = data.get('explanation_text')
            if not explanation_text: return jsonify({"error": "Explanation text is required"}), 400
            # PASS 'language' TO THE GENERATOR
            quiz_questions = generate_quiz_from_text(word, explanation_text, data.get('streakContext'), language, nonce=time.time())
            return jsonify({"word": word, "quiz": quiz_questions, "source": "generated"}), 200

        else:
            return jsonify({"error": "Invalid mode specified"}), 400
            
    except Exception as e:
        app.logger.error(f"Error in /generate_explanation for user {current_user_id}: {e}")
        return jsonify({"error": f"An internal AI error occurred: {str(e)}"}), 500


@app.route('/generate_story_node', methods=['POST'])
@token_required
@limiter.limit("200/hour")
def generate_story_node_route(current_user_id):
    data = request.get_json()
    # ADD THIS LINE
    language = data.get('language', 'en')
    history = data.get('history', [])
    
    # --- THIS IS THE FIX ---
    # Define a maximum number of history items to keep. 8 items = 4 user/AI turns.
    MAX_HISTORY_ITEMS = 8 
    
    # If the history is longer than our max, slice it to keep only the most recent items.
    if len(history) > MAX_HISTORY_ITEMS:
        current_app.logger.warning(f"History truncated from {len(history)} to {MAX_HISTORY_ITEMS} items.")
        history = history[-MAX_HISTORY_ITEMS:]
        
    # --- END OF FIX ---
    # --- ADD THESE DEBUGGING LINES ---
    current_app.logger.warning(f"STORY MODE REQUEST: Language='{language}'")
    current_app.logger.warning(f"STORY MODE HISTORY RECEIVED: {history}")
    try:
        # PASS 'language' TO THE GENERATOR
        parsed_node = generate_story_node(
            topic=data.get('topic', '').strip(),
            history=data.get('history', []),
            last_choice_leads_to=data.get('leads_to'),
            language=language
        )
        return jsonify(parsed_node), 200
    except ValueError as e:
        app.logger.warning(f"ValueError in story generation for user {current_user_id}: {e}")
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app.logger.error(f"FATAL Exception in /generate_story_node for user {current_user_id}: {e}")
        return jsonify({"error": "An unexpected server error occurred."}), 500
    

@app.route('/generate_game', methods=['POST'])
@token_required
@limiter.limit("50/hour")
def generate_game_route(current_user_id):
    topic = request.json.get('topic', '').strip()
    if not topic: return jsonify({"error": "Topic is required"}), 400
    try:
        # Simple delegation
        reasoning, game_html = generate_game_for_topic(topic)
        # Here you could add caching logic if desired, similar to before
        return jsonify({"topic": topic, "game_html": game_html, "reasoning": reasoning}), 200
    except Exception as e:
        app.logger.error(f"Error in /generate_game for user {current_user_id}: {e}")
        return jsonify({"error": f"An internal error occurred: {str(e)}"}), 500

# --- User Data and Stats Routes ---

@app.route('/profile', methods=['GET'])
@token_required
def get_user_profile(current_user_id):
    try:
        profile_data = get_user_profile_data(db, current_user_id)
        return jsonify(profile_data), 200
    except Exception as e:
        app.logger.error(f"Failed to fetch profile for user {current_user_id}: {e}")
        return jsonify({"error": f"Failed to fetch profile: {str(e)}"}), 500

@app.route('/toggle_favorite', methods=['POST'])
@token_required
def toggle_favorite_route(current_user_id):
    word = request.json.get('word', '').strip()
    if not word: return jsonify({"error": "Word is required"}), 400
    try:
        new_status = toggle_favorite_status(db, current_user_id, word)
        return jsonify({"message": "Favorite status updated", "word": word, "is_favorite": new_status}), 200
    except Exception as e:
        app.logger.error(f"Failed to toggle favorite for user {current_user_id}: {e}")
        return jsonify({"error": f"Failed to toggle favorite: {str(e)}"}), 500

@app.route('/save_streak', methods=['POST'])
@token_required
def save_streak_route(current_user_id):
    data = request.get_json()
    words = data.get('words')
    score = data.get('score')
    if not isinstance(words, list) or not words or not isinstance(score, int):
        return jsonify({"error": "Invalid streak data"}), 400
    try:
        updated_history = save_streak_to_db(db, current_user_id, words, score)
        return jsonify({"message": "Streak processed", "streakHistory": updated_history}), 200
    except Exception as e:
        app.logger.error(f"Failed to save streak for user {current_user_id}: {e}")
        return jsonify({"error": f"Failed to save streak: {str(e)}"}), 500

@app.route('/save_quiz_attempt', methods=['POST'])
@token_required
def save_quiz_attempt_route(current_user_id):
    data = request.get_json()
    word = data.get('word', '').strip()
    is_correct = data.get('is_correct')
    if not word or is_correct is None:
        return jsonify({"error": "Missing required fields"}), 400
    try:
        save_quiz_attempt_to_db(db, current_user_id, word, is_correct)
        return jsonify({"message": "Quiz attempt processed and stats updated"}), 200
    except Exception as e:
        app.logger.error(f"Failed to save quiz stats for user {current_user_id}: {e}")
        return jsonify({"error": f"Failed to save quiz attempt: {str(e)}"}), 500


# --- Authentication Routes (largely unchanged) ---

@app.route('/signup', methods=['POST'])
@limiter.limit("5 per hour")
def signup_user():
    data = request.json
    username = data.get('username', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password')
    if not all([username, email, password]):
        return jsonify({"error": "Username, email, and password are required"}), 400
    
    users_ref = db.collection('users')
    if users_ref.where('username_lowercase', '==', username.lower()).limit(1).get():
        return jsonify({"error": "Username already exists"}), 409
    if users_ref.where('email', '==', email).limit(1).get():
        return jsonify({"error": "Email already registered"}), 409
        
    users_ref.add({
        'username': username, 'username_lowercase': username.lower(), 'email': email,
        'password_hash': generate_password_hash(password), 'tier': 'standard',
        'created_at': firestore.SERVER_TIMESTAMP, 'quiz_points': 0,
        'total_quiz_questions_answered': 0, 'total_quiz_questions_correct': 0
    })
    return jsonify({"message": "User created successfully"}), 201

@app.route('/login', methods=['POST'])
@limiter.limit("30 per minute")
def login_user():
    data = request.json
    identifier = data.get('email_or_username', '').strip()
    password = data.get('password', '')
    if not identifier or not password:
        return jsonify({"error": "Missing username/email or password"}), 400

    is_email = '@' in identifier
    query_field = 'email' if is_email else 'username_lowercase'
    docs = db.collection('users').where(query_field, '==', identifier.lower()).limit(1).stream()
    
    user_doc = next(docs, None)
    if not user_doc:
        return jsonify({"error": "Invalid credentials"}), 401
    
    user_data = user_doc.to_dict()
    if not check_password_hash(user_data.get('password_hash', ''), password):
        return jsonify({"error": "Invalid credentials"}), 401

    token_payload = {
        'user_id': user_doc.id,
        'exp': datetime.now(timezone.utc) + app.config['JWT_ACCESS_TOKEN_EXPIRES']
    }
    access_token = jwt.encode(token_payload, app.config['JWT_SECRET_KEY'], algorithm='HS256')
    
    return jsonify({
        "message": "Login successful", "access_token": access_token,
        "user": {"id": user_doc.id, "username": user_data.get('username'), "email": user_data.get('email')}
    }), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port)

