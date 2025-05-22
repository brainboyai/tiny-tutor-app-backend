    # app.py
from flask import Flask, request, jsonify, session
from flask_cors import CORS
import os
import re
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
import json
import base64 # <--- NEW: Import base64 module

    # Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

    # Configure CORS to allow requests from your frontend's Render URL
CORS(app, resources={r"/*": {"origins": [
        "https://tiny-tutor-app-frontend.onrender.com",
        "http://localhost:5173"
    ]}}, supports_credentials=True)

    # In a real application, use a strong, randomly generated secret key
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'default_secret_key_for_dev')

    # --- Firebase Initialization ---
    # Render will provide FIREBASE_SERVICE_ACCOUNT_KEY_BASE64 as an environment variable.
    # Locally, it will fall back to reading the JSON file.
service_account_key_base64 = os.getenv('FIREBASE_SERVICE_ACCOUNT_KEY_BASE64') # <--- NEW: Changed env var name

if service_account_key_base64:
        # <--- NEW LOGIC: Decode the Base64 string and then load as JSON
        try:
            decoded_key = base64.b64decode(service_account_key_base64).decode('utf-8')
            cred = credentials.Certificate(json.loads(decoded_key))
        except Exception as e:
            print(f"ERROR: Failed to decode or parse FIREBASE_SERVICE_ACCOUNT_KEY_BASE64: {e}")
            exit(1) # Exit if environment variable is malformed
else:
        # <--- LOCAL DEVELOPMENT LOGIC: If env var not set, load from local JSON file
        try:
            cred = credentials.Certificate("firebase-service-account.json")
        except FileNotFoundError:
            print("ERROR: firebase-service-account.json not found. Please ensure it's in the backend directory or set FIREBASE_SERVICE_ACCOUNT_KEY_BASE64 env var for deployment.")
            exit(1) # Exit if key file is not found locally

firebase_admin.initialize_app(cred)
db = firestore.client() # Get a Firestore client

    # --- Utility Functions ---
def is_valid_email(email):
        """Validates an email address format."""
        return re.match(r"[^@]+@[^@]+\.[^@]+", email)

def is_valid_password(password):
        """Validates password strength."""
        return len(password) >= 6 # Minimum 6 characters

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
        # Note: Firestore queries on non-indexed fields can be slow or require index creation.
        # For 'email', you might need to create a composite index in Firebase Console if this query becomes complex.
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
                session['username'] = username
                session['tier'] = user_data.get('tier', 'free')
                print(f"User {username} logged in from Firestore. Session: {session}")
                return jsonify({"message": "Login successful", "username": username, "tier": session['tier']}), 200
            else:
                return jsonify({"error": "Invalid username or password"}), 401
        else:
            return jsonify({"error": "Invalid username or password"}), 401

@app.route('/logout', methods=['POST'])
def logout():
        session.pop('username', None)
        session.pop('tier', None)
        print("User logged out. Session cleared.")
        return jsonify({"message": "Logged out successfully"}), 200

@app.route('/status', methods=['GET'])
def status():
        if 'username' in session:
            print(f"Status check: User {session['username']} is logged in with tier {session.get('tier')}.")
            return jsonify({"logged_in": True, "username": session['username'], "tier": session.get('tier', 'free')}), 200
        else:
            print("Status check: User is not logged in.")
            return jsonify({"logged_in": False}), 200

@app.route('/protected', methods=['GET'])
def protected():
        if 'username' in session:
            return jsonify({"message": f"Welcome, {session['username']}! This is a protected resource for {session.get('tier')} users."}), 200
        else:
            return jsonify({"error": "Unauthorized"}), 401

if __name__ == '__main__':
        app.run(debug=True, port=5000)
    