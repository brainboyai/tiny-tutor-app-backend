# app.py (Only the /generate_explanation route and relevant parts are shown for brevity)
# ... (keep all other imports and app setup as in your current app.py v3_full_cache) ...
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

# --- (Assume all your existing Flask app setup, Firebase init, helpers, and other routes are here) ---
# For context, ensure these are defined as they were in your previous full app.py:
# load_dotenv()
# app = Flask(__name__)
# CORS(app, ...)
# app.config['JWT_SECRET_KEY'] = ...
# app.config['JWT_ACCESS_TOKEN_EXPIRES'] = ...
# db = ... (Firebase client)
# sanitize_word_for_firestore = ...
# jwt_required decorator = ...
# All other routes like /signup, /login, /toggle_favorite, /profile

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

    # Define placeholders for image and deep modes
    placeholder_image_text = "Image generation feature coming soon! You can imagine an image of '{question}'."
    placeholder_deep_text = "In-depth explanation feature coming soon! We're working on providing more detailed insights for '{question}'."

    # --- Firestore Logging Setup (common for all modes) ---
    sanitized_word_id = sanitize_word_for_firestore(question)
    word_doc_ref = db.collection('users').document(user_id).collection('word_history').document(sanitized_word_id)
    word_doc_snapshot = word_doc_ref.get()
    current_timestamp = firestore.SERVER_TIMESTAMP
    
    explanation_text_to_return = "" # Will hold the text to send back to frontend

    # --- Handle Placeholder Modes First ---
    if content_type == 'image':
        explanation_text_to_return = placeholder_image_text.format(question=question)
    elif content_type == 'deep':
        explanation_text_to_return = placeholder_deep_text.format(question=question)
    
    # If it's a placeholder mode, we can log and return immediately
    if content_type == 'image' or content_type == 'deep':
        try:
            if word_doc_snapshot.exists:
                existing_data = word_doc_snapshot.to_dict()
                modes_generated = existing_data.get('modes_generated', [])
                if content_type not in modes_generated:
                    modes_generated.append(content_type)
                
                update_data = {
                    'last_explored_at': current_timestamp,
                    'modes_generated': modes_generated,
                    # Store the placeholder text in the cache for these modes
                    f'generated_content_cache.{content_type}': explanation_text_to_return 
                }
                word_doc_ref.update(update_data)
            else:
                word_doc_ref.set({
                    'word': question,
                    'sanitized_word': question.strip().lower(),
                    'is_favorite': False,
                    'first_explored_at': current_timestamp,
                    'last_explored_at': current_timestamp,
                    'modes_generated': [content_type],
                    'generated_content_cache': {content_type: explanation_text_to_return}
                })
            return jsonify({"explanation": explanation_text_to_return}), 200
        except Exception as e:
            print(f"Error logging placeholder for {content_type} mode: {e}")
            # Still return the placeholder to the user even if logging fails for some reason
            return jsonify({"explanation": explanation_text_to_return, "warning": "Could not save history for this placeholder."}), 200


    # --- Handle Actual Gemini API Call for other modes (explain, fact, quiz) ---
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
    GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
    if not GEMINI_API_KEY: return jsonify({"error": "Gemini API key missing"}), 500

    prompt_templates = { # Only define for modes that hit Gemini
        'explain': "Provide a concise, easy-to-understand explanation for '{question}'.",
        'fact': "Give one interesting fact about '{question}'.",
        'quiz': "Generate a simple multiple-choice quiz about '{question}' with 4 options and the correct answer (e.g., 'Correct: C) ...')."
        # 'deep' is now handled above as a placeholder
    }
    prompt_template = prompt_templates.get(content_type) # Should always find a key now for non-placeholder modes
    
    if not prompt_template: # Should not happen if content_type is validated or defaults correctly
        return jsonify({"error": "Invalid content type for API call."}), 400

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
            explanation_text_to_return = generated_text # Set for logging and return

            # Log to Firestore (same logic as before, but now `explanation_text_to_return` has the Gemini response)
            if word_doc_snapshot.exists:
                existing_data = word_doc_snapshot.to_dict()
                modes_generated = existing_data.get('modes_generated', [])
                if content_type not in modes_generated:
                    modes_generated.append(content_type)
                update_data = {
                    'last_explored_at': current_timestamp,
                    'modes_generated': modes_generated,
                    f'generated_content_cache.{content_type}': explanation_text_to_return
                }
                word_doc_ref.update(update_data)
            else:
                word_doc_ref.set({
                    'word': question,
                    'sanitized_word': question.strip().lower(),
                    'is_favorite': False,
                    'first_explored_at': current_timestamp,
                    'last_explored_at': current_timestamp,
                    'modes_generated': [content_type],
                    'generated_content_cache': {content_type: explanation_text_to_return}
                })
            
            return jsonify({"explanation": explanation_text_to_return}), 200
        else:
            return jsonify({"error": "Failed to generate content from AI."}), 500
    except requests.exceptions.Timeout: return jsonify({"error": "AI service request timed out."}), 504
    except requests.exceptions.RequestException as e: return jsonify({"error": f"AI service error: {e}"}), 502
    except Exception as e: return jsonify({"error": f"Unexpected error: {e}"}), 500

# ... (rest of your app.py: /toggle_favorite, /profile, if __name__ == '__main__': etc.) ...