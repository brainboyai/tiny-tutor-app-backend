import base64
import json
import os
import re
from datetime import datetime, timedelta, timezone
from functools import wraps

import firebase_admin
import google.generativeai as genai
import jwt
from dotenv import load_dotenv
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from flask import Flask, jsonify, request, current_app
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash
from google.generativeai.types import HarmCategory, HarmBlockThreshold

load_dotenv()
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": ["https://tiny-tutor-app-frontend.onrender.com", "http://localhost:5173", "http://127.0.0.1:5173"]}}, supports_credentials=True, expose_headers=["Content-Type", "Authorization"], allow_headers=["Content-Type", "Authorization", "X-Requested-With"])
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'fallback_secret_key_for_dev_only_change_me')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)
service_account_key_base64 = os.getenv('FIREBASE_SERVICE_ACCOUNT_KEY_BASE64')
db = None
if service_account_key_base64:
    try:
        decoded_key_bytes = base64.b64decode(service_account_key_base64)
        decoded_key_str = decoded_key_bytes.decode('utf-8')
        service_account_info = json.loads(decoded_key_str)
        if not firebase_admin._apps:
            cred = credentials.Certificate(service_account_info)
            firebase_admin.initialize_app(cred)
            app.logger.info("Firebase Admin SDK initialized successfully from Base64.")
        else:
            app.logger.info("Firebase Admin SDK already initialized.")
        db = firestore.client()
    except Exception as e:
        app.logger.error(f"Failed to initialize Firebase Admin SDK from Base64: {e}")
        db = None
else:
    app.logger.warning("FIREBASE_SERVICE_ACCOUNT_KEY_BASE64 not found. Firebase Admin SDK not initialized.")

gemini_api_key = os.getenv('GEMINI_API_KEY')
if gemini_api_key:
    try:
        genai.configure(api_key=gemini_api_key)
        app.logger.info("Google Gemini API configured successfully.")
    except Exception as e:
        app.logger.error(f"Failed to configure Google Gemini API: {e}")
else:
    app.logger.warning("GEMINI_API_KEY not found. Google Gemini API not configured.")

limiter = Limiter(get_remote_address, app=app, default_limits=["200 per day", "60 per hour"], storage_uri="memory://")

def sanitize_word_for_id(word: str) -> str:
    if not isinstance(word, str): return "invalid_input"
    sanitized = word.lower()
    sanitized = re.sub(r'\s+', '_', sanitized)
    sanitized = re.sub(r'[^a-z0-9_]', '', sanitized)
    return sanitized if sanitized else "empty_word"

def token_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.method == 'OPTIONS':
            return current_app.make_default_options_response()
        token = None
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            try: token = auth_header.split(" ")[1]
            except IndexError: return jsonify({"error": "Bearer token malformed"}), 401
        if not token: return jsonify({"error": "Token is missing"}), 401
        try:
            payload = jwt.decode(token, app.config['JWT_SECRET_KEY'], algorithms=['HS256'], leeway=timedelta(seconds=30))
            current_user_id = payload['user_id']
        except Exception: return jsonify({"error": "Token is invalid"}), 401
        return f(current_user_id, *args, **kwargs)
    return decorated_function

@app.route('/generate_story_node', methods=['POST', 'OPTIONS'])
@token_required
@limiter.limit("200/hour")
def generate_story_node_route(current_user_id):
    if not gemini_api_key: return jsonify({"error": "AI service not configured"}), 500
    data = request.get_json()
    if not data: return jsonify({"error": "No input data provided"}), 400

    topic = data.get('topic', '').strip()
    history = data.get('history', [])
    last_choice_leads_to = data.get('leads_to')

    if not topic: return jsonify({"error": "Topic is required"}), 400

    base_prompt = """
You are 'Tiny Tutor,' an expert AI educator creating an interactive, conversational learning game. Your task is to generate the next single turn in the conversation, following these core principles inspired by expert teaching methods.

**Core Instructional Principles:**
1.  **Follow the Screenplay Flow:** The conversation must follow a **Feedback -> Explain -> Transition -> Question** pattern. Do not merge these steps.
2.  **Feedback First:** The `feedback_on_previous_answer` field is for direct, evaluative feedback (e.g., "Correct!", "Not quite..."). This field MUST BE an empty string if it's the first turn or if the previous turn was a simple transition (like clicking "Continue").
3.  **Explain a Single Concept:** After feedback, the `dialogue` should explain ONE new concept concisely (2-3 sentences). This turn must end with a single, simple transition option like "Continue" or "Got it, what's next?".
4.  **Ask a Question on a New Turn:** After the user clicks a transition button, the next turn should be dedicated to asking a question about the concept you just explained. The `dialogue` will contain the question.
5.  **Contextual Integrity:** All questions and options must ONLY relate to information already provided in the conversation history or common-sense analogies.
6.  **Image for Every Step:** Every turn MUST have at least one `image_prompt`. For image-based questions, provide one distinct prompt for each clickable option. Ensure the number of image prompts matches the number of options.

**Your Input for This Turn:**
- Learning Topic/Concept: "{topic}"
- Target Audience/Grade Level: Grade 6 Science
- Tone: Exploratory and curious.
"""
    if not history:
        prompt = base_prompt.format(topic=topic) + """
- **Current Task:** Generate the VERY FIRST interaction cycle. Introduce the topic with a relatable, common-sense question. The `feedback_on_previous_answer` field MUST be an empty string.
"""
    else:
        prompt_history = "\\n".join([f"{item['type']}: {item['text']}" for item in history])
        prompt = base_prompt.format(topic=topic) + f"""
- **Conversation History So Far:**
{prompt_history}
- **Current Task:** The user chose an option that "Leads to: {last_choice_leads_to}". Generate the SINGLE, COMPLETE interaction cycle for this next step, strictly following all core instructional principles.
"""
    try:
        story_node_schema = {
            "type": "object",
            "properties": {
                "feedback_on_previous_answer": {"type": "string", "description": "Direct feedback on the user's last choice. Empty string for the first turn or after a 'continue' button."},
                "dialogue": {"type": "string", "description": "The AI teacher's main dialogue for this turn (either an explanation or a question)."},
                "image_prompts": {"type": "array", "items": {"type": "string"}, "description": "A list of prompts for images to display. For image questions, the order must match the options."},
                "interaction": { "type": "object", "properties": { "type": {"type": "string", "description": "e.g., 'Text-based Button Selection' or 'Image Selection'."},
                        "options": { "type": "array", "items": { "type": "object", "properties": {
                                        "text": {"type": "string"}, "leads_to": {"type": "string"}},
                                    "required": ["text", "leads_to"]}}}, "required": ["type", "options"]}},
            "required": ["feedback_on_previous_answer", "dialogue", "image_prompts", "interaction"]}

        gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')
        generation_config = genai.types.GenerationConfig(response_mime_type="application/json", response_schema=story_node_schema)
        safety_settings = {HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_ONLY_HIGH, HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_ONLY_HIGH, HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_ONLY_HIGH, HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_ONLY_HIGH}
        
        response = gemini_model.generate_content(prompt, generation_config=generation_config, safety_settings=safety_settings)
        parsed_node = json.loads(response.text)
        return jsonify(parsed_node), 200

    except Exception as e:
        app.logger.error(f"FATAL Error in /generate_story_node for user {current_user_id}, topic '{topic}': {e}")
        try:
            if response and response.prompt_feedback.block_reason:
                app.logger.error(f"AI response was blocked. Reason: {response.prompt_feedback.block_reason}")
                return jsonify({"error": "The learning topic was blocked for safety reasons. Please try a different topic."}), 400
        except Exception:
             pass
        return jsonify({"error": "The AI returned an unreadable story format. Please try again."}), 500

@app.route('/')
def home(): return "Tiny Tutor Backend is running!"
@app.route('/signup', methods=['POST'])
@limiter.limit("5 per hour")
def signup_user():
    if not db: return jsonify({"error": "Database not configured"}), 500
    data = request.get_json();
    if not data: return jsonify({"error": "No input data provided"}), 400
    username = data.get('username', '').strip(); email = data.get('email', '').strip().lower(); password = data.get('password', '')
    if not username or not email or not password: return jsonify({"error": "Username, email, and password are required"}), 400
    try:
        users_ref = db.collection('users')
        if len(list(users_ref.where('username_lowercase', '==', username.lower()).limit(1).stream())) > 0: return jsonify({"error": "Username already exists"}), 409
        if len(list(users_ref.where('email', '==', email).limit(1).stream())) > 0: return jsonify({"error": "Email already registered"}), 409
        user_doc_ref = users_ref.document()
        user_doc_ref.set({'username': username, 'username_lowercase': username.lower(), 'email': email, 'password_hash': generate_password_hash(password), 'tier': 'standard', 'created_at': firestore.SERVER_TIMESTAMP, 'quiz_points': 0, 'total_quiz_questions_answered': 0, 'total_quiz_questions_correct': 0})
        return jsonify({"message": "User created successfully. Please login."}), 201
    except Exception as e:
        app.logger.error(f"Signup failed: {e}"); return jsonify({"error": "An internal error occurred during signup."}), 500

@app.route('/login', methods=['POST'])
@limiter.limit("30 per minute") 
def login_user():
    if not db: return jsonify({"error": "Database not configured"}), 500
    data = request.get_json();
    if not data: return jsonify({"error": "No input data provided"}), 400
    identifier = str(data.get('email_or_username', '')).strip(); password = str(data.get('password', ''))
    if not identifier or not password: return jsonify({"error": "Missing username/email or password"}), 400
    try:
        is_email = '@' in identifier; user_ref = db.collection('users'); query = user_ref.where('email' if is_email else 'username_lowercase', '==', identifier.lower()).limit(1); docs = list(query.stream())
        if not docs: return jsonify({"error": "Invalid credentials"}), 401
        user_doc = docs[0]; user_data = user_doc.to_dict()
        if not user_data or not check_password_hash(user_data.get('password_hash', ''), password): return jsonify({"error": "Invalid credentials"}), 401
        token_payload = {'user_id': user_doc.id, 'username': user_data.get('username'), 'email': user_data.get('email'), 'tier': user_data.get('tier', 'standard'),'exp': datetime.now(timezone.utc) + app.config['JWT_ACCESS_TOKEN_EXPIRES']}
        access_token = jwt.encode(token_payload, app.config['JWT_SECRET_KEY'], algorithm='HS256')
        return jsonify({"message": "Login successful", "access_token": access_token, "user": {"id": user_doc.id, "username": user_data.get('username'), "email": user_data.get('email'), "tier": user_data.get('tier')}}), 200
    except Exception as e:
        app.logger.error(f"Login failed: {e}"); return jsonify({"error": "An internal error occurred during login."}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() in ['true', '1', 't']
    app.run(host='0.0.0.0', port=port, debug=debug_mode)