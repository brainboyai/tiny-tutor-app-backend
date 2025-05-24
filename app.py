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
from datetime import datetime, timedelta, timezone # Added timezone
from werkzeug.security import generate_password_hash, check_password_hash

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# Configure CORS
CORS(app, resources={r"/*": {"origins": [
        "https://tiny-tutor-app-frontend.onrender.com", # Your frontend on Render
        "http://localhost:5173",                      # Your local development frontend
        "http://127.0.0.1:5173"                       # Common local dev alias
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
        
        # Basic check for a common field to ensure the key is somewhat valid
        if 'project_id' not in cred_json:
            print("Warning: 'project_id' not found in Firebase service account key. This might indicate an issue with the key.")
            raise ValueError("Firebase service account key is missing 'project_id'.")

        cred = credentials.Certificate(cred_json)
        if not firebase_admin._apps: # Initialize only if no app is already initialized
            firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("Firebase initialized successfully.")
    except json.JSONDecodeError as e:
        print(f"Error decoding Firebase service account JSON: {e}")
        print("Ensure FIREBASE_SERVICE_ACCOUNT_KEY_BASE64 is a valid Base64 encoded JSON string.")
    except ValueError as e: # Catch our custom ValueError
        print(f"Firebase key validation error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred initializing Firebase: {e}")
        print("Firebase might not be initialized. Check environment variables and key format.")
else:
    print("FIREBASE_SERVICE_ACCOUNT_KEY_BASE64 environment variable not set. Firebase will not be initialized.")


# --- Helper Functions ---
def sanitize_word_for_firestore(word: str) -> str:
    """Sanitizes a word for use as a Firestore document ID or for querying.
       Replaces characters not allowed in document IDs and converts to lowercase.
    """
    if not isinstance(word, str):
        return ""
    # Firestore document IDs must not contain / * [ ]
    # Also, let's make it lowercase and trim whitespace for consistency.
    sanitized = word.strip().lower()
    # Replace problematic characters with underscores or remove them
    sanitized = re.sub(r'[/*\[\]]', '_', sanitized)
    # If it's too long, truncate (Firestore ID limit is 1500 bytes)
    # This is a basic truncation, consider a more robust approach if needed
    return sanitized[:100] # Truncate to a reasonable length for an ID part


# Decorator for JWT authentication
def jwt_required(f):
    def decorated_function(*args, **kwargs):
        token = None
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            try:
                token = auth_header.split(" ")[1]
            except IndexError:
                return jsonify({"error": "Token format is 'Bearer <token>'"}), 403
        
        if not token:
            return jsonify({"error": "Authentication token is missing!"}), 401

        try:
            # Decode the token using the secret key
            data = jwt.decode(token, app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
            request.current_user_jwt = data # Attach user payload to request object
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token has expired!"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token!"}), 401
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__ # Preserve original function name
    return decorated_function

# --- Routes ---
@app.route('/')
def home():
    return "Tiny Tutor Backend is running!"

@app.route('/signup', methods=['POST'])
def signup():
    data = request.get_json()
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')

    if not all([username, email, password]):
        return jsonify({"error": "Missing username, email, or password"}), 400
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email): # Basic email regex
        return jsonify({"error": "Invalid email format"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters long"}), 400

    if db is None: # Check if Firebase was initialized
        return jsonify({"error": "Database service is not available. Please contact support."}), 503

    users_ref = db.collection('users')
    # Check if username or email already exists
    if users_ref.where('username', '==', username).limit(1).get():
        return jsonify({"error": "Username already exists"}), 409
    if users_ref.where('email', '==', email).limit(1).get():
        return jsonify({"error": "Email already exists"}), 409

    hashed_password = generate_password_hash(password)
    try:
        # Use username as the document ID for the users collection for easier direct access
        user_doc_ref = users_ref.document(username) 
        user_doc_ref.set({
            'username': username,
            'email': email,
            'password': hashed_password, # Store hashed password
            'tier': 'basic', # Default tier
            'created_at': firestore.SERVER_TIMESTAMP
        })
        print(f"User '{username}' signed up successfully.")
        return jsonify({"message": "User registered successfully"}), 201
    except Exception as e:
        print(f"Error during signup for user '{username}': {e}")
        return jsonify({"error": f"Failed to register user: {str(e)}"}), 500


@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({"error": "Missing username or password"}), 400
    if db is None:
        return jsonify({"error": "Database service is not available."}), 503

    users_ref = db.collection('users')
    # Fetch user by document ID (username)
    user_doc_ref = users_ref.document(username)
    user_doc_snapshot = user_doc_ref.get()

    if not user_doc_snapshot.exists:
        print(f"Login failed: Username '{username}' not found.")
        return jsonify({"error": "Invalid username or password"}), 401
    
    user_data = user_doc_snapshot.to_dict()

    if user_data and user_data.get('password') and check_password_hash(user_data['password'], password):
        # Password matches
        access_token = jwt.encode({
            'user_id': user_doc_snapshot.id, # Use Firestore document ID (which is username) as user_id in JWT
            'username': user_data['username'], 
            'tier': user_data.get('tier', 'basic'),
            'exp': datetime.now(timezone.utc) + app.config['JWT_ACCESS_TOKEN_EXPIRES']
        }, app.config['JWT_SECRET_KEY'], algorithm='HS256')
        
        print(f"User '{username}' logged in successfully.")
        return jsonify(access_token=access_token), 200
    else:
        print(f"Login failed: Incorrect password for user '{username}'.")
        return jsonify({"error": "Invalid username or password"}), 401


@app.route('/generate_explanation', methods=['POST'])
@jwt_required
def generate_explanation_and_log_word():
    data = request.get_json()
    question = data.get('question') # This is the word/concept
    content_type = data.get('content_type', 'explain')

    if not question:
        return jsonify({"error": "Missing question (word/concept)"}), 400

    user_jwt_data = request.current_user_jwt
    user_id = user_jwt_data.get('user_id') # Get user_id from JWT (which is the username/document_id)
    
    if not user_id:
        return jsonify({"error": "User ID not found in token."}), 401
    if db is None:
        return jsonify({"error": "Database service is not available."}), 503

    # --- Call Gemini API (existing logic) ---
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
    GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
    if not GEMINI_API_KEY:
        return jsonify({"error": "Server configuration error: Gemini API key missing."}), 500

    prompt_templates = {
        'explain': "Provide a concise, easy-to-understand explanation for the concept '{question}'.",
        'fact': "Give me one interesting fact about '{question}'.",
        'quiz': "Generate a simple multiple-choice quiz question about '{question}' with 4 options and identify the correct answer (e.g., 'Correct Answer: C) Option C').",
        'deep': "Provide a detailed, in-depth explanation of '{question}', covering its background, key aspects, and significance.",
        'image': "Describe an image that could represent '{question}'. (Note: Image generation is a future feature.)"
    }
    prompt_template = prompt_templates.get(content_type, prompt_templates['explain'])
    # Tier-based prompt modification (example)
    if user_jwt_data.get('tier') == 'premium' and content_type == 'explain':
        prompt_template = "Provide a comprehensive, detailed, and easy-to-understand explanation for the concept '{question}'. Include analogies if helpful."
    
    prompt = prompt_template.format(question=question)
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {"Content-Type": "application/json"}
    params = {"key": GEMINI_API_KEY}

    try:
        response = requests.post(GEMINI_API_URL, headers=headers, params=params, json=payload, timeout=25) # 25s timeout
        response.raise_for_status()
        gemini_result = response.json()

        if gemini_result and 'candidates' in gemini_result and gemini_result['candidates']:
            explanation_text = gemini_result['candidates'][0]['content']['parts'][0]['text']
            
            # --- Log word to Firestore user's word_history ---
            # Use the original question (word) for display, but a sanitized version for document ID
            sanitized_word_id = sanitize_word_for_firestore(question)
            word_doc_ref = db.collection('users').document(user_id).collection('word_history').document(sanitized_word_id)
            
            word_doc_snapshot = word_doc_ref.get()
            current_timestamp = firestore.SERVER_TIMESTAMP

            if word_doc_snapshot.exists:
                # Word already explored, update last_explored_at and modes_generated
                existing_data = word_doc_snapshot.to_dict()
                modes_generated = existing_data.get('modes_generated', [])
                if content_type not in modes_generated:
                    modes_generated.append(content_type)
                
                update_data = {
                    'last_explored_at': current_timestamp,
                    'modes_generated': modes_generated
                }
                # Optionally update cache if it's a new 'explain' or a better explanation
                if content_type == 'explain':
                    update_data['first_explanation_cache'] = explanation_text # Or some logic to decide if this is better

                word_doc_ref.update(update_data)
            else:
                # New word for this user
                word_doc_ref.set({
                    'word': question, # Original casing for display
                    'sanitized_word': question.strip().lower(), # For querying if needed separately from ID
                    'is_favorite': False,
                    'first_explored_at': current_timestamp,
                    'last_explored_at': current_timestamp,
                    'modes_generated': [content_type],
                    'first_explanation_cache': explanation_text if content_type == 'explain' else ""
                })
            
            return jsonify({"explanation": explanation_text}), 200
        else:
            return jsonify({"error": "Failed to generate explanation from AI."}), 500

    except requests.exceptions.Timeout:
        return jsonify({"error": "AI service request timed out."}), 504 # Gateway Timeout
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"AI service connection error: {str(e)}"}), 502 # Bad Gateway
    except Exception as e:
        print(f"Unexpected error in /generate_explanation: {e}")
        return jsonify({"error": f"An unexpected error occurred: {str(e)}"}), 500

@app.route('/toggle_favorite', methods=['POST'])
@jwt_required
def toggle_favorite():
    data = request.get_json()
    word_to_toggle = data.get('word') # Expecting the original word string
    if not word_to_toggle:
        return jsonify({"error": "Missing 'word' in request"}), 400

    user_id = request.current_user_jwt.get('user_id')
    if not user_id or db is None:
        return jsonify({"error": "User not found or database error"}), 500

    sanitized_word_id = sanitize_word_for_firestore(word_to_toggle)
    word_doc_ref = db.collection('users').document(user_id).collection('word_history').document(sanitized_word_id)
    
    try:
        word_doc_snapshot = word_doc_ref.get()
        if not word_doc_snapshot.exists:
            # If word isn't in history, user can't favorite it. 
            # Alternatively, could add it here then favorite, but that might be unexpected.
            return jsonify({"error": "Word not found in history. Explore it first to favorite."}), 404
        
        current_is_favorite = word_doc_snapshot.to_dict().get('is_favorite', False)
        new_favorite_status = not current_is_favorite
        
        word_doc_ref.update({'is_favorite': new_favorite_status})
        return jsonify({
            "word": word_to_toggle, # Return original word for frontend consistency
            "sanitized_word_id": sanitized_word_id, # Return ID for frontend state update
            "is_favorite": new_favorite_status,
            "message": "Favorite status updated."
        }), 200
    except Exception as e:
        print(f"Error toggling favorite for word '{word_to_toggle}', user '{user_id}': {e}")
        return jsonify({"error": f"Failed to update favorite status: {str(e)}"}), 500

@app.route('/profile', methods=['GET'])
@jwt_required
def get_profile_data():
    user_id = request.current_user_jwt.get('user_id')
    if not user_id or db is None:
        return jsonify({"error": "User not found or database error"}), 500

    word_history_coll_ref = db.collection('users').document(user_id).collection('word_history')
    
    try:
        # Fetch all words, order by last explored (most recent first)
        # Consider adding .limit(N) if the list could become very long
        all_words_query = word_history_coll_ref.order_by('last_explored_at', direction=firestore.Query.DESCENDING).stream()
        
        explored_words_list = []
        favorite_words_list = []
        
        for doc_snapshot in all_words_query:
            word_data = doc_snapshot.to_dict()
            
            # Convert Firestore timestamp to ISO string for JSON serialization
            if 'last_explored_at' in word_data and hasattr(word_data['last_explored_at'], 'isoformat'):
                word_data['last_explored_at_iso'] = word_data['last_explored_at'].isoformat()
            if 'first_explored_at' in word_data and hasattr(word_data['first_explored_at'], 'isoformat'):
                word_data['first_explored_at_iso'] = word_data['first_explored_at'].isoformat()

            # Prepare data for frontend
            display_word = {
                "id": doc_snapshot.id, # This is the sanitized_word_id
                "word": word_data.get('word', 'N/A'), # Original cased word
                "is_favorite": word_data.get('is_favorite', False),
                "last_explored_at": word_data.get('last_explored_at_iso'), # Use ISO string
                "first_explanation_cache": word_data.get('first_explanation_cache', ''),
                "modes_generated": word_data.get('modes_generated', [])
            }
            explored_words_list.append(display_word)
            if display_word["is_favorite"]:
                favorite_words_list.append(display_word) # Favorites are already sorted by last_explored_at
        
        return jsonify({
            "username": request.current_user_jwt.get('username'), # Include username for display
            "tier": request.current_user_jwt.get('tier'),       # Include tier
            "explored_words_count": len(explored_words_list),
            "explored_words_list": explored_words_list,
            "favorite_words_list": favorite_words_list
        }), 200
        
    except Exception as e:
        print(f"Error fetching profile data for user '{user_id}': {e}")
        return jsonify({"error": f"Failed to fetch profile data: {str(e)}"}), 500

if __name__ == '__main__':
    # For Render, PORT is set by the environment. For local, defaults to 5000.
    # debug=True is fine for local, Render might override or manage this.
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=os.environ.get('FLASK_DEBUG', '1') == '1')
