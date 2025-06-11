# firestore_handler.py

from firebase_admin import firestore
from datetime import datetime, timezone, timedelta
from google.cloud.firestore_v1.base_query import FieldFilter
import logging

def sanitize_word_for_id(word: str) -> str:
    """A helper function to ensure consistent document IDs."""
    if not isinstance(word, str): return "invalid_input"
    import re
    sanitized = word.lower()
    sanitized = re.sub(r'\s+', '_', sanitized)
    sanitized = re.sub(r'[^a-z0-9_]', '', sanitized)
    return sanitized if sanitized else "empty_word"

def get_user_profile_data(db, user_id: str):
    """
    Fetches and formats all profile data for a given user.
    """
    user_doc_ref = db.collection('users').document(user_id)
    user_doc = user_doc_ref.get()
    if not user_doc.exists:
        raise ValueError("User not found")
    
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
    return {
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
    }

def toggle_favorite_status(db, user_id: str, word: str):
    """
    Toggles the 'is_favorite' status of a word for a user.
    """
    sanitized_word_id = sanitize_word_for_id(word)
    word_ref = db.collection('users').document(user_id).collection('word_history').document(sanitized_word_id)
    word_doc = word_ref.get()

    if not word_doc.exists:
        word_ref.set({
            'word': word, 'first_explored_at': firestore.SERVER_TIMESTAMP,
            'last_explored_at': firestore.SERVER_TIMESTAMP, 'is_favorite': True,
            'generated_content_cache': {}, 'modes_generated': []
        })
        return True # Returns the new 'is_favorite' status

    current_status = word_doc.to_dict().get('is_favorite', False)
    new_status = not current_status
    word_ref.update({'is_favorite': new_status, 'last_explored_at': firestore.SERVER_TIMESTAMP})
    return new_status

def save_streak_to_db(db, user_id: str, words: list, score: int):
    """
    Saves a completed streak to the database, avoiding recent duplicates.
    """
    streaks_ref = db.collection('users').document(user_id).collection('streaks')
    two_minutes_ago = datetime.now(timezone.utc) - timedelta(minutes=2)

    # Query for identical streaks in the last 2 minutes to prevent duplicates
    query = streaks_ref.where(filter=FieldFilter('words', '==', words)).where(filter=FieldFilter('completed_at', '>', two_minutes_ago)).limit(1)
    
    if not list(query.stream()):
        streaks_ref.add({'words': words, 'score': score, 'completed_at': firestore.SERVER_TIMESTAMP})
        logging.info(f"Streak saved for user {user_id}")
    else:
        logging.info(f"Duplicate streak detected for user {user_id}. Ignoring.")
    
    # Return the updated streak history
    streak_history_list = []
    history_query = streaks_ref.order_by('completed_at', direction=firestore.Query.DESCENDING).limit(50).stream()
    for doc in history_query:
        streak = doc.to_dict()
        completed_at = streak.get("completed_at")
        streak_history_list.append({
            "id": doc.id, "words": streak.get("words", []), "score": streak.get("score", 0),
            "completed_at": completed_at.isoformat() if isinstance(completed_at, datetime) else str(completed_at)
        })
    return streak_history_list


def save_quiz_attempt_to_db(db, user_id: str, word: str, is_correct: bool):
    """
    Logs a quiz attempt and updates user stats.
    """
    user_ref = db.collection('users').document(user_id)
    word_ref = user_ref.collection('word_history').document(sanitize_word_for_id(word))

    # Ensure the word exists in history
    word_doc = word_ref.get()
    if not word_doc.exists:
        word_ref.set({
            'word': word, 'first_explored_at': firestore.SERVER_TIMESTAMP,
            'last_explored_at': firestore.SERVER_TIMESTAMP, 'is_favorite': False,
            'modes_generated': ['quiz']
        }, merge=True)
    else:
        word_ref.update({
            'modes_generated': firestore.ArrayUnion(['quiz']),
            'last_explored_at': firestore.SERVER_TIMESTAMP
        })
    
    # Update user's aggregate stats
    user_update_payload = {'total_quiz_questions_answered': firestore.Increment(1)}
    if is_correct:
        user_update_payload['total_quiz_questions_correct'] = firestore.Increment(1)
        user_update_payload['quiz_points'] = firestore.Increment(10)
    
    user_ref.update(user_update_payload)
