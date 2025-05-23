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

db = None
if service_account_key_base64:
        try:
            decoded_key = base64.b64decode(service_account_key_base64).decode('utf-8')
            cred = credentials.Certificate(json.loads(decoded_key))
            if not firebase_admin._apps: # Initialize only if no app is already initialized
                firebase_admin.initialize_app(cred)
            db = firestore.client()
            print("Firebase initialized successfully.")
        except Exception as e:
            print(f"Error initializing Firebase: {e}")
else:
        print("FIREBASE_SERVICE_ACCOUNT_KEY_BASE64 environment variable not set. Firebase will not be initialized.")

    # Decorator for JWT authentication
def jwt_required(f):
        def decorated_function(*args, **kwargs):
            token = None
            # JWT is typically sent in the Authorization header as a Bearer token
            if 'Authorization' in request.headers:
                auth_header = request.headers['Authorization']
                try:
                    token = auth_header.split(" ")[1]
                except IndexError:
                    return jsonify({"error": "Token format is 'Bearer <token>'"}), 403

            if not token:
                print("Authentication token is missing!")
                return jsonify({"error": "Authentication token is missing!"}), 401

            try:
                # Decode the token using the secret key
                data = jwt.decode(token, app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
                request.user = data # Attach user payload to request object
            except jwt.ExpiredSignatureError:
                print("Token has expired!")
                return jsonify({"error": "Token has expired!"}), 401
            except jwt.InvalidTokenError:
                print("Invalid token!")
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

        if not username or not email or not password:
            return jsonify({"error": "Missing username, email, or password"}), 400

        # Basic validation
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            return jsonify({"error": "Invalid email format"}), 400
        if len(password) < 6:
            return jsonify({"error": "Password must be at least 6 characters long"}), 400

        if db is None:
            return jsonify({"error": "Database not initialized. Please check backend configuration."}), 500

        users_ref = db.collection('users')

        # Check if username or email already exists
        if users_ref.where('username', '==', username).limit(1).get():
            return jsonify({"error": "Username already exists"}), 409
        if users_ref.where('email', '==', email).limit(1).get():
            return jsonify({"error": "Email already exists"}), 409

        try:
            users_ref.add({
                'username': username,
                'email': email,
                'password': password, # Storing plain text password for now, consider hashing in production
                'tier': 'basic', # Default tier
                'created_at': firestore.SERVER_TIMESTAMP
            })
            print(f"User '{username}' signed up successfully.")
            return jsonify({"message": "User registered successfully"}), 201
        except Exception as e:
            print(f"Error during signup for user '{username}': {e}")
            return jsonify({"error": "Failed to register user"}), 500


@app.route('/login', methods=['POST'])
def login():
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')

        if not username or not password:
            return jsonify({"error": "Missing username or password"}), 400

        if db is None:
            return jsonify({"error": "Database not initialized. Please check backend configuration."}), 500

        users_ref = db.collection('users')
        query = users_ref.where('username', '==', username).limit(1).get()

        if not query:
            print(f"Login failed: Username '{username}' not found.")
            return jsonify({"error": "Invalid username or password"}), 401

        user_doc = query[0]
        user_data = user_doc.to_dict()

        if user_data and user_data['password'] == password: # Plain text password comparison
            access_token = jwt.encode({
                'username': user_data['username'],
                'tier': user_data.get('tier', 'basic'),
                'exp': datetime.utcnow() + app.config['JWT_ACCESS_TOKEN_EXPIRES']
            }, app.config['JWT_SECRET_KEY'], algorithm='HS256')
            print(f"User '{username}' logged in successfully.")
            return jsonify(access_token=access_token), 200
        else:
            print(f"Login failed: Incorrect password for user '{username}'.")
            return jsonify({"error": "Invalid username or password"}), 401

@app.route('/logout', methods=['POST'])
@jwt_required
def logout():
        # For JWT, logout is usually handled client-side by deleting the token.
        # This endpoint can be used for server-side cleanup if needed, but for now, it's mostly a placeholder.
        return jsonify({"message": "Logged out successfully"}), 200


@app.route('/generate_explanation', methods=['POST'])
@jwt_required # Protect this route with JWT
def generate_explanation():
        data = request.get_json()
        question = data.get('question')
        content_type = data.get('content_type', 'explain') # Default to 'explain'

        if not question:
            return jsonify({"error": "Missing question"}), 400

        user_tier = request.user.get('tier', 'basic') # Access user data from the request object

        GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
        GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent"

        if not GEMINI_API_KEY:
            print("GEMINI_API_KEY is not set.")
            return jsonify({"error": "Server configuration error: Gemini API key is missing."}), 500

        prompt_prefix = {
            'explain': "Provide a concise, easy-to-understand explanation for the concept '{question}'.",
            'fact': "Give me one interesting fact about '{question}'.",
            'quiz': "Generate a simple multiple-choice quiz question about '{question}' with 4 options and identify the correct answer.",
            'deep': "Provide a detailed, in-depth explanation of '{question}', including its background, key aspects, and significance.",
            'image': "Describe an image that could represent '{question}'. (Note: Image generation is a future feature, this is just a textual description for now.)"
        }

        if content_type not in prompt_prefix:
            return jsonify({"error": "Invalid content type requested."}), 400

        # Apply tier-based limits (example: 'premium' tier gets more detailed explanations)
        if user_tier == 'premium' and content_type == 'explain':
            prompt_template = "Provide a comprehensive, detailed, and easy-to-understand explanation for the concept '{question}'. Include analogies if helpful."
        else:
            prompt_template = prompt_prefix.get(content_type, prompt_prefix['explain']) # Fallback to explain if type is invalid or not in dict


        prompt = prompt_template.format(question=question)

        headers = {
            "Content-Type": "application/json"
        }
        params = {
            "key": GEMINI_API_KEY
        }

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ]
        }

        try:
            response = requests.post(GEMINI_API_URL, headers=headers, params=params, json=payload)
            response.raise_for_status() # Raises HTTPError for bad responses (4xx or 5xx)

            gemini_result = response.json()

            if gemini_result and 'candidates' in gemini_result and len(gemini_result['candidates']) > 0:
                explanation = gemini_result['candidates'][0]['content']['parts'][0]['text']
                return jsonify({"explanation": explanation}), 200
            else:
                print(f"Gemini API returned no candidates or unexpected structure: {gemini_result}")
                return jsonify({"error": "Failed to generate explanation. Please try again."}), 500

        except requests.exceptions.RequestException as e:
            print(f"Error calling Gemini API: {e}")
            return jsonify({"error": f"Failed to connect to AI service: {e}"}), 500
        except Exception as e:
            print(f"An unexpected error occurred during explanation generation: {e}")
            return jsonify({"error": "An unexpected error occurred."}), 500


if __name__ == '__main__':
        # When running locally, set JWT_SECRET_KEY in your .env file
        # For Render, set it as an environment variable in your service settings
        app.run(debug=True, port=5000)
