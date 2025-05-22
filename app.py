# app.py
from flask import Flask, request, jsonify, session
from flask_cors import CORS
import os
import re
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# Configure CORS to allow requests from your frontend's Render URL
# Replace 'https://tiny-tutor-app-frontend.onrender.com' with your actual frontend URL if it changes.
# We also allow your local development server (http://localhost:5173) for testing.
CORS(app, resources={r"/*": {"origins": [
"https://tiny-tutor-app-frontend.onrender.com",
"http://localhost:5173"
]}}, supports_credentials=True) # Enable CORS with credentials support

# In a real application, use a strong, randomly generated secret key
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'default_secret_key_for_dev')

# In-memory user store (for demonstration purposes)
# In a real application, you would use a database (e.g., PostgreSQL, MongoDB)
users = {} # {username: {email: "email", password: "hashed_password", tier: "free"}}

# --- Utility Functions ---
def is_valid_email(email):
"""Validates an email address format."""
# A simple regex for email validation
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

if username in users:
return jsonify({"error": "Username already exists"}), 409 # Conflict
if any(user_data['email'] == email for user_data in users.values()):
return jsonify({"error": "Email already registered"}), 409 # Conflict

# In a real app, hash the password before storing (e.g., using bcrypt)
users[username] = {"email": email, "password": password, "tier": "free"}
print(f"User {username} signed up. Current users: {users}") # Debug print
return jsonify({"message": "User registered successfully"}), 201 # Created

@app.route('/login', methods=['POST'])
def login():
data = request.get_json()
username = data.get('username')
password = data.get('password')

if not username or not password:
return jsonify({"error": "Missing username or password"}), 400

user = users.get(username)
if user and user['password'] == password: # In real app, compare hashed passwords
session['username'] = username
session['tier'] = user['tier'] # Store tier in session
print(f"User {username} logged in. Session: {session}") # Debug print
return jsonify({"message": "Login successful", "username": username, "tier": user['tier']}), 200
else:
return jsonify({"error": "Invalid username or password"}), 401 # Unauthorized

@app.route('/logout', methods=['POST'])
def logout():
session.pop('username', None)
session.pop('tier', None)
print("User logged out. Session cleared.") # Debug print
return jsonify({"message": "Logged out successfully"}), 200

@app.route('/status', methods=['GET'])
def status():
if 'username' in session:
print(f"Status check: User {session['username']} is logged in with tier {session.get('tier')}.") # Debug print
return jsonify({"logged_in": True, "username": session['username'], "tier": session.get('tier', 'free')}), 200
else:
print("Status check: User is not logged in.") # Debug print
return jsonify({"logged_in": False}), 200

@app.route('/protected', methods=['GET'])
def protected():
if 'username' in session:
return jsonify({"message": f"Welcome, {session['username']}! This is a protected resource for {session.get('tier')} users."}), 200
else:
return jsonify({"error": "Unauthorized"}), 401

if __name__ == '__main__':
# In a production environment, you would typically use a production-ready WSGI server
# like Gunicorn or uWSGI, and not run app.run() directly.
# For local development:
app.run(debug=True, port=5000)
