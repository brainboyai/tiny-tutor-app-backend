# app.py
from flask import Flask, request, jsonify, current_app # Added current_app
from flask_cors import CORS
import os
import re
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
import json
import base64
import google.generativeai as genai
import jwt # PyJWT for encoding/decoding
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps # For JWT decorator
from flask_limiter import Limiter # Assuming Flask-Limiter is used as per report
from flask_limiter.util import get_remote_address # Assuming Flask-Limiter is used

# Load environment variables from .env file
load_dotenv()

# Initialize Flask App FIRST
app = Flask(__name__)

# --- CORS Configuration ---
CORS(app, 
     resources={r"/*": {"origins": [
         "https://tiny-tutor-app-frontend.onrender.com", # Your deployed frontend
         "http://localhost:5173", # Local Vite dev server
         "http://127.0.0.1:5173"  # Alternate local Vite dev server
     ]}}, 
     supports_credentials=True,
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"], 
     allow_headers=["Content-Type", "Authorization", "X-Requested-With"] 
)

# --- JWT Configuration & Helper ---
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'fallback_secret_key_for_dev_only_change_me')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)

# --- Firebase Initialization ---
try:
    service_account_key_base64 = os.getenv('FIREBASE_SERVICE_ACCOUNT_KEY_BASE64')
    if not service_account_key_base64:
        raise ValueError("FIREBASE_SERVICE_ACCOUNT_KEY_BASE64 environment variable not set.")
    
    decoded_key = base64.b64decode(service_account_key_base64)
    service_account_info = json.loads(decoded_key.decode('utf-8'))
    cred = credentials.Certificate(service_account_info)
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    app.logger.info("Firebase Admin SDK initialized successfully.")
except Exception as e:
    app.logger.error(f"Error initializing Firebase Admin SDK: {e}", exc_info=True)
    db = None 

# --- Rate Limiter Initialization ---
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"], 
    storage_uri="memory://", 
)

@app.before_request
def exempt_options_from_limit():
    if request.method == 'OPTIONS':
        pass 

# --- Gemini API Configuration ---
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    app.logger.warning("GEMINI_API_KEY environment variable not set. AI features will not work.")
    genai.configure(api_key="DUMMY_KEY_FOR_INITIALIZATION_ONLY") 
else:
    genai.configure(api_key=GEMINI_API_KEY)

# --- Helper Functions ---
def sanitize_word_for_id(word):
    sanitized = re.sub(r'[^a-zA-Z0-9-_]', '_', word.lower())
    return sanitized[:100] 

# --- Token Required Decorator ---
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method == 'OPTIONS':
            return "", 204 

        token = None
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(" ")[1]

        if not token:
            return jsonify({'message': 'Token is missing!'}), 401

        try:
            data = jwt.decode(token, current_app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
            # The key in your token payload is 'user_id' based on /signup and /login
            current_user_id = data['user_id'] 
        except jwt.ExpiredSignatureError:
            current_app.logger.warning("Token expired.")
            return jsonify({'message': 'Token has expired!'}), 401
        except jwt.InvalidTokenError:
            current_app.logger.warning("Invalid token.")
            return jsonify({'message': 'Token is invalid!'}), 401
        except Exception as e:
            current_app.logger.error(f"Token validation error: {e}", exc_info=True)
            return jsonify({'message': 'Token processing error!'}), 500 
        
        return f(current_user_id, *args, **kwargs)
    return decorated

# --- API Endpoints ---
@app.route('/signup', methods=['POST'])
def signup():
    if not db: return jsonify({"error": "Database not initialized"}), 503
    data = request.get_json()
    # ... (rest of your signup logic - ensure it returns 'user_id' in token and 'userId' in JSON response)
    # For brevity, assuming it's correct as per your file.
    # Ensure the response for signup includes:
    # return jsonify({'message': 'User created successfully', 'access_token': token, 
    #                 'user': {'username': username, 'userId': user_id, 'email': email}}), 201
    # Or similar structure that frontend expects for handleAuthSuccess.
    # Your current code returns:
    # return jsonify({'message': 'User created successfully', 'token': token, 'username': username, 'userId': user_id}), 201
    # This is fine if frontend `handleAuthSuccess` expects `data.token`, `data.username`, `data.userId`.

    username = data.get('username', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    if not username or not email or not password:
        return jsonify({'error': 'Missing username, email, or password'}), 400
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return jsonify({'error': 'Invalid email format'}), 400
    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400
    if len(username) < 3:
        return jsonify({'error': 'Username must be at least 3 characters'}), 400

    users_ref = db.collection('users')
    if users_ref.where('username_lowercase', '==', username.lower()).limit(1).get():
        return jsonify({'error': 'Username already exists'}), 409
    if users_ref.where('email', '==', email).limit(1).get():
        return jsonify({'error': 'Email already registered'}), 409

    hashed_password = generate_password_hash(password)
    user_doc_ref = users_ref.document() 
    user_id = user_doc_ref.id
    user_data_to_store = {
        'user_id': user_id, 
        'username': username,
        'username_lowercase': username.lower(),
        'email': email,
        'password_hash': hashed_password,
        'tier': 'free', 
        'created_at': firestore.SERVER_TIMESTAMP
    }
    user_doc_ref.set(user_data_to_store)
    
    token_payload = {
        'user_id': user_id,
        'username': username,
        'exp': datetime.now(timezone.utc) + current_app.config['JWT_ACCESS_TOKEN_EXPIRES']
    }
    access_token = jwt.encode(token_payload, current_app.config['JWT_SECRET_KEY'], algorithm='HS256')

    # Ensure the response matches what frontend's handleAuthSuccess expects
    # Your App.tsx handleAuthSuccess expects: data.access_token, data.user (which has username, userId)
    # So, the response should be:
    return jsonify({
        'message': 'User created successfully', 
        'access_token': access_token, # Changed from 'token' to 'access_token'
        'user': {'username': username, 'userId': user_id, 'email': email} # Added 'user' object
    }), 201


@app.route('/login', methods=['POST'])
def login():
    if not db: return jsonify({"error": "Database not initialized"}), 503
    data = request.get_json()
    # ... (rest of your login logic - ensure it returns 'user_id' in token and 'userId' in JSON response)
    # Similar to signup, ensure response matches frontend:
    # return jsonify({'access_token': token, 
    #                 'user': {'username': user_data['username'], 'userId': user_id, 'email': user_data.get('email')}}), 200
    # Your current code returns:
    # return jsonify({'token': token, 'username': user_data['username'], 'userId': user_id}), 200
    # This also needs adjustment if frontend expects 'access_token' and a 'user' object.

    login_identifier = data.get('email_or_username', '').strip()
    password = data.get('password', '')

    if not login_identifier or not password:
        return jsonify({'error': 'Missing email/username or password'}), 400
    
    users_ref = db.collection('users')
    user_query_res = users_ref.where('email', '==', login_identifier.lower()).limit(1).get()
    if not user_query_res:
        user_query_res = users_ref.where('username_lowercase', '==', login_identifier.lower()).limit(1).get()

    if not user_query_res:
        return jsonify({'error': 'Invalid credentials'}), 401
    
    user_doc_snapshot = user_query_res[0]
    user_data = user_doc_snapshot.to_dict()
    user_id = user_doc_snapshot.id 

    if not check_password_hash(user_data['password_hash'], password):
        return jsonify({'error': 'Invalid credentials'}), 401

    token_payload = {
        'user_id': user_id, 
        'username': user_data['username'],
        'exp': datetime.now(timezone.utc) + current_app.config['JWT_ACCESS_TOKEN_EXPIRES']
    }
    access_token = jwt.encode(token_payload, current_app.config['JWT_SECRET_KEY'], algorithm='HS256')
    
    # Adjust response to match frontend expectation
    return jsonify({
        'access_token': access_token, # Changed from 'token'
        'user': {'username': user_data['username'], 'userId': user_id, 'email': user_data.get('email')}
    }), 200


@app.route('/generate_explanation', methods=['POST'])
@token_required
def generate_explanation_route(current_user_id): # current_user_id comes from @token_required
    if not db: return jsonify({"error": "Database not initialized"}), 503
    if not GEMINI_API_KEY or GEMINI_API_KEY == "DUMMY_KEY_FOR_INITIALIZATION_ONLY":
        return jsonify({"error": "AI service not configured on server."}), 503

    data = request.get_json()
    word = data.get('word')
    mode = data.get('mode', 'explain') 
    refresh_cache = data.get('refresh_cache', False)

    if not word:
        return jsonify({'error': 'Word is required'}), 400

    sanitized_word_id = sanitize_word_for_id(word)
    # The collection path should be users/{user_id}/word_history/{word_id}
    user_word_history_ref = db.collection('users').document(current_user_id).collection('word_history').document(sanitized_word_id)
    
    try:
        word_doc = user_word_history_ref.get()
        content_to_return = None
        # Initialize with empty structures if not found or on refresh
        generated_content_cache = {}
        modes_generated = []
        is_favorite = False
        quiz_progress = [] # Always reset/fetch quiz_progress for the specific word

        if word_doc.exists:
            word_data = word_doc.to_dict()
            # Load existing cache, modes, favorite status, and progress
            generated_content_cache = word_data.get('generated_content_cache', {})
            modes_generated = word_data.get('modes_generated', [])
            is_favorite = word_data.get('is_favorite', False)
            quiz_progress = word_data.get('quiz_progress', []) # Load existing progress
            
            if mode in generated_content_cache and not refresh_cache:
                content_to_return = generated_content_cache[mode]
        
        if content_to_return is None or refresh_cache:
            app.logger.info(f"Generating content for word '{word}', mode '{mode}' for user '{current_user_id}' (Refresh: {refresh_cache})")
            
            model = genai.GenerativeModel('gemini-1.5-flash-latest') 
            prompt = ""
            if mode == 'explain':
                # FIX: Changed 'concept' to 'word'
                prompt = f"Explain the concept of '{word}' in 2 concise sentences with words or sub-topics that could extend the learning. If relevant, identify up to 2 key words or sub-topics within your explanation that deepen the understanding and wrap them in <click>tags</click> like this: <click>sub-topic</click>."
            elif mode == 'fact':
                prompt = f"Tell me one single, concise, interesting fact about '{word}'."
            elif mode == 'quiz':
                prompt = f"""Create a set of 1 to 3 multiple-choice quiz questions about '{word}'.
For each question:
1. Provide the question text.
2. Provide 4 answer options, labeled A), B), C), and D).
3. Clearly indicate the correct answer, for example, by writing 'Correct Answer: B)' or similar after the options for that question.
Separate each complete question block (question, options, correct answer) with '---QUIZ_SEPARATOR---'.
If you can only generate one question, do not use the separator.
Example for one question:
What is the capital of France?
A) London
B) Berlin
C) Paris
D) Madrid
Correct Answer: C)
"""
            elif mode == 'image': 
                content_to_return = f"Placeholder image content for {word}."
            elif mode == 'deep_dive': 
                content_to_return = f"Placeholder deep dive content for {word}."
            else:
                return jsonify({'error': 'Invalid content mode'}), 400

            if mode not in ['image', 'deep_dive']: 
                try:
                    response = model.generate_content(prompt)
                    content_to_return = response.text
                    # If fetching quiz (new or refresh), reset existing quiz_progress for this word on the frontend by sending empty
                    if mode == 'quiz': # Always reset quiz_progress if quiz mode is fetched/refreshed
                        quiz_progress = [] 
                except Exception as e:
                    app.logger.error(f"Gemini API error for word '{word}', mode '{mode}': {e}", exc_info=True)
                    return jsonify({'error': f'Failed to generate content from AI: {str(e)}'}), 500 # Return string of e
            
            generated_content_cache[mode] = content_to_return
            if mode not in modes_generated:
                modes_generated.append(mode)

            # Update Firestore
            update_data = {
                'generated_content_cache': generated_content_cache,
                'modes_generated': modes_generated,
                'last_explored_at': firestore.SERVER_TIMESTAMP,
                'quiz_progress': quiz_progress # Save potentially reset quiz_progress
            }
            if word_doc.exists:
                user_word_history_ref.update(update_data)
            else:
                # For a new word, also set initial favorite status and first_explored_at
                update_data['word'] = word
                update_data['is_favorite'] = False # Default for new word
                update_data['first_explored_at'] = firestore.SERVER_TIMESTAMP
                user_word_history_ref.set(update_data)
        
        # Construct the full response object expected by the frontend
        # Ensure all necessary fields are present, even if from existing doc
        final_response = {
            'word': word, # The word requested
            'mode': mode, # The mode requested
            'content': content_to_return, # The newly generated or cached content for this mode
            'generated_content_cache': generated_content_cache, # The entire cache for this word
            'modes_generated': modes_generated, # All modes generated for this word
            'is_favorite': is_favorite, # Current favorite status
            'quiz_progress': quiz_progress # Current quiz progress for this word
        }
        return jsonify(final_response), 200

    except Exception as e:
        app.logger.error(f"Error in /generate_explanation for user '{current_user_id}', word '{word}': {e}", exc_info=True)
        return jsonify({'error': f'An unexpected error occurred: {str(e)}'}), 500 # Return string of e

# ... (rest of your app.py: /toggle_favorite, /profile, /save_streak, /save_quiz_attempt, health_check, __main__)
# Ensure these routes are consistent with your frontend expectations.

@app.route('/toggle_favorite', methods=['POST'])
@token_required
def toggle_favorite(current_user_id):
    if not db: return jsonify({"error": "Database not initialized"}), 503
    data = request.get_json()
    word = data.get('word')
    if not word:
        return jsonify({'error': 'Word is required'}), 400

    sanitized_word_id = sanitize_word_for_id(word)
    word_history_ref = db.collection('users').document(current_user_id).collection('word_history').document(sanitized_word_id)
    
    try:
        word_doc = word_history_ref.get()
        if not word_doc.exists:
            return jsonify({'error': 'Word not found in history. Generate content first.'}), 404
        
        current_favorite_status = word_doc.to_dict().get('is_favorite', False)
        new_favorite_status = not current_favorite_status
        word_history_ref.update({'is_favorite': new_favorite_status})
        
        return jsonify({'message': 'Favorite status updated', 'word': word, 'is_favorite': new_favorite_status}), 200
    except Exception as e:
        app.logger.error(f"Error toggling favorite for user '{current_user_id}', word '{word}': {e}", exc_info=True)
        return jsonify({'error': f'Failed to toggle favorite: {str(e)}'}), 500

@app.route('/profile', methods=['GET'])
@token_required
def get_profile(current_user_id):
    if not db: return jsonify({"error": "Database not initialized"}), 503
    try:
        user_doc = db.collection('users').document(current_user_id).get()
        if not user_doc.exists:
            return jsonify({'error': 'User not found'}), 404
        
        user_data = user_doc.to_dict()
        
        word_history_docs = db.collection('users').document(current_user_id).collection('word_history').order_by('last_explored_at', direction=firestore.Query.DESCENDING).stream()
        explored_words = []
        favorite_words = []
        for doc in word_history_docs:
            word_info = doc.to_dict()
            # Ensure timestamp is serializable (ISO format)
            last_explored_at_ts = word_info.get('last_explored_at')
            first_explored_at_ts = word_info.get('first_explored_at')
            word_entry = {
                'id': doc.id,
                'word': word_info.get('word'),
                'first_explored_at': first_explored_at_ts.isoformat() if isinstance(first_explored_at_ts, datetime) else str(first_explored_at_ts),
                'last_explored_at': last_explored_at_ts.isoformat() if isinstance(last_explored_at_ts, datetime) else str(last_explored_at_ts),
                'is_favorite': word_info.get('is_favorite', False),
                'modes_generated': word_info.get('modes_generated', [])
            }
            explored_words.append(word_entry)
            if word_info.get('is_favorite'):
                favorite_words.append(word_entry)

        streak_docs = db.collection('users').document(current_user_id).collection('streaks').order_by('completed_at', direction=firestore.Query.DESCENDING).stream()
        streak_history = []
        for doc in streak_docs:
            streak_data = doc.to_dict()
            completed_at_ts = streak_data.get('completed_at')
            streak_history.append({
                'id': doc.id,
                'words': streak_data.get('words'),
                'score': streak_data.get('score'),
                'completed_at': completed_at_ts.isoformat() if isinstance(completed_at_ts, datetime) else str(completed_at_ts)
            })
            
        profile_data = {
            'username': user_data.get('username'),
            'email': user_data.get('email'),
            'tier': user_data.get('tier', 'free'),
            'total_words_explored': len(explored_words), 
            'explored_words': explored_words,
            'favorite_words': favorite_words, 
            'streak_history': streak_history
        }
        return jsonify(profile_data), 200

    except Exception as e:
        app.logger.error(f"Error fetching profile for user '{current_user_id}': {e}", exc_info=True)
        return jsonify({'error': f'Failed to fetch profile: {str(e)}'}), 500

@app.route('/save_streak', methods=['POST'])
@token_required
def save_streak(current_user_id):
    if not db: return jsonify({"error": "Database not initialized"}), 503
    data = request.get_json()
    words = data.get('words')
    score = data.get('score')

    if not isinstance(words, list) or not words or not isinstance(score, int) or score < 2: 
        return jsonify({'error': 'Invalid streak data. Words must be a non-empty list and score >= 2.'}), 400

    try:
        streaks_collection_ref = db.collection('users').document(current_user_id).collection('streaks')
        streak_doc_ref = streaks_collection_ref.document() 
        streak_doc_ref.set({
            'words': words,
            'score': score,
            'completed_at': firestore.SERVER_TIMESTAMP
        })
        return jsonify({'message': 'Streak saved successfully', 'streak_id': streak_doc_ref.id}), 201
    except Exception as e:
        app.logger.error(f"Error saving streak for user '{current_user_id}': {e}", exc_info=True)
        return jsonify({'error': f'Failed to save streak: {str(e)}'}), 500

@app.route('/save_quiz_attempt', methods=['POST'])
@token_required
def save_quiz_attempt(current_user_id):
    if not db: return jsonify({"error": "Database not initialized"}), 503
    data = request.get_json()
    word = data.get('word')
    question_index = data.get('question_index')
    selected_option_key = data.get('selected_option_key')
    is_correct = data.get('is_correct')

    if not word or question_index is None or not selected_option_key or is_correct is None:
        return jsonify({'error': 'Missing required quiz attempt data'}), 400

    sanitized_word_id = sanitize_word_for_id(word)
    word_history_ref = db.collection('users').document(current_user_id).collection('word_history').document(sanitized_word_id)

    try:
        word_doc = word_history_ref.get()
        if not word_doc.exists:
            return jsonify({'error': 'Word not found in history. Generate quiz content first.'}), 404
        
        quiz_progress = word_doc.to_dict().get('quiz_progress', [])
        
        attempt_exists = False
        for attempt in quiz_progress:
            if attempt.get('question_index') == question_index:
                attempt['selected_option_key'] = selected_option_key
                attempt['is_correct'] = is_correct
                attempt['timestamp'] = datetime.now(timezone.utc).isoformat()
                attempt_exists = True
                break
        
        if not attempt_exists:
            quiz_progress.append({
                "question_index": question_index,
                "selected_option_key": selected_option_key,
                "is_correct": is_correct,
                "timestamp": datetime.now(timezone.utc).isoformat() 
            })

        word_history_ref.update({"quiz_progress": quiz_progress, "last_explored_at": firestore.SERVER_TIMESTAMP})
        
        app.logger.info(f"Quiz attempt saved for user '{current_user_id}', word '{word}', q_idx {question_index}")
        return jsonify({"message": "Quiz attempt saved", "quiz_progress": quiz_progress}), 200

    except Exception as e:
        app.logger.error(f"Error saving quiz attempt for user '{current_user_id}', word '{word}': {e}", exc_info=True)
        return jsonify({"error": f"Failed to save quiz attempt: {str(e)}"}), 500


@app.route('/', methods=['GET'])
def health_check():
    return jsonify({"status": "Healthy", "timestamp": datetime.now(timezone.utc).isoformat()}), 200


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5001))
    app.run(host='0.0.0.0', port=port, debug=os.getenv('FLASK_DEBUG', 'False').lower() == 'true')

