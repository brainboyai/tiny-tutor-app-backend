# app.py

import base64
import json
import os
import re
from datetime import datetime, timedelta, timezone
from functools import wraps
import time
import jwt
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

import firebase_admin
import google.generativeai as genai
from dotenv import load_dotenv
from firebase_admin import credentials, firestore
from flask import Flask, jsonify, request, g, current_app
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash
from google.api_core import exceptions as google_exceptions
from google.api_core import exceptions
from web_context_agent import get_web_context # Import the new agent

# --- Import all modules ---
# (No changes here)
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

load_dotenv()
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": ["https://tiny-tutor-app-frontend.onrender.com", "http://localhost:5173", "http://127.0.0.1:5173"]}}, supports_credentials=True, expose_headers=["Content-Type", "Authorization"], allow_headers=["Content-Type", "Authorization", "X-Requested-With", "X-User-API-Key"])
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'fallback_secret_key_for_dev_only_change_me')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)

# --- Firebase Initialization ---
# (No changes here)
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

# --- CORRECTED: Rate Limiter with Bypass ---
def get_request_identifier():
    # If a user provides their own key, return None to EXEMPT them from rate limiting
    if request.headers.get('X-User-API-Key'):
        return None
    
    # Otherwise, key by user_id for logged-in users, or IP for guests
    return g.get("user_id", get_remote_address())

limiter = Limiter(key_func=get_request_identifier, app=app)

# --- Token Decorators (no changes) ---
def _get_user_from_token(token):
    try:
        data = jwt.decode(token, app.config['JWT_SECRET_KEY'], algorithms=["HS256"])
        user_id = data['user_id']
        user_doc = db.collection('users').document(user_id).get()
        if user_doc.exists:
            user_data = user_doc.to_dict()
            g.user_id = user_id
            g.user_tier = user_data.get('tier', 'free')
            return user_id
    except Exception:
        return None
    return None

def token_optional(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        g.user_id = None
        g.user_tier = 'guest'
        token = request.headers.get('Authorization', '').split(' ')[-1] if request.headers.get('Authorization', '').startswith('Bearer ') else None
        user_id = _get_user_from_token(token) if token else None
        return f(user_id, *args, **kwargs)
    return decorated

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization', '').split(' ')[-1] if request.headers.get('Authorization', '').startswith('Bearer ') else None
        if not token: return jsonify({"error": "Token is missing"}), 401
        user_id = _get_user_from_token(token)
        if not user_id: return jsonify({"error": "Token is invalid or expired"}), 401
        return f(user_id, *args, **kwargs)
    return decorated

def generation_limit():
    if g.get('user_tier') == 'pro':
        return "200/day"
    return "3/day"

def configure_gemini_for_request():
    user_api_key = request.headers.get('X-User-API-Key')
    api_key_to_use = user_api_key if user_api_key else os.getenv('GEMINI_API_KEY')
    if not api_key_to_use:
        raise ValueError("API key is not available.")
    genai.configure(api_key=api_key_to_use)

# ... (add this helper function somewhere in the file, e.g., before the routes)
def delete_collection(coll_ref, batch_size):
    """Recursively delete a collection in batches."""
    docs = coll_ref.limit(batch_size).stream()
    deleted = 0

    for doc in docs:
        print(f"Deleting doc: {doc.id}")
        # Recursively delete subcollections
        for sub_coll_ref in doc.reference.collections():
            delete_collection(sub_coll_ref, batch_size)
        doc.reference.delete()
        deleted += 1

    if deleted >= batch_size:
        return delete_collection(coll_ref, batch_size)
    

# NEW: Global handler for 429 Rate Limit errors
@app.errorhandler(429)
def ratelimit_handler(e):
    # This ensures any rate-limited route returns a clean JSON error
    # The frontend will provide the specific message text
    return jsonify(error=f"Rate limit exceeded: {e.description}"), 429

# --- All Routes ---
# (The routes themselves do not need to change from the last version)
# ... The rest of your app.py file ...
# --- Core Feature Routes ---
@app.route('/generate_explanation', methods=['POST'])
@token_optional
@limiter.limit(generation_limit)
def generate_explanation_route(current_user_id):
    try:
        configure_gemini_for_request() 
        data = request.get_json()
        word = data.get('word', '').strip()
        mode = data.get('mode', 'explain').strip()
        language = data.get('language', 'en')
        if not word: return jsonify({"error": "Word/concept is required"}), 400

        if mode == 'explain':
            explanation = generate_explanation(word, data.get('streakContext'), language, nonce=time.time())
            return jsonify({"word": word, "explain": explanation, "source": "generated"}), 200
        elif mode == 'quiz':
            explanation_text = data.get('explanation_text')
            if not explanation_text: return jsonify({"error": "Explanation text is required"}), 400
            quiz_questions = generate_quiz_from_text(word, explanation_text, data.get('streakContext'), language, nonce=time.time())
            return jsonify({"word": word, "quiz": quiz_questions, "source": "generated"}), 200
        else:
            return jsonify({"error": "Invalid mode specified"}), 400
            
    except Exception as e:
        app.logger.error(f"Error in /generate_explanation for user {current_user_id or 'Guest'}: {e}")
        return jsonify({"error": f"An internal AI error occurred: {str(e)}"}), 500
    

# In app.py, replace the existing /fetch_web_context route with this:
@app.route('/fetch_web_context', methods=['POST'])
@token_optional
@limiter.limit(generation_limit)
def fetch_web_context_route(current_user_id):
    """
    Fetches relevant web links and snippets for a given topic using the web agent.
    """
    try:
        configure_gemini_for_request()
        topic = request.json.get('topic', '').strip()
        if not topic:
            return jsonify({"error": "Topic is required"}), 400

        # Create a model instance to pass to the agent
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        
        # Call the agent to get the dynamic web context
        web_context = get_web_context(topic, model)

        return jsonify({"topic": topic, "web_context": web_context})

    except Exception as e:
        app.logger.error(f"Error in /fetch_web_context for topic '{topic}': {e}")
        return jsonify({"error": f"An internal error occurred: {str(e)}"}), 500

# ... rest of app.py
#------------------------------------------------------------------------------------------
# Keep the enhanced fetcher function as a helper
def fetch_metadata_enhanced(url_to_fetch):
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    driver = None
    try:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
        driver.get(url_to_fetch)
        time.sleep(2)
        soup = BeautifulSoup(driver.page_source, 'lxml')
        
        # ... (The metadata extraction logic remains the same)
        title = (soup.find('meta', property='og:title') or soup.find('title')).get('content', '').strip() or soup.title.string
        description = (soup.find('meta', property='og:description') or soup.find('meta', attrs={'name': 'description'})).get('content', '')
        image_tag = soup.find('meta', property='og:image')
        image_url = image_tag['content'] if image_tag and image_tag.get('content') else None
        if image_url:
            image_url = urljoin(url_to_fetch, image_url)
        
        return {"title": title, "description": description, "image": image_url}
    finally:
        if driver:
            driver.quit()

# This is the standard, requests-based fetcher to be used as a fallback
def fetch_metadata_standard(url_to_fetch):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36'}
    response = requests.get(url_to_fetch, headers=headers, timeout=5, allow_redirects=True)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, 'lxml')
    
    title = (soup.find('meta', property='og:title') or soup.find('title')).get('content', '').strip() or soup.title.string
    description = (soup.find('meta', property='og:description') or soup.find('meta', attrs={'name': 'description'})).get('content', '')
    image_tag = soup.find('meta', property='og:image')
    image_url = image_tag['content'] if image_tag and image_tag.get('content') else None
    if image_url:
        image_url = urljoin(response.url, image_url)
        
    return {"title": title, "description": description, "image": image_url}

# Replace your existing /fetch_link_metadata route with this new version
@app.route('/fetch_link_metadata', methods=['GET'])
@limiter.limit("30 per minute")
def fetch_link_metadata_route():
    url_to_fetch = request.args.get('url')
    if not url_to_fetch:
        return jsonify({"error": "URL parameter is required"}), 400

    try:
        # --- PRIMARY ATTEMPT: Use the enhanced headless browser ---
        logging.warning(f"METADATA: Attempting ENHANCED fetch for {url_to_fetch}")
        metadata = fetch_metadata_enhanced(url_to_fetch)
        return jsonify(metadata)
    except Exception as e:
        # --- FALLBACK: If enhanced fetcher fails, use the standard method ---
        logging.error(f"ENHANCED fetch failed for {url_to_fetch}: {e}. Trying STANDARD fallback.")
        try:
            metadata = fetch_metadata_standard(url_to_fetch)
            return jsonify(metadata)
        except Exception as e2:
            logging.error(f"STANDARD fetch also failed for {url_to_fetch}: {e2}")
            return jsonify({"error": "Could not retrieve link preview."}), 500
#------------------------------------------------------------------------------------------

@app.route('/generate_story_node', methods=['POST'])
@token_optional
@limiter.limit(generation_limit)
def generate_story_node_route(current_user_id):
    try:
        configure_gemini_for_request()
        data = request.get_json()
        language = data.get('language', 'en')
        parsed_node = generate_story_node(
            topic=data.get('topic', '').strip(),
            history=data.get('history', []),
            last_choice_leads_to=data.get('leads_to'),
            language=language
        )
        return jsonify(parsed_node), 200
    except Exception as e:
        return jsonify({"error": "An unexpected server error occurred."}), 500

@app.route('/generate_game', methods=['POST'])
@token_optional
@limiter.limit(generation_limit)
def generate_game_route(current_user_id):
    try:
        configure_gemini_for_request()
        topic = request.json.get('topic', '').strip()
        if not topic: return jsonify({"error": "Topic is required"}), 400
        reasoning, game_html = generate_game_for_topic(topic)
        return jsonify({"topic": topic, "game_html": game_html, "reasoning": reasoning}), 200
    except Exception as e:
        return jsonify({"error": f"An internal error occurred: {str(e)}"}), 500

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

# ... (place this after the existing /save_quiz_attempt route and before the /signup route)

@app.route('/validate_api_key', methods=['POST'])
@limiter.limit("10 per minute") # Prevent abuse
def validate_api_key():
    """
    Validates a user-provided Gemini API key by making a test call.
    It safely restores the original environment key after the check.
    """
    data = request.get_json()
    api_key_to_test = data.get('api_key')

    if not api_key_to_test:
        return jsonify({"valid": False, "message": "No API key was provided."}), 400

    # Store the application's default key to restore it later
    original_key = os.getenv('GEMINI_API_KEY')
    
    try:
        # --- The Validation Step ---
        # 1. Configure the client to use the user's key for this specific test
        genai.configure(api_key=api_key_to_test)
        
        # 2. Create a model instance with this configuration
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        
        # 3. Make a very small, cheap, but definitive API call.
        # An invalid key will raise a PermissionDenied error here.
        model.generate_content("test", generation_config=genai.types.GenerationConfig(max_output_tokens=1))
        
        # 4. If the call succeeds, the key is valid.
        return jsonify({"valid": True, "message": "API Key is valid!"}), 200

    except google_exceptions.PermissionDenied:
        # This is the specific error for an invalid or unauthorized key.
        return jsonify({"valid": False, "message": "API key is invalid or not enabled for the Gemini API."}), 400
    except Exception as e:
        # Catch any other unexpected errors.
        app.logger.error(f"API Key Validation - Unexpected Error: {e}")
        return jsonify({"valid": False, "message": "An unexpected error occurred during validation."}), 500
    finally:
        # --- Restore Original State ---
        # 5. CRITICAL: No matter the outcome, reconfigure the client back to the
        #    original application key so that other user requests don't fail.
        if original_key:
            genai.configure(api_key=original_key)
# ... (the rest of the file remains the same)    

# ... (add this new route before the /signup route)
@app.route('/delete_account', methods=['POST'])
@token_required
def delete_account_route(current_user_id):
    """
    Handles the permanent deletion of a user's account and all associated data.
    """
    try:
        user_ref = db.collection('users').document(current_user_id)
        
        # 1. Recursively delete subcollections
        for collection_ref in user_ref.collections():
            delete_collection(collection_ref, 50) # Batch size of 50
            
        # 2. Delete the main user document
        user_ref.delete()
        
        app.logger.info(f"Successfully deleted account and all data for user_id: {current_user_id}")
        return jsonify({"message": "Account successfully deleted."}), 200

    except exceptions.NotFound:
        return jsonify({"error": "User not found."}), 404
    except Exception as e:
        app.logger.error(f"Error deleting account for user {current_user_id}: {e}")
        return jsonify({"error": f"An internal error occurred: {str(e)}"}), 500

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
        'password_hash': generate_password_hash(password), 'tier': 'free',
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
