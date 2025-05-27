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
# Applied globally first, then potentially refined per route if needed.
# The report implies specific origins, which is good practice.
CORS(app, 
     resources={r"/*": {"origins": [
         "https://tiny-tutor-app-frontend.onrender.com", # Your deployed frontend
         "http://localhost:5173", # Local Vite dev server
         "http://127.0.0.1:5173"  # Alternate local Vite dev server
     ]}}, 
     supports_credentials=True,
     # automatic_options=True is default and usually handles OPTIONS requests.
     # We ensure our decorator doesn't interfere.
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"], # Explicitly list methods
     allow_headers=["Content-Type", "Authorization", "X-Requested-With"] # Explicitly list allowed headers
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
    db = None # Ensure db is None if initialization fails

# --- Rate Limiter Initialization (as per project report) ---
# This needs to be configured carefully not to block OPTIONS requests.
# Flask-CORS should ideally handle OPTIONS before the limiter if hooks are ordered correctly.
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"], # Example limits
    storage_uri="memory://", # For Render, consider a persistent store if needed across instances
    # strategy="fixed-window" # or "moving-window"
)

# Exempt OPTIONS requests from rate limiting if Flask-CORS doesn't handle it early enough
@app.before_request
def exempt_options_from_limit():
    if request.method == 'OPTIONS':
        # This attribute name can vary based on Flask-Limiter version or specific setup
        # For some versions, you might need to interact with the limiter instance directly
        # or ensure Flask-CORS handles the OPTIONS response before the limiter's check.
        # A common approach is that Flask-CORS responds to OPTIONS, so the limiter isn't hit.
        # If issues persist, consult Flask-Limiter documentation for exempting methods.
        pass # Let Flask-CORS handle it. If limiter still blocks, this needs more specific handling.


# --- Gemini API Configuration ---
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    app.logger.warning("GEMINI_API_KEY environment variable not set. AI features will not work.")
    genai.configure(api_key="DUMMY_KEY_FOR_INITIALIZATION_ONLY") # Configure with a dummy if not set, to avoid startup error
else:
    genai.configure(api_key=GEMINI_API_KEY)

# --- Helper Functions ---
def sanitize_word_for_id(word):
    """Sanitizes a word to be used as a Firestore document ID."""
    sanitized = re.sub(r'[^a-zA-Z0-9-_]', '_', word.lower())
    return sanitized[:100] # Limit length for Firestore ID

# --- Token Required Decorator (FIX 3 Applied) ---
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # FIX 3: Allow OPTIONS requests to pass through for CORS preflight
        if request.method == 'OPTIONS':
            # Flask-CORS should ideally handle the response headers.
            # Returning a 204 No Content or 200 OK allows the preflight to succeed.
            # The actual CORS headers (Allow-Origin, Allow-Methods, Allow-Headers)
            # are typically added by the Flask-CORS extension globally or per-route.
            return "", 204 # Standard response for successful preflight

        token = None
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(" ")[1]

        if not token:
            return jsonify({'message': 'Token is missing!'}), 401

        try:
            # Use current_app.config for accessing app configuration in decorators
            data = jwt.decode(token, current_app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
            current_user_id = data['user_id'] 
        except jwt.ExpiredSignatureError:
            current_app.logger.warning("Token expired.")
            return jsonify({'message': 'Token has expired!'}), 401
        except jwt.InvalidTokenError:
            current_app.logger.warning("Invalid token.")
            return jsonify({'message': 'Token is invalid!'}), 401
        except Exception as e:
            current_app.logger.error(f"Token validation error: {e}", exc_info=True)
            return jsonify({'message': 'Token processing error!'}), 500 # Use 500 for unexpected server errors
        
        return f(current_user_id, *args, **kwargs)
    return decorated

# --- API Endpoints ---
@app.route('/signup', methods=['POST'])
def signup():
    if not db: return jsonify({"error": "Database not initialized"}), 503
    data = request.get_json()
    if not data or not data.get('username') or not data.get('email') or not data.get('password'):
        return jsonify({'error': 'Missing username, email, or password'}), 400

    username = data['username'].strip()
    email = data['email'].strip().lower()
    
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return jsonify({'error': 'Invalid email format'}), 400
    if len(data['password']) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400
    if len(username) < 3:
        return jsonify({'error': 'Username must be at least 3 characters'}), 400

    users_ref = db.collection('users')
    # Check if username or email already exists
    if users_ref.where('username_lowercase', '==', username.lower()).limit(1).get():
        return jsonify({'error': 'Username already exists'}), 409
    if users_ref.where('email', '==', email).limit(1).get():
        return jsonify({'error': 'Email already registered'}), 409

    hashed_password = generate_password_hash(data['password'])
    user_doc_ref = users_ref.document() # Auto-generate ID
    user_id = user_doc_ref.id
    user_data = {
        'user_id': user_id, # Store the auto-generated ID also in the document
        'username': username,
        'username_lowercase': username.lower(),
        'email': email,
        'password_hash': hashed_password,
        'tier': 'free', # Default tier
        'created_at': firestore.SERVER_TIMESTAMP
    }
    user_doc_ref.set(user_data)
    
    # Create JWT token for immediate login
    token = jwt.encode({
        'user_id': user_id,
        'username': username,
        'exp': datetime.now(timezone.utc) + current_app.config['JWT_ACCESS_TOKEN_EXPIRES']
    }, current_app.config['JWT_SECRET_KEY'], algorithm='HS256')

    return jsonify({'message': 'User created successfully', 'token': token, 'username': username, 'userId': user_id}), 201


@app.route('/login', methods=['POST'])
def login():
    if not db: return jsonify({"error": "Database not initialized"}), 503
    data = request.get_json()
    if not data or not (data.get('email_or_username') and data.get('password')):
        return jsonify({'error': 'Missing email/username or password'}), 400

    login_identifier = data['email_or_username'].strip()
    password = data['password']
    
    users_ref = db.collection('users')
    user_query = users_ref.where('email', '==', login_identifier.lower()).limit(1).get()
    if not user_query:
        user_query = users_ref.where('username_lowercase', '==', login_identifier.lower()).limit(1).get()

    if not user_query:
        return jsonify({'error': 'Invalid credentials'}), 401
    
    user_data = user_query[0].to_dict()
    user_id = user_query[0].id # Get document ID as user_id

    if not check_password_hash(user_data['password_hash'], password):
        return jsonify({'error': 'Invalid credentials'}), 401

    token = jwt.encode({
        'user_id': user_id, # Use Firestore document ID
        'username': user_data['username'],
        'exp': datetime.now(timezone.utc) + current_app.config['JWT_ACCESS_TOKEN_EXPIRES']
    }, current_app.config['JWT_SECRET_KEY'], algorithm='HS256')

    return jsonify({'token': token, 'username': user_data['username'], 'userId': user_id}), 200

@app.route('/generate_explanation', methods=['POST'])
@token_required
def generate_explanation_route(current_user_id):
    if not db: return jsonify({"error": "Database not initialized"}), 503
    if not GEMINI_API_KEY or GEMINI_API_KEY == "DUMMY_KEY_FOR_INITIALIZATION_ONLY":
        return jsonify({"error": "AI service not configured on server."}), 503

    data = request.get_json()
    word = data.get('word')
    mode = data.get('mode', 'explain') # explain, fact, quiz, image, deep_dive
    refresh_cache = data.get('refresh_cache', False)

    if not word:
        return jsonify({'error': 'Word is required'}), 400

    sanitized_word_id = sanitize_word_for_id(word)
    user_word_history_ref = db.collection('users').document(current_user_id).collection('word_history').document(sanitized_word_id)
    
    try:
        word_doc = user_word_history_ref.get()
        content_to_return = None
        generated_content_cache = {}
        modes_generated = []
        is_favorite = False
        quiz_progress = []

        if word_doc.exists:
            word_data = word_doc.to_dict()
            generated_content_cache = word_data.get('generated_content_cache', {})
            modes_generated = word_data.get('modes_generated', [])
            is_favorite = word_data.get('is_favorite', False)
            quiz_progress = word_data.get('quiz_progress', [])
            if mode in generated_content_cache and not refresh_cache:
                content_to_return = generated_content_cache[mode]
        
        if content_to_return is None or refresh_cache:
            app.logger.info(f"Generating content for word '{word}', mode '{mode}' for user '{current_user_id}' (Refresh: {refresh_cache})")
            
            model = genai.GenerativeModel('gemini-1.5-flash-latest') # Or your preferred model
            prompt = ""
            if mode == 'explain':
                prompt = f"Explain the concept or word '{word}' in 2-4 concise sentences. Identify up to 3 key sub-topics within your explanation and enclose them in <click> and </click> tags. For example: <click>Sub-topic A</click>."
            elif mode == 'fact':
                prompt = f"Tell me one single, concise, interesting fact about '{word}'."
            elif mode == 'quiz':
                 # Expects 1-3 questions, each with Q, 4 options (A,B,C,D), and correct answer marked.
                 # Questions separated by "---QUIZ_SEPARATOR---"
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
            elif mode == 'image': # Placeholder
                content_to_return = f"Placeholder image content for {word}."
            elif mode == 'deep_dive': # Placeholder
                content_to_return = f"Placeholder deep dive content for {word}."
            else:
                return jsonify({'error': 'Invalid content mode'}), 400

            if mode not in ['image', 'deep_dive']: # Don't call Gemini for placeholders
                try:
                    response = model.generate_content(prompt)
                    content_to_return = response.text
                    if mode == 'quiz' and refresh_cache: # If refreshing quiz, reset progress
                        quiz_progress = [] 
                except Exception as e:
                    app.logger.error(f"Gemini API error for word '{word}', mode '{mode}': {e}", exc_info=True)
                    return jsonify({'error': f'Failed to generate content from AI: {e}'}), 500
            
            generated_content_cache[mode] = content_to_return
            if mode not in modes_generated:
                modes_generated.append(mode)

            # Update Firestore
            if word_doc.exists:
                user_word_history_ref.update({
                    'generated_content_cache': generated_content_cache,
                    'modes_generated': modes_generated,
                    'last_explored_at': firestore.SERVER_TIMESTAMP,
                    'quiz_progress': quiz_progress # Update quiz_progress if it was reset
                })
            else:
                user_word_history_ref.set({
                    'word': word,
                    'generated_content_cache': generated_content_cache,
                    'modes_generated': modes_generated,
                    'is_favorite': False,
                    'quiz_progress': quiz_progress,
                    'first_explored_at': firestore.SERVER_TIMESTAMP,
                    'last_explored_at': firestore.SERVER_TIMESTAMP
                })
        
        return jsonify({
            'word': word,
            'mode': mode,
            'content': content_to_return,
            'generated_content_cache': generated_content_cache, # Send the whole cache
            'modes_generated': modes_generated,
            'is_favorite': is_favorite,
            'quiz_progress': quiz_progress
        }), 200

    except Exception as e:
        app.logger.error(f"Error in /generate_explanation for user '{current_user_id}', word '{word}': {e}", exc_info=True)
        return jsonify({'error': f'An unexpected error occurred: {e}'}), 500


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
        return jsonify({'error': f'Failed to toggle favorite: {e}'}), 500

@app.route('/profile', methods=['GET'])
@token_required
def get_profile(current_user_id):
    if not db: return jsonify({"error": "Database not initialized"}), 503
    try:
        user_doc = db.collection('users').document(current_user_id).get()
        if not user_doc.exists:
            return jsonify({'error': 'User not found'}), 404
        
        user_data = user_doc.to_dict()
        
        # Fetch word history
        word_history_docs = db.collection('users').document(current_user_id).collection('word_history').order_by('last_explored_at', direction=firestore.Query.DESCENDING).stream()
        explored_words = []
        favorite_words = []
        for doc in word_history_docs:
            word_info = doc.to_dict()
            word_entry = {
                'id': doc.id,
                'word': word_info.get('word'),
                'last_explored_at': word_info.get('last_explored_at').isoformat() if word_info.get('last_explored_at') else None,
                'is_favorite': word_info.get('is_favorite', False),
                # Add other relevant fields if needed by frontend profile view
            }
            explored_words.append(word_entry)
            if word_info.get('is_favorite'):
                favorite_words.append(word_entry)

        # Fetch streak history
        streak_docs = db.collection('users').document(current_user_id).collection('streaks').order_by('completed_at', direction=firestore.Query.DESCENDING).stream()
        streak_history = []
        for doc in streak_docs:
            streak_data = doc.to_dict()
            streak_history.append({
                'id': doc.id,
                'words': streak_data.get('words'),
                'score': streak_data.get('score'),
                'completed_at': streak_data.get('completed_at').isoformat() if streak_data.get('completed_at') else None
            })
            
        profile_data = {
            'username': user_data.get('username'),
            'email': user_data.get('email'),
            'tier': user_data.get('tier', 'free'),
            'total_words_explored': len(explored_words), # Simple count
            'explored_words': explored_words,
            'favorite_words': favorite_words, # Already sorted by recency due to explored_words sort
            'streak_history': streak_history
        }
        return jsonify(profile_data), 200

    except Exception as e:
        app.logger.error(f"Error fetching profile for user '{current_user_id}': {e}", exc_info=True)
        return jsonify({'error': f'Failed to fetch profile: {e}'}), 500

@app.route('/save_streak', methods=['POST'])
@token_required
def save_streak(current_user_id):
    if not db: return jsonify({"error": "Database not initialized"}), 503
    data = request.get_json()
    words = data.get('words')
    score = data.get('score')

    if not isinstance(words, list) or not words or not isinstance(score, int) or score < 2: # Min streak score 2
        return jsonify({'error': 'Invalid streak data. Words must be a non-empty list and score >= 2.'}), 400

    try:
        streaks_collection_ref = db.collection('users').document(current_user_id).collection('streaks')
        streak_doc_ref = streaks_collection_ref.document() # Auto-generate ID
        streak_doc_ref.set({
            'words': words,
            'score': score,
            'completed_at': firestore.SERVER_TIMESTAMP
        })
        return jsonify({'message': 'Streak saved successfully', 'streak_id': streak_doc_ref.id}), 201
    except Exception as e:
        app.logger.error(f"Error saving streak for user '{current_user_id}': {e}", exc_info=True)
        return jsonify({'error': f'Failed to save streak: {e}'}), 500

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
        
        # Update existing attempt or add new one
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
        return jsonify({"error": f"Failed to save quiz attempt: {e}"}), 500


# Basic health check endpoint
@app.route('/', methods=['GET'])
def health_check():
    return jsonify({"status": "Healthy", "timestamp": datetime.now(timezone.utc).isoformat()}), 200


if __name__ == '__main__':
    # This block is mainly for local development.
    # Render uses a Gunicorn command specified in its settings (e.g., gunicorn app:app).
    port = int(os.environ.get("PORT", 5001))
    # Set debug=False for production or when testing with Gunicorn locally
    # For local dev, debug=True can be helpful.
    app.run(host='0.0.0.0', port=port, debug=os.getenv('FLASK_DEBUG', 'False').lower() == 'true')
