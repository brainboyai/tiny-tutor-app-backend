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
import requests
import jwt
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash, check_password_hash

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

# JWT Configuration
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'YOUR_VERY_STRONG_RANDOM_SECRET_KEY_IN_DOTENV') # IMPORTANT
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)

# --- Firebase Initialization ---
service_account_key_base64 = os.getenv('FIREBASE_SERVICE_ACCOUNT_KEY_BASE64')
db = None
if service_account_key_base64:
    try:
        decoded_key_bytes = base64.b64decode(service_account_key_base64)
        decoded_key_str = decoded_key_bytes.decode('utf-8')
        cred_json = json.loads(decoded_key_str)
        if 'project_id' not in cred_json:
            print("Warning: 'project_id' not found in Firebase service account key.")
            # Consider not raising an error here to allow app to start, but log prominently
            # raise ValueError("Firebase service account key is missing 'project_id'.")
        cred = credentials.Certificate(cred_json)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("Firebase initialized successfully.")
    except json.JSONDecodeError as e:
        print(f"Error decoding Firebase service account JSON: {e}")
    except ValueError as e:
        print(f"Firebase key validation error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred initializing Firebase: {e}")
else:
    print("FIREBASE_SERVICE_ACCOUNT_KEY_BASE64 not set. Firebase not initialized.")

# --- Helper Functions ---
def sanitize_word_for_firestore(word: str) -> str:
    if not isinstance(word, str): return ""
    sanitized = word.strip().lower()
    sanitized = re.sub(r'[/*\[\]]', '_', sanitized)
    return sanitized[:100] # Max length for a part of a document ID

# Decorator for JWT authentication
def jwt_required(f):
    def decorated_function(*args, **kwargs):
        token = None
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            try: token = auth_header.split(" ")[1]
            except IndexError: return jsonify({"error": "Token format is 'Bearer <token>'"}), 403
        if not token: return jsonify({"error": "Authentication token is missing!"}), 401
        try:
            data = jwt.decode(token, app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
            request.current_user_jwt = data
        except jwt.ExpiredSignatureError: return jsonify({"error": "Token has expired!"}), 401
        except jwt.InvalidTokenError: return jsonify({"error": "Invalid token!"}), 401
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

# --- Routes ---
@app.route('/')
def home(): return "Tiny Tutor Backend is running!"

@app.route('/signup', methods=['POST'])
def signup():
    data = request.get_json()
    username, email, password = data.get('username'), data.get('email'), data.get('password')
    if not all([username, email, password]): return jsonify({"error": "Missing fields"}), 400
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email): return jsonify({"error": "Invalid email"}), 400
    if len(password) < 6: return jsonify({"error": "Password too short"}), 400
    if db is None: return jsonify({"error": "Database service unavailable"}), 503
    users_ref = db.collection('users')
    if users_ref.where('username', '==', username).limit(1).get(): return jsonify({"error": "Username exists"}), 409
    if users_ref.where('email', '==', email).limit(1).get(): return jsonify({"error": "Email exists"}), 409
    hashed_password = generate_password_hash(password)
    try:
        users_ref.document(username).set({
            'username': username, 'email': email, 'password': hashed_password,
            'tier': 'basic', 'created_at': firestore.SERVER_TIMESTAMP
        })
        return jsonify({"message": "User registered"}), 201
    except Exception as e: return jsonify({"error": f"Registration failed: {e}"}), 500

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username, password = data.get('username'), data.get('password')
    if not username or not password: return jsonify({"error": "Missing fields"}), 400
    if db is None: return jsonify({"error": "Database service unavailable"}), 503
    user_doc_snapshot = db.collection('users').document(username).get()
    if not user_doc_snapshot.exists: return jsonify({"error": "Invalid credentials"}), 401
    user_data = user_doc_snapshot.to_dict()
    if user_data and user_data.get('password') and check_password_hash(user_data['password'], password):
        access_token = jwt.encode({
            'user_id': user_doc_snapshot.id, 'username': user_data['username'],
            'tier': user_data.get('tier', 'basic'),
            'exp': datetime.now(timezone.utc) + app.config['JWT_ACCESS_TOKEN_EXPIRES']
        }, app.config['JWT_SECRET_KEY'], algorithm='HS256')
        return jsonify(access_token=access_token), 200
    return jsonify({"error": "Invalid credentials"}), 401

@app.route('/generate_explanation', methods=['POST'])
@jwt_required
def generate_explanation_and_log_word():
    data = request.get_json()
    question, content_type = data.get('question'), data.get('content_type', 'explain')
    if not question: return jsonify({"error": "Missing question"}), 400
    
    user_jwt_data = request.current_user_jwt
    user_id = user_jwt_data.get('user_id')
    if not user_id: return jsonify({"error": "User ID not found in token"}), 401
    if db is None: return jsonify({"error": "Database service unavailable"}), 503

    placeholder_image_text = "Image generation feature coming soon! You can imagine an image of '{question}'."
    placeholder_deep_text = "In-depth explanation feature coming soon! We're working on providing more detailed insights for '{question}'."
    
    sanitized_word_id = sanitize_word_for_firestore(question)
    word_doc_ref = db.collection('users').document(user_id).collection('word_history').document(sanitized_word_id)
    word_doc_snapshot = word_doc_ref.get() # Get snapshot once
    current_timestamp = firestore.SERVER_TIMESTAMP
    
    explanation_text_to_return = ""

    if content_type == 'image':
        explanation_text_to_return = placeholder_image_text.format(question=question)
    elif content_type == 'deep':
        explanation_text_to_return = placeholder_deep_text.format(question=question)
    
    if content_type in ['image', 'deep']:
        try:
            if word_doc_snapshot.exists:
                existing_data = word_doc_snapshot.to_dict()
                modes_generated = existing_data.get('modes_generated', [])
                if content_type not in modes_generated: modes_generated.append(content_type)
                word_doc_ref.update({
                    'last_explored_at': current_timestamp,
                    'modes_generated': modes_generated,
                    f'generated_content_cache.{content_type}': explanation_text_to_return 
                })
            else:
                word_doc_ref.set({
                    'word': question, 'sanitized_word': question.strip().lower(), 'is_favorite': False,
                    'first_explored_at': current_timestamp, 'last_explored_at': current_timestamp,
                    'modes_generated': [content_type],
                    'generated_content_cache': {content_type: explanation_text_to_return}
                })
            return jsonify({"explanation": explanation_text_to_return}), 200
        except Exception as e:
            print(f"Error logging placeholder for {content_type}: {e}")
            return jsonify({"explanation": explanation_text_to_return, "warning": "History not saved for placeholder."}), 200

    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
    GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
    if not GEMINI_API_KEY: return jsonify({"error": "Gemini API key missing"}), 500

    prompt_templates = {
        'explain': "Provide a concise, easy-to-understand explanation for '{question}'.",
        'fact': "Give one interesting fact about '{question}'.",
        'quiz': "Generate a simple multiple-choice quiz about '{question}' with 4 options and the correct answer (e.g., 'Correct: C) ...')."
    }
    prompt_template = prompt_templates.get(content_type)
    if not prompt_template: return jsonify({"error": "Invalid content type for API call."}), 400
    if user_jwt_data.get('tier') == 'premium' and content_type == 'explain':
        prompt_template = "Provide a comprehensive, detailed explanation for '{question}', with analogies."
    
    prompt = prompt_template.format(question=question)
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        response = requests.post(GEMINI_API_URL, headers={"Content-Type": "application/json"}, params={"key": GEMINI_API_KEY}, json=payload, timeout=25)
        response.raise_for_status()
        gemini_result = response.json()

        if gemini_result and 'candidates' in gemini_result and gemini_result['candidates']:
            generated_text = gemini_result['candidates'][0]['content']['parts'][0]['text']
            explanation_text_to_return = generated_text

            if word_doc_snapshot.exists:
                existing_data = word_doc_snapshot.to_dict()
                modes_generated = existing_data.get('modes_generated', [])
                if content_type not in modes_generated: modes_generated.append(content_type)
                word_doc_ref.update({
                    'last_explored_at': current_timestamp,
                    'modes_generated': modes_generated,
                    f'generated_content_cache.{content_type}': explanation_text_to_return
                })
            else:
                word_doc_ref.set({
                    'word': question, 'sanitized_word': question.strip().lower(), 'is_favorite': False,
                    'first_explored_at': current_timestamp, 'last_explored_at': current_timestamp,
                    'modes_generated': [content_type],
                    'generated_content_cache': {content_type: explanation_text_to_return}
                })
            return jsonify({"explanation": explanation_text_to_return}), 200
        else:
            return jsonify({"error": "Failed to generate content from AI."}), 500
    except requests.exceptions.Timeout: return jsonify({"error": "AI service request timed out."}), 504
    except requests.exceptions.RequestException as e: return jsonify({"error": f"AI service error: {e}"}), 502
    except Exception as e: return jsonify({"error": f"Unexpected error: {e}"}), 500

@app.route('/toggle_favorite', methods=['POST'])
@jwt_required
def toggle_favorite():
    data = request.get_json()
    word_to_toggle = data.get('word')
    if not word_to_toggle: return jsonify({"error": "Missing 'word'"}), 400
    user_id = request.current_user_jwt.get('user_id')
    if not user_id or db is None: return jsonify({"error": "User/DB error"}), 500
    sanitized_word_id = sanitize_word_for_firestore(word_to_toggle)
    word_doc_ref = db.collection('users').document(user_id).collection('word_history').document(sanitized_word_id)
    try:
        word_doc = word_doc_ref.get()
        if not word_doc.exists: return jsonify({"error": "Word not in history"}), 404
        current_is_favorite = word_doc.to_dict().get('is_favorite', False)
        new_favorite_status = not current_is_favorite
        word_doc_ref.update({'is_favorite': new_favorite_status})
        return jsonify({"word": word_to_toggle, "sanitized_word_id": sanitized_word_id, "is_favorite": new_favorite_status, "message": "Favorite updated"}), 200
    except Exception as e: return jsonify({"error": f"Update failed: {e}"}), 500

@app.route('/profile', methods=['GET'])
@jwt_required
def get_profile_data():
    user_id = request.current_user_jwt.get('user_id')
    if not user_id or db is None: return jsonify({"error": "User/DB error"}), 500
    word_history_coll_ref = db.collection('users').document(user_id).collection('word_history')
    try:
        all_words_query = word_history_coll_ref.order_by('last_explored_at', direction=firestore.Query.DESCENDING).stream()
        explored_words, favorite_words = [], []
        for doc in all_words_query:
            data = doc.to_dict()
            display_word = {
                "id": doc.id, "word": data.get('word', 'N/A'),
                "is_favorite": data.get('is_favorite', False),
                "last_explored_at": data['last_explored_at'].isoformat() if 'last_explored_at' in data and hasattr(data['last_explored_at'], 'isoformat') else None,
                "generated_content_cache": data.get('generated_content_cache', {}), 
                "modes_generated": data.get('modes_generated', [])
            }
            explored_words.append(display_word)
            if display_word["is_favorite"]: favorite_words.append(display_word)
        return jsonify({
            "username": request.current_user_jwt.get('username'), "tier": request.current_user_jwt.get('tier'),
            "explored_words_count": len(explored_words),
            "explored_words_list": explored_words, "favorite_words_list": favorite_words
        }), 200
    except Exception as e: return jsonify({"error": f"Profile fetch failed: {e}"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=os.environ.get('FLASK_DEBUG', '1') == '1')
