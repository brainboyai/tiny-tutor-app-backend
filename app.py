# app.py
from flask import Flask, request, jsonify # Removed 'session'
from flask_cors import CORS
import os
import re
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
import json
import base64
import requests
import jwt # Import PyJWT
from datetime import datetime, timedelta # For token expiry

    # Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

    # Configure CORS to allow requests ONLY from your Render frontend URL and local development
CORS(app, resources={r"/*": {"origins": [
        "https://tiny-tutor-app-frontend.onrender.com",  # Your frontend on Render
        "http://localhost:5173"                          # Your local development frontend
    ]}}, supports_credentials=True) # supports_credentials can be removed if not using cookies at all, but keep for now just in case of other needs.

    # JWT Configuration
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'super-secret-jwt-key') # IMPORTANT: Use a very strong, random key
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24) # Token expiry time

    # --- Firebase Initialization ---
service_account_key_base64 = os.getenv('FIREBASE_SERVICE_ACCOUNT_KEY_BASE64')

if service_account_key_base64:
        try:
            decoded_key = base64.b64decode(service_account_key_base64).decode('utf-8')
            cred = credentials.Certificate(json.loads(decoded_key))
        except Exception as e:
            print(f"ERROR: Failed to decode or parse FIREBASE_SERVICE_ACCOUNT_KEY_BASE64: {e}")
            exit(1)
else:
        try:
            cred = credentials.Certificate("firebase-service-account.json")
        except FileNotFoundError:
            print("ERROR: firebase-service-account.json not found. Please ensure it's in the backend directory or set FIREBASE_SERVICE_ACCOUNT_KEY_BASE64 env var for deployment.")
            exit(1)

firebase_admin.initialize_app(cred)
db = firestore.client() # Get a Firestore client

    # --- Gemini API Configuration ---
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
        print("WARNING: GEMINI_API_KEY environment variable not set. AI explanation feature will not work.")

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

    # --- Utility Functions ---
def is_valid_email(email):
        """Validates an email address format."""
        return re.match(r"[^@]+@[^@]+\.[^@]+", email)

def is_valid_password(password):
        """Validates password strength."""
        return len(password) >= 6 # Minimum 6 characters

def create_jwt_token(username, tier):
        """Creates a JWT token."""
        payload = {
            'username': username,
            'tier': tier,
            'exp': datetime.utcnow() + app.config['JWT_ACCESS_TOKEN_EXPIRES'] # Token expiry
        }
        return jwt.encode(payload, app.config['JWT_SECRET_KEY'], algorithm='HS256')

def decode_jwt_token(token):
        """Decodes and validates a JWT token."""
        try:
            payload = jwt.decode(token, app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
            return payload
        except jwt.ExpiredSignatureError:
            return {'error': 'Token has expired'}
        except jwt.InvalidTokenError:
            return {'error': 'Invalid token'}

    # Decorator for protecting routes with JWT
def jwt_required(f):
        from functools import wraps
        @wraps(f)
        def decorated_function(*args, **kwargs):
            auth_header = request.headers.get('Authorization')
            if not auth_header:
                print("JWT_REQUIRED: Authorization header missing.")
                return jsonify({"error": "Authorization token is missing"}), 401

            try:
                token = auth_header.split(" ")[1] # Expects "Bearer <token>"
                payload = decode_jwt_token(token)
                if 'error' in payload:
                    print(f"JWT_REQUIRED: Token error: {payload['error']}")
                    return jsonify({"error": payload['error']}), 401
                
                request.user = payload # Attach user info to request object
            except IndexError:
                print("JWT_REQUIRED: Token format invalid (not 'Bearer <token>').")
                return jsonify({"error": "Token format is 'Bearer <token>'"}), 401
            except Exception as e:
                print(f"JWT_REQUIRED: Unexpected error decoding token: {e}")
                return jsonify({"error": "Invalid token"}), 401
            return f(*args, **kwargs)
        return decorated_function


    # --- Routes ---

@app.route('/signup', methods=['POST'])
def signup():
        data = request.get_json()
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')

        if not username or not email or not password:
            return jsonify({"error": "Missing username, email, or password"}), 400

        if not is_valid_email(email):
            return jsonify({"error": "Invalid email format"}), 400

        if not is_valid_password(password):
            return jsonify({"error": "Password must be at least 6 characters long"}), 400

        users_ref = db.collection('users')

        # Check if username already exists
        if users_ref.document(username).get().exists:
            return jsonify({"error": "Username already exists"}), 409

        # Check if email already exists (query across documents)
        if users_ref.where('email', '==', email).get():
            return jsonify({"error": "Email already registered"}), 409

        try:
            users_ref.document(username).set({
                "email": email,
                "password": password, # In a real app, hash the password (e.g., using bcrypt)
                "tier": "free"
            })
            print(f"User {username} signed up and stored in Firestore.")
            return jsonify({"message": "User registered successfully"}), 201
        except Exception as e:
            print(f"Error during signup: {e}")
            return jsonify({"error": "Failed to register user"}), 500

@app.route('/login', methods=['POST'])
def login():
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')

        if not username or not password:
            return jsonify({"error": "Missing username or password"}), 400

        user_doc = db.collection('users').document(username).get()

        if user_doc.exists:
            user_data = user_doc.to_dict()
            if user_data['password'] == password: # In real app, compare hashed passwords
                tier = user_data.get('tier', 'free')
                access_token = create_jwt_token(username, tier) # Generate JWT
                print(f"User {username} logged in. JWT generated.")
                return jsonify({
                    "message": "Login successful",
                    "username": username,
                    "tier": tier,
                    "access_token": access_token # Send token to frontend
                }), 200
            else:
                return jsonify({"error": "Invalid username or password"}), 401
        else:
            return jsonify({"error": "Invalid username or password"}), 401

@app.route('/logout', methods=['POST'])
@jwt_required # Protect logout with JWT, though it's optional for a simple logout
def logout():
        # With JWTs, logout is purely a client-side action (deleting the token)
        # This endpoint can be used to invalidate tokens on a blacklist if needed,
        # but for simple cases, it's just a formality.
        print(f"User {request.user['username']} effectively logged out (token deleted client-side).")
        return jsonify({"message": "Logged out successfully"}), 200

@app.route('/status', methods=['GET'])
@jwt_required # Protect status check
def status():
        # If jwt_required passed, request.user contains the decoded token payload
        print(f"Status check: User {request.user['username']} is logged in with tier {request.user['tier']}.")
        return jsonify({"logged_in": True, "username": request.user['username'], "tier": request.user['tier']}), 200

@app.route('/check_session', methods=['GET'])
@jwt_required # Protect this debugging endpoint
def check_session():
        print(f"Backend /check_session: User {request.user['username']} is in session.")
        return jsonify({"logged_in": True, "username": request.user['username'], "tier": request.user['tier']}), 200

@app.route('/protected', methods=['GET'])
@jwt_required # Apply JWT protection
def protected():
        return jsonify({"message": f"Welcome, {request.user['username']}! This is a protected resource for {request.user['tier']} users."}), 200

@app.route('/generate_explanation', methods=['POST'])
@jwt_required # Apply JWT protection
def generate_explanation():
        # With jwt_required, we are guaranteed a valid user in request.user
        username = request.user['username']
        tier = request.user['tier']
        print(f"Backend /generate_explanation: User {username} ({tier}) is authorized via JWT.")

        data = request.get_json()
        question = data.get('question')

        if not question:
            return jsonify({"error": "No question provided"}), 400

        if not GEMINI_API_KEY:
            return jsonify({"error": "AI service not configured. Missing API Key."}), 500

        try:
            headers = {
                'Content-Type': 'application/json',
            }
            params = {
                'key': GEMINI_API_KEY
            }
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {"text": f"Provide a simple, 3-sentence explanation of the concept '{question}'. Ensure the explanation includes key terms and clearly defines the concept for a student."}
                        ]
                    }
                ]
            }

            response = requests.post(GEMINI_API_URL, headers=headers, params=params, json=payload)
            response.raise_for_status()

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
    