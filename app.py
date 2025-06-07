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

# --- Story Mode Endpoint with ROBUST JSON PROMPT ---
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
Role: You are an expert Curriculum Designer and Interactive Narrative Game Developer.
Objective: Generate a SINGLE interaction cycle for an educational narrative game. The content must be engaging, game-like, and test the user's intuition before explaining concepts.
Instructions:
- Dialogue should be from your AI teacher persona, be concise, and age-appropriate (Grade 6).
- Image Prompts must be purely educational, contextual, and contain no text or illustrative characters.
- User Interaction options must guide the user toward the learning goal.
- Your entire output MUST be a single, valid JSON object. Do not include any text or markdown formatting before or after the JSON.

Input for this segment:
- Learning Topic/Concept: "{topic}"
- Target Audience/Grade Level: "Grade 6 Science"
- Segment Goal/Learning Outcome: "User can visually identify and describe the difference between tap roots and fibrous roots."
- Desired Visual Style for Images: "Clean and clear 2D educational illustrations"
"""

    if not history:
        prompt = base_prompt.format(topic=topic) + """
- Segment Type: "Introduction with common-sense testing"
Now, generate the VERY FIRST interaction cycle.
"""
    else:
        prompt_history = "\\n".join([f"{item['type']}: {item['text']}" for item in history])
        prompt = base_prompt.format(topic=topic) + f"""
- Brief Summary of Previous Segment: The conversation so far has been:\\n{prompt_history}
- Segment Type: "Continuation or Question"
The user has just made a choice that "Leads to: {last_choice_leads_to}". Now, generate the SINGLE, COMPLETE interaction cycle for "{last_choice_leads_to}".
"""

    try:
        gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')
        
        # This is the key change: Tell the model to output JSON
        generation_config = genai.types.GenerationConfig(
            response_mime_type="application/json"
        )
        
        response = gemini_model.generate_content(
            prompt,
            generation_config=generation_config
        )
        
        # The response.text is now a reliable JSON string
        parsed_node = json.loads(response.text)
        
        # Basic validation
        if not all(k in parsed_node for k in ["dialogue", "image_prompts", "interaction"]):
            raise ValueError("AI response JSON did not contain the required keys.")

        return jsonify(parsed_node), 200

    except (json.JSONDecodeError, ValueError) as e:
        app.logger.error(f"Failed to process AI JSON response for topic '{topic}'. Error: {e}. Response text: {response.text}")
        return jsonify({"error": "The AI returned an unreadable story format. Please try again."}), 500
    except Exception as e:
        app.logger.error(f"Error in /generate_story_node for user {current_user_id}, topic '{topic}': {e}")
        return jsonify({"error": f"An internal error occurred: {str(e)}"}), 500


# --- All other existing endpoints remain the same ---
@app.route('/')
def home():
    return "Tiny Tutor Backend is running!"
# (... The rest of your endpoints: /signup, /login, /generate_explanation, etc. remain unchanged ...)
@app.route('/signup', methods=['POST'])
@limiter.limit("5 per hour")
def signup_user():
    if not db: return jsonify({"error": "Database not configured"}), 500
    data = request.get_json()
    if not data: return jsonify({"error": "No input data provided"}), 400
    username = data.get('username', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    if not username or not email or not password: return jsonify({"error": "Username, email, and password are required"}), 400
    try:
        users_ref = db.collection('users')
        if len(list(users_ref.where('username_lowercase', '==', username.lower()).limit(1).stream())) > 0:
            return jsonify({"error": "Username already exists"}), 409
        if len(list(users_ref.where('email', '==', email).limit(1).stream())) > 0:
            return jsonify({"error": "Email already registered"}), 409
        
        user_doc_ref = users_ref.document()
        user_doc_ref.set({
            'username': username, 'username_lowercase': username.lower(), 'email': email,
            'password_hash': generate_password_hash(password), 'tier': 'standard', 
            'created_at': firestore.SERVER_TIMESTAMP, 'quiz_points': 0,
            'total_quiz_questions_answered': 0, 'total_quiz_questions_correct': 0
        })
        return jsonify({"message": "User created successfully. Please login."}), 201
    except Exception as e:
        app.logger.error(f"Signup failed: {e}")
        return jsonify({"error": "An internal error occurred during signup."}), 500

@app.route('/login', methods=['POST'])
@limiter.limit("30 per minute") 
def login_user():
    if not db: return jsonify({"error": "Database not configured"}), 500
    data = request.get_json()
    if not data: return jsonify({"error": "No input data provided"}), 400
    identifier = str(data.get('email_or_username', '')).strip()
    password = str(data.get('password', ''))
    if not identifier or not password: return jsonify({"error": "Missing username/email or password"}), 400
    try:
        is_email = '@' in identifier
        user_ref = db.collection('users')
        query = user_ref.where('email' if is_email else 'username_lowercase', '==', identifier.lower()).limit(1)
        docs = list(query.stream())
        if not docs: return jsonify({"error": "Invalid credentials"}), 401
        user_doc = docs[0]
        user_data = user_doc.to_dict()
        if not user_data or not check_password_hash(user_data.get('password_hash', ''), password):
            return jsonify({"error": "Invalid credentials"}), 401
        token_payload = {
            'user_id': user_doc.id, 'username': user_data.get('username'), 
            'email': user_data.get('email'), 'tier': user_data.get('tier', 'standard'),
            'exp': datetime.now(timezone.utc) + app.config['JWT_ACCESS_TOKEN_EXPIRES']
        }
        access_token = jwt.encode(token_payload, app.config['JWT_SECRET_KEY'], algorithm='HS256')
        return jsonify({
            "message": "Login successful", "access_token": access_token,
            "user": {"id": user_doc.id, "username": user_data.get('username'), 
                     "email": user_data.get('email'), "tier": user_data.get('tier')}
        }), 200
    except Exception as e:
        app.logger.error(f"Login failed: {e}")
        return jsonify({"error": "An internal error occurred during login."}), 500

@app.route('/generate_explanation', methods=['POST', 'OPTIONS'])
@token_required
@limiter.limit("150/hour")
def generate_explanation_route(current_user_id):
    if not db: return jsonify({"error": "Database not configured"}), 500
    if not gemini_api_key: return jsonify({"error": "AI service not configured"}), 500
    data = request.get_json()
    if not data: return jsonify({"error": "No input data provided"}), 400

    word = data.get('word', '').strip()
    mode = data.get('mode', 'explain').strip().lower()
    force_refresh = data.get('refresh_cache', False)
    streak_context_list = data.get('streakContext', []) 
    explanation_text_for_quiz = data.get('explanation_text', None)

    if not word: return jsonify({"error": "Word/concept is required"}), 400
    
    if mode == 'quiz' and not explanation_text_for_quiz:
        return jsonify({"error": "Explanation text is now mandatory to generate a quiz."}), 400

    sanitized_word_id = sanitize_word_for_id(word)
    user_word_history_ref = db.collection('users').document(current_user_id).collection('word_history').document(sanitized_word_id)

    try:
        word_doc = user_word_history_ref.get()
        cached_content_from_db = {} 
        is_favorite_status = False
        modes_already_generated = []

        if word_doc.exists:
            word_data = word_doc.to_dict()
            cached_content_from_db = word_data.get('generated_content_cache', {})
            is_favorite_status = word_data.get('is_favorite', False)

        is_contextual_explain_call = mode == 'explain' and bool(streak_context_list)

        if mode != 'quiz' and not is_contextual_explain_call and not force_refresh and mode in cached_content_from_db:
            user_word_history_ref.set({'last_explored_at': firestore.SERVER_TIMESTAMP, 'word': word}, merge=True)
            if word_doc.exists: modes_already_generated = word_doc.to_dict().get('modes_generated', [])
            return jsonify({
                "word": word, mode: cached_content_from_db[mode], "source": "cache",
                "is_favorite": is_favorite_status, "full_cache": cached_content_from_db,
                "modes_generated": modes_already_generated 
            }), 200

        prompt = ""
        current_request_content_holder = {}

        if mode == 'explain':
            primary_word_for_prompt = word 
            if not streak_context_list: 
                prompt = f"""Your task is to define '{primary_word_for_prompt}', acting as a knowledgeable guide introducing a foundational concept to a curious beginner.
Instructions: Define '{primary_word_for_prompt}' in exactly two sentences using the simplest, most basic, and direct language suitable for a complete beginner with no prior knowledge; focus on its core, fundamental aspects. Within these sentences, embed the maximum number of distinct, foundational sub-topics (key terms, core concepts, related ideas) that are crucial not only for grasping '{primary_word_for_prompt}' but also for sparking further inquiry and naturally leading towards a deeper exploration—think of these as initial pathways into a fascinating subject. These sub-topics must not be mere synonyms or rephrasing of '{primary_word_for_prompt}'. If '{primary_word_for_prompt}' involves mathematics, physics, chemistry, or similar fields, embed any critical fundamental formulas or equations (using LaTeX, e.g., $E=mc^2$) as sub-topics. Wrap all sub-topics (textual, formulas, equations) in <click>tags</click> (e.g., <click>energy conversion</click>, <click>$A=\pi r^2$</click>). Your response must consist strictly of the two definition sentences containing the embedded clickable sub-topics. Do not include any headers, introductory phrases, or these instructions in your output.
Example of the expected output format: Photosynthesis is a <click>biological process</click> in <click>plants</click> and other organisms converting <click>light energy</click> into <click>chemical energy</click>, often represented by <click>6CO_2+6H_2O+textLightrightarrowC_6H_12O_6+6O_2</click>. This process uses <click>carbon dioxide</click> and <click>water</click> to produce <click>glucose</click> (a <click>sugar</click>) and <click>oxygen</click>.
"""
            else: 
                current_word_for_prompt = word 
                context_string = ", ".join(streak_context_list)
                all_relevant_words_for_reiteration_check = [current_word_for_prompt] + streak_context_list
                reiteration_check_string = ", ".join(all_relevant_words_for_reiteration_check)
                prompt = f"""Your task is to define '{current_word_for_prompt}', acting as a teacher guiding a student step-by-step down a 'rabbit hole' of knowledge. The student has already learned about the following concepts in this order: '{context_string}'.
Instructions: Define '{current_word_for_prompt}' in exactly two sentences using the simplest, most basic, and direct language suitable for a complete beginner. Your explanation must clearly show how '{current_word_for_prompt}' relates to, builds upon, or offers a new dimension to the established learning path of '{context_string}'. Focus on its core aspects as they specifically connect to this narrative of exploration. Within these sentences, embed the maximum number of distinct, foundational sub-topics (key terms, core concepts, related ideas). These sub-topics should be crucial for understanding '{current_word_for_prompt}' within this specific learning sequence and should themselves be chosen to intelligently suggest further avenues of exploration, continuing the streak of discovery. Crucially, these embedded sub-topics must not be a simple reiteration of any words found in '{reiteration_check_string}'. If '{current_word_for_prompt}' (when considered in the context of '{context_string}') involves mathematics, physics, chemistry, or similar fields, embed any critical fundamental formulas or equations (using LaTeX, e.g., $E=mc^2$) as sub-topics. Wrap all sub-topics (textual, formulas, equations) in <click>tags</click> (e.g., <click>relevant concept</click>, <click>$y=mx+c$</click>). Your response must consist strictly of the two definition sentences containing the embedded clickable sub-topics. Do not include any headers, introductory phrases, or these instructions in your output.
Example of the expected output format: Photosynthesis is a <click>biological process</click> in <click>plants</click> and other organisms converting <click>light energy</click> into <click>chemical energy</click>, often represented by <click>6CO2​+6H2​O+Light→C6​H12​O6​+6O2​</click>. This process uses <click>carbon dioxide</click> and <click>water</click> to produce <click>glucose</click> (a <click>sugar</click>) and <click>oxygen</click>.
"""
        elif mode == 'quiz': 
            context_hint_for_quiz = ""
            if streak_context_list:
                context_hint_for_quiz = f" The learning path so far included: {', '.join(streak_context_list)}."

            prompt = (
                f"Based on the following explanation text for the term '{word}', generate a set of exactly 1 distinct multiple-choice quiz questions. "
                f"The questions should test understanding of the key concepts presented in this specific text.{context_hint_for_quiz}\n\n"
                f"Explanation Text:\n\"\"\"{explanation_text_for_quiz}\"\"\"\n\n"
                "For each question, strictly follow this exact format, including newlines:\n"
                "**Question [Number]:** [Your Question Text Here]\n"
                "A) [Option A Text]\n"
                "B) [Option B Text]\n"
                "C) [Option C Text]\n"
                "D) [Option D Text]\n"
                "Correct Answer: [Single Letter A, B, C, or D]\n"
                "Explanation: [Optional: A brief explanation for the correct answer or why other options are incorrect]\n"
                "Ensure option keys are unique. Separate each complete question block with '---QUIZ_SEPARATOR---'."
            )

        if mode in ['explain', 'quiz'] and prompt:
            gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')
            response = gemini_model.generate_content(prompt)
            llm_output_text = response.text.strip()
            if mode == 'quiz':
                quiz_questions_array = [q.strip() for q in llm_output_text.split('---QUIZ_SEPARATOR---') if q.strip()]
                if not quiz_questions_array and llm_output_text:
                    quiz_questions_array = [llm_output_text]
                current_request_content_holder[mode] = quiz_questions_array
            else:
                current_request_content_holder[mode] = llm_output_text
                if not is_contextual_explain_call:
                    cached_content_from_db[mode] = llm_output_text
        
        db_modes_generated = []
        if word_doc.exists:
            db_modes_generated = word_doc.to_dict().get('modes_generated', [])
        
        current_modes_set = set(db_modes_generated)
        current_modes_set.add(mode)
        modes_already_generated = sorted(list(current_modes_set))

        payload_for_db = {
            'word': word, 
            'last_explored_at': firestore.SERVER_TIMESTAMP,
            'modes_generated': modes_already_generated,
        }
        if cached_content_from_db:
             payload_for_db['generated_content_cache'] = cached_content_from_db
        
        if 'quiz' in payload_for_db.get('generated_content_cache', {}):
            del payload_for_db['generated_content_cache']['quiz']

        if not word_doc.exists: 
            payload_for_db.update({
                'first_explored_at': firestore.SERVER_TIMESTAMP, 
                'is_favorite': False, 
            })
            is_favorite_status = False
        else:
            payload_for_db['is_favorite'] = is_favorite_status 

        user_word_history_ref.set(payload_for_db, merge=True)

        response_payload = {
            "word": word, 
            mode: current_request_content_holder.get(mode),
            "source": "generated",
            "is_favorite": payload_for_db.get('is_favorite', is_favorite_status),
            "full_cache": cached_content_from_db,
            "modes_generated": modes_already_generated
        }
        return jsonify(response_payload), 200
    except Exception as e:
        app.logger.error(f"Error in /generate_explanation for user {current_user_id}, word '{word}', mode '{mode}': {e}")
        return jsonify({"error": f"An internal error occurred: {e}"}), 500

@app.route('/profile', methods=['GET', 'OPTIONS'])
@token_required
def get_user_profile(current_user_id):
    if not db: return jsonify({"error": "Database not configured"}), 500
    try:
        user_doc_ref = db.collection('users').document(current_user_id)
        user_doc = user_doc_ref.get()
        if not user_doc.exists: return jsonify({"error": "User not found"}), 404
        user_data = user_doc.to_dict()

        word_history_list = []
        favorite_words_list = []
        
        word_history_query = user_doc_ref.collection('word_history').order_by('last_explored_at', direction=firestore.Query.DESCENDING).stream()
        for doc in word_history_query:
            entry = doc.to_dict()
            if not entry.get("word"): 
                continue
            
            last_explored_at_val = entry.get("last_explored_at")
            first_explored_at_val = entry.get("first_explored_at")

            entry_data = {
                "word": entry.get("word"),
                "is_favorite": entry.get("is_favorite", False),
                "last_explored_at": last_explored_at_val.isoformat() if isinstance(last_explored_at_val, datetime) else str(last_explored_at_val) if last_explored_at_val else None,
                "first_explored_at": first_explored_at_val.isoformat() if isinstance(first_explored_at_val, datetime) else str(first_explored_at_val) if first_explored_at_val else None,
            }
            word_history_list.append(entry_data)
            if entry_data["is_favorite"]:
                favorite_words_list.append(entry_data)
        
        streak_history_list = []
        streak_history_query = user_doc_ref.collection('streaks').order_by('completed_at', direction=firestore.Query.DESCENDING).limit(50).stream()
        for doc in streak_history_query:
            streak = doc.to_dict()
            completed_at_val = streak.get("completed_at")
            streak_history_list.append({
                "id": doc.id, "words": streak.get("words", []), "score": streak.get("score", 0),
                "completed_at": completed_at_val.isoformat() if isinstance(completed_at_val, datetime) else str(completed_at_val) if completed_at_val else None,
            })
        
        created_at_val = user_data.get("created_at")
        return jsonify({
            "username": user_data.get("username"), 
            "email": user_data.get("email"), 
            "tier": user_data.get("tier"),
            "totalWordsExplored": len(word_history_list),
            "exploredWords": word_history_list, 
            "favoriteWords": favorite_words_list, 
            "streakHistory": streak_history_list, 
            "created_at": created_at_val.isoformat() if isinstance(created_at_val, datetime) else str(created_at_val) if created_at_val else None,
            "quiz_points": user_data.get("quiz_points", 0),
            "total_quiz_questions_answered": user_data.get("total_quiz_questions_answered", 0),
            "total_quiz_questions_correct": user_data.get("total_quiz_questions_correct", 0)
        }), 200
    except Exception as e:
        app.logger.error(f"Failed to fetch profile for user {current_user_id}: {e}")
        return jsonify({"error": f"Failed to fetch profile: {e}"}), 500

@app.route('/toggle_favorite', methods=['POST', 'OPTIONS'])
@token_required
def toggle_favorite_word(current_user_id):
    if not db: return jsonify({"error": "Database not configured"}), 500
    data = request.get_json()
    word_to_toggle = data.get('word', '').strip()
    if not word_to_toggle: return jsonify({"error": "Word is required"}), 400
    sanitized_word_id = sanitize_word_for_id(word_to_toggle)
    word_ref = db.collection('users').document(current_user_id).collection('word_history').document(sanitized_word_id)
    try:
        word_doc = word_ref.get()
        if not word_doc.exists:
            word_ref.set({
                'word': word_to_toggle, 'first_explored_at': firestore.SERVER_TIMESTAMP,
                'last_explored_at': firestore.SERVER_TIMESTAMP, 'is_favorite': True, 
                'generated_content_cache': {}, 'modes_generated': []
            }, merge=True) 
            return jsonify({"message": "Word added and favorited", "word": word_to_toggle, "is_favorite": True}), 200

        current_is_favorite = word_doc.to_dict().get('is_favorite', False)
        new_favorite_status = not current_is_favorite
        word_ref.update({'is_favorite': new_favorite_status, 'last_explored_at': firestore.SERVER_TIMESTAMP})
        return jsonify({"message": "Favorite status updated", "word": word_to_toggle, "is_favorite": new_favorite_status}), 200
    except Exception as e:
        app.logger.error(f"Failed to toggle favorite for user {current_user_id}, word '{word_to_toggle}': {e}")
        return jsonify({"error": f"Failed to toggle favorite: {e}"}), 500

@app.route('/save_streak', methods=['POST', 'OPTIONS'])
@token_required
def save_user_streak(current_user_id):
    if not db: return jsonify({"error": "Database not configured"}), 500
    data = request.get_json()
    if not data: return jsonify({"error": "No input data provided"}), 400
    streak_words = data.get('words')
    streak_score = data.get('score')
    if not isinstance(streak_words, list) or not streak_words or not isinstance(streak_score, int) or streak_score < 2:
        return jsonify({"error": "Invalid streak data"}), 400
    try:
        streaks_collection_ref = db.collection('users').document(current_user_id).collection('streaks')
        two_minutes_ago = datetime.now(timezone.utc) - timedelta(minutes=2)
        
        existing_streaks_query = streaks_collection_ref \
            .where(filter=FieldFilter('words', '==', streak_words)) \
            .where(filter=FieldFilter('completed_at', '>', two_minutes_ago)) \
            .limit(1).stream()

        if not list(existing_streaks_query):
            streak_doc_ref = streaks_collection_ref.document()
            streak_doc_ref.set({'words': streak_words, 'score': streak_score, 'completed_at': firestore.SERVER_TIMESTAMP})
            app.logger.info(f"Streak saved for user {current_user_id}")
        else:
            app.logger.info(f"Duplicate streak detected for user {current_user_id}. Ignoring save.")

        streak_history_list = []
        streak_history_query = streaks_collection_ref.order_by('completed_at', direction=firestore.Query.DESCENDING).limit(50).stream()
        for doc in streak_history_query:
            streak = doc.to_dict()
            completed_at_val = streak.get("completed_at")
            streak_history_list.append({
                "id": doc.id,
                "words": streak.get("words", []),
                "score": streak.get("score", 0),
                "completed_at": completed_at_val.isoformat() if isinstance(completed_at_val, datetime) else str(completed_at_val) if completed_at_val else None,
            })
            
        return jsonify({"message": "Streak processed", "streakHistory": streak_history_list}), 200
        
    except Exception as e:
        app.logger.error(f"Failed to save streak for user {current_user_id}: {e}")
        return jsonify({"error": f"Failed to save streak: {e}"}), 500

@app.route('/save_quiz_attempt', methods=['POST', 'OPTIONS'])
@token_required
def save_quiz_attempt_route(current_user_id):
    if not db: return jsonify({"error": "Database not configured"}), 500
    data = request.get_json()
    if not data: return jsonify({"error": "No data provided"}), 400

    word = data.get('word', '').strip()
    is_correct = data.get('is_correct')

    if not word or is_correct is None:
        return jsonify({"error": "Missing required fields (word, is_correct)"}), 400

    user_doc_ref = db.collection('users').document(current_user_id)
    word_history_ref = user_doc_ref.collection('word_history').document(sanitize_word_for_id(word))

    try:
        word_doc = word_history_ref.get()
        if not word_doc.exists:
            word_history_ref.set({
                'word': word,
                'first_explored_at': firestore.SERVER_TIMESTAMP,
                'last_explored_at': firestore.SERVER_TIMESTAMP,
                'is_favorite': False,
                'modes_generated': ['quiz']
            }, merge=True)
        else:
            current_modes = word_doc.to_dict().get('modes_generated', [])
            if 'quiz' not in current_modes:
                current_modes.append('quiz')
            word_history_ref.update({
                'last_explored_at': firestore.SERVER_TIMESTAMP,
                'modes_generated': sorted(list(set(current_modes)))
            })

        user_update_payload = {'total_quiz_questions_answered': firestore.Increment(1)}
        if is_correct:
            user_update_payload['total_quiz_questions_correct'] = firestore.Increment(1)
            user_update_payload['quiz_points'] = firestore.Increment(10)
        
        user_doc_ref.update(user_update_payload)
        
        return jsonify({"message": "Quiz attempt processed and stats updated"}), 200
    except Exception as e:
        app.logger.error(f"Failed to save quiz attempt stats for user {current_user_id}, word '{word}': {e}")
        return jsonify({"error": f"Failed to save quiz attempt: {e}"}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() in ['true', '1', 't']
    app.run(host='0.0.0.0', port=port, debug=debug_mode)