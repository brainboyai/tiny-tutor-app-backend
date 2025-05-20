# app.py
from flask import Flask, request, jsonify, session
from flask_cors import CORS
import os
import uuid # For generating user IDs if not using a database
# For LLM integration (Gemini API)
import google.generativeai as genai

# Initialize Flask app
app = Flask(__name__)

# Configure CORS to allow requests from your frontend URL
# Replace 'YOUR_FRONTEND_URL' with the actual URL of your Render frontend service
# Example: CORS(app, resources={r"/*": {"origins": "https://tiny-tutor-frontend-brainboyai.onrender.com"}}, supports_credentials=True)
CORS(app, resources={r"/*": {"origins": "YOUR_FRONTEND_URL"}}, supports_credentials=True)

# Secret key for session management (IMPORTANT: Use a strong, random key in production)
# For Render, you would typically set this as an environment variable.
# For now, we'll use a placeholder.
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'a_very_secret_and_random_key_for_dev')

# In a real application, you would use a database (e.g., Firestore, PostgreSQL)
# to store user data. For this example, we'll use a simple in-memory dictionary.
# DO NOT use this in a production environment.
users_db = {} # Stores: {username: {password: "...", email: "...", tier: "free"}}

# Configure Gemini API (free tier)
# IMPORTANT: Replace 'YOUR_GEMINI_API_KEY' with your actual Gemini API Key.
# For Render, you would set this as an environment variable.
# Example: genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))
genai.configure(api_key=os.environ.get('GEMINI_API_KEY', 'YOUR_GEMINI_API_KEY'))

# Initialize the Gemini Pro model
# This uses the default gemini-pro model available in the free tier
model = genai.GenerativeModel('gemini-pro')

# In-memory chat history for LLM (for demonstration purposes)
# In a real app, this would be stored per-user, possibly in a database or session.
chat_history = {} # Stores: {session_id: [{role: "user", parts: [{text: "..."}]}, {role: "model", parts: [{text: "..."}]}]}

@app.route('/')
def home():
    """Basic home route for the backend."""
    return "Tiny Tutor Backend is running!"

@app.route('/signup', methods=['POST'])
def signup():
    """Handles user registration."""
    data = request.get_json()
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')

    if not username or not email or not password:
        return jsonify({"error": "Missing username, email, or password"}), 400

    if username in users_db:
        return jsonify({"error": "Username already exists"}), 409

    # In a real app, hash the password before storing!
    users_db[username] = {"password": password, "email": email, "tier": "free"}
    print(f"User {username} signed up. Total users: {len(users_db)}")
    return jsonify({"message": "User registered successfully"}), 201

@app.route('/login', methods=['POST'])
def login():
    """Handles user login."""
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({"error": "Missing username or password"}), 400

    user = users_db.get(username)
    if user and user["password"] == password: # In real app: check hashed password
        session['logged_in'] = True
        session['username'] = username
        session['tier'] = user["tier"]
        # Generate a unique session ID for chat history
        if 'session_id' not in session:
            session['session_id'] = str(uuid.uuid4())
        print(f"User {username} logged in.")
        return jsonify({"message": "Login successful", "username": username, "tier": user["tier"]}), 200
    else:
        return jsonify({"error": "Invalid username or password"}), 401

@app.route('/logout', methods=['POST'])
def logout():
    """Handles user logout."""
    session.pop('logged_in', None)
    session.pop('username', None)
    session.pop('tier', None)
    session.pop('session_id', None) # Clear chat session ID
    print("User logged out.")
    return jsonify({"message": "Logged out successfully"}), 200

@app.route('/status', methods=['GET'])
def status():
    """Checks if a user is logged in."""
    if session.get('logged_in'):
        return jsonify({"logged_in": True, "username": session.get('username'), "tier": session.get('tier')}), 200
    return jsonify({"logged_in": False}), 200

@app.route('/llm_chat', methods=['POST'])
def llm_chat():
    """Handles LLM chat interactions."""
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401

    user_message = request.get_json().get('message')
    if not user_message:
        return jsonify({"error": "Missing message"}), 400

    session_id = session.get('session_id')
    if not session_id:
        session_id = str(uuid.uuid4())
        session['session_id'] = session_id

    # Get or initialize chat history for this session
    current_chat_history = chat_history.get(session_id, [])

    try:
        # Start a new chat session with the model using the current history
        convo = model.start_chat(history=current_chat_history)
        convo.send_message(user_message)
        llm_response = convo.last.text

        # Update chat history (in-memory for this example)
        chat_history[session_id] = convo.history

        return jsonify({"response": llm_response}), 200
    except Exception as e:
        print(f"Error during LLM chat: {e}")
        return jsonify({"error": f"LLM interaction failed: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
