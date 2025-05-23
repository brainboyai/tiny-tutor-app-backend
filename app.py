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
from datetime import datetime, timedelta
from functools import wraps # Import wraps for decorator

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# Configure CORS to allow requests ONLY from your Render frontend URL and local development
CORS(app, resources={r"/*": {"origins": [
    "https://tiny-tutor-app-frontend.onrender.com",  # Your frontend on Render
    "http://localhost:5173"                          # Your local development frontend
]}}, supports_credentials=True)

# JWT Configuration
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'super-secret-jwt-key') # IMPORTANT: Use a very strong, random key
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24) # Token expiry time

# --- Firebase Initialization ---
service_account_key_base64 = os.getenv('FIREBASE_SERVICE_ACCOUNT_KEY_BASE64')

if service_account_key_base64:
    try:
        decoded_key = base64.b64decode(service_account_key_base64).decode('utf-8')
        cred = credentials.Certificate(json.loads(decoded_key))
        if not firebase_admin._apps: # Initialize only if not already initialized
            firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("Firebase initialized successfully.")
    except Exception as e:
        print(f"Error initializing Firebase: {e}")
        db = None
else:
    print("FIREBASE_SERVICE_ACCOUNT_KEY_BASE64 environment variable not set. Firebase not initialized.")
    db = None

# Gemini API Configuration
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent"

# --- JWT Authentication Decorator ---
def jwt_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            if auth_header.startswith('Bearer '):
                token = auth_header.split(' ')[1]

        if not token:
            return jsonify({"error": "Authentication token is missing!"}), 401
        try:
            # Decode the token using your secret key
            data = jwt.decode(token, app.config['JWT_SECRET_KEY'], algorithms=["HS256"])
            # You can add more validation here if needed, e.g., check user existence in DB
            request.user = data # Attach user payload to request
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token has expired!"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Token is invalid!"}), 401
        return f(*args, **kwargs)
    return decorated_function

# --- Routes ---

@app.route('/')
def home():
    return "Tiny Tutor Backend is running!"

@app.route('/signup', methods=['POST'])
def signup():
    if not db:
        return jsonify({"error": "Firebase not initialized. Cannot sign up."}), 500

    data = request.get_json()
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')

    if not all([username, email, password]):
        return jsonify({"error": "Missing username, email, or password"}), 400

    # Basic validation for email format
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return jsonify({"error": "Invalid email format"}), 400

    # Check if username or email already exists
    users_ref = db.collection('users')
    existing_username = users_ref.where('username', '==', username).limit(1).get()
    existing_email = users_ref.where('email', '==', email).limit(1).get()

    if len(existing_username) > 0:
        return jsonify({"error": "Username already exists"}), 409
    if len(existing_email) > 0:
        return jsonify({"error": "Email already registered"}), 409

    try:
        # In a real app, hash the password before storing!
        # For simplicity in this tutorial, we store it plain. DO NOT DO THIS IN PRODUCTION.
        users_ref.add({
            'username': username,
            'email': email,
            'password': password, # In production, hash this password!
            'tier': 'free', # Default tier
            'created_at': firestore.SERVER_TIMESTAMP
        })
        return jsonify({"message": "User registered successfully"}), 201
    except Exception as e:
        print(f"Error during signup: {e}")
        return jsonify({"error": "Internal server error during registration"}), 500

@app.route('/login', methods=['POST'])
def login():
    if not db:
        return jsonify({"error": "Firebase not initialized. Cannot log in."}), 500

    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not all([username, password]):
        return jsonify({"error": "Missing username or password"}), 400

    users_ref = db.collection('users')
    query = users_ref.where('username', '==', username).limit(1).get()

    if not query:
        return jsonify({"error": "Invalid username or password"}), 401

    user_doc = query[0]
    user_data = user_doc.to_dict()

    if user_data and user_data['password'] == password: # In production, verify hashed password
        # Generate JWT
        expires_delta = app.config['JWT_ACCESS_TOKEN_EXPIRES']
        expires = datetime.now(tz=None) + expires_delta
        # The payload should contain minimal, non-sensitive user info
        identity = {
            'username': user_data['username'],
            'tier': user_data['tier'],
            'exp': expires.timestamp() # Expiration timestamp
        }
        access_token = jwt.encode(identity, app.config['JWT_SECRET_KEY'], algorithm="HS256")

        return jsonify({
            "message": "Login successful",
            "access_token": access_token
        }), 200
    else:
        return jsonify({"error": "Invalid username or password"}), 401

@app.route('/logout', methods=['POST'])
@jwt_required # Protect logout if it needs server-side processing (e.g., token invalidation)
def logout():
    # For JWT, logout is primarily client-side token removal.
    # This endpoint can be used for server-side logging or invalidation if implemented.
    return jsonify({"message": "Logged out successfully"}), 200

# NEW: Modified generate_explanation endpoint to handle different content types
@app.route('/generate_explanation', methods=['POST'])
@jwt_required # Ensure this route is protected by JWT
def generate_explanation():
    try:
        data = request.get_json()
        question = data.get('question')
        # Get the content_type from the request, default to 'explain'
        content_type = data.get('content_type', 'explain')

        if not question:
            return jsonify({"error": "Question is required"}), 400

        # Define prompts based on content_type
        # You can adjust these prompts to get the desired AI output
        prompts = {
            'explain': f"Provide a concise and easy-to-understand explanation of the concept '{question}'. Ensure the explanation includes key terms and clearly defines the concept for a student. Keep it around 3-5 paragraphs.",
            'fact': f"Provide 3-5 interesting and lesser-known facts about '{question}'. Each fact should be a concise sentence or two.",
            'quiz': f"Generate a a single multiple-choice quiz question about '{question}' with 4 options (A, B, C, D) and specify the correct answer. Format the output clearly like this:\n\nQuestion: [Your question here]\nA) [Option A]\nB) [Option B]\nC) [Option C]\nD) [Option D]\nCorrect Answer: [A, B, C, or D]",
            'deep': f"Provide a detailed, in-depth explanation of '{question}', including its advanced concepts, historical context, and potential future implications. Aim for a comprehensive academic-level overview, around 5-8 paragraphs.",
            'image': "This feature will generate an image soon. For now, imagine a visual representation of the concept.", # Placeholder for image
        }

        prompt_text = prompts.get(content_type)
        if not prompt_text:
            return jsonify({"error": "Invalid content type specified"}), 400

        # For 'image' type, we just return the placeholder directly without calling Gemini
        if content_type == 'image':
            return jsonify({"explanation": prompt_text}), 200

        # Gemini API call for other types
        headers = {
            "Content-Type": "application/json",
        }
        params = {
            "key": os.getenv("GEMINI_API_KEY")
        }
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt_text}
                    ]
                }
            ]
        }

        response = requests.post(GEMINI_API_URL, headers=headers, params=params, json=payload)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

        gemini_result = response.json()

        if gemini_result and 'candidates' in gemini_result and len(gemini_result['candidates']) > 0:
            explanation = gemini_result['candidates'][0]['content']['parts'][0]['text']
            return jsonify({"explanation": explanation}), 200
        else:
            print(f"Gemini API returned no candidates or unexpected structure for {content_type}: {gemini_result}")
            return jsonify({"error": f"Failed to generate {content_type}. Please try again."}), 500

    except requests.exceptions.RequestException as e:
        print(f"Error calling Gemini API for {content_type}: {e}")
        return jsonify({"error": f"Failed to connect to AI service for {content_type}: {e}"}), 500
    except Exception as e:
        print(f"An unexpected error occurred during {content_type} generation: {e}")
        return jsonify({"error": "An unexpected error occurred."}), 500


if __name__ == '__main__':
    # When running locally, set JWT_SECRET_KEY and GEMINI_API_KEY in your .env file
    # For Render, set them as environment variables in your service settings
    app.run(debug=True, port=5000)
