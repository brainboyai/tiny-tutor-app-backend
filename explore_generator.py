import google.generativeai as genai
import logging
import requests
import json
import os
import time
from urllib.parse import quote_plus

gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')


def get_image_urls_for_topic(topic: str, num_images: int = 2):
    """
    Performs a reliable image search using the official Pexels API.
    This is the definitive, stable method for getting images.
    """
    logging.warning(f"--- Starting Pexels API image search for topic: '{topic}' ---")
    
    api_key = os.getenv("PEXELS_API_KEY")
    if not api_key:
        logging.error("PEXELS_API_KEY is not set. Cannot search for images.")
        return []

    try:
        headers = {"Authorization": api_key}
        query = quote_plus(topic)
        url = f"https://api.pexels.com/v1/search?query={query}&per_page={num_images}"
        
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        data = response.json()
        
        # Extract the 'large' image URL from each photo result
        image_urls = [photo['src']['large'] for photo in data.get('photos', [])]
        
        logging.warning(f"--- Found {len(image_urls)} images from Pexels for '{topic}': {image_urls} ---")
        return image_urls

    except requests.exceptions.RequestException as e:
        logging.error(f"Pexels API request FAILED for topic '{topic}': {e}")
        return []
    except Exception as e:
        logging.error(f"An UNEXPECTED error occurred during Pexels search for topic '{topic}': {e}")
        return []
    
def generate_agentic_suggestions(topic: str, language: str = 'en', explanation_text: str = ''):
    """
    Analyzes a topic's type and generates a list of actionable search intents that serve as both
    user-facing suggestions and machine-readable queries for a web context agent.
    """
    logging.warning(f"--- Generating actionable search intents for topic: '{topic}' ---")
    
    # This new, advanced prompt instructs the AI to categorize the topic first,
    # then generate specific, actionable search queries based on that category.
    prompt = f"""
    You are an expert Search Intent Generator. Your task is to bridge human curiosity with web search by creating a list of actionable search queries. These queries will be displayed to a user as clickable suggestions and then used directly by a web search agent.

    First, analyze the user's topic and its explanation to determine its category. Is it a place, a brand/company, a scientific concept, a historical event, a person, etc.?

    Based on that category, generate a JSON-formatted list of 3 to 5 diverse, actionable search queries. Each query should combine the topic with a clear user intent (like shopping, travel, learning, watching videos, or finding news).

    The response MUST be a raw JSON object with a single key "suggestions" containing a list of strings.

    **Topic:** "{topic}"
    **Explanation they just read:** "{explanation_text}"

    --- EXAMPLES ---

    1.  **If the topic is a place (e.g., "Delhi"):** The intents should be about travel, culture, food, and local information.
        {{"suggestions": ["news about Delhi", "shopping in Delhi", "Delhi culture", "hotels in Delhi", "travel to Delhi"]}}

    2.  **If the topic is a brand or product (e.g., "Adidas"):** The intents should be about shopping, news, official resources, and media.
        {{"suggestions": ["news about adidas", "videos about adidas", "shop for adidas products", "official adidas website"]}}

    3.  **If the topic is a scientific or abstract concept (e.g., "Aerodynamics"):** The intents should be about learning, reading, and visual explanations.
        {{"suggestions": ["what is aerodynamics", "books about aerodynamics", "videos explaining aerodynamics", "aerodynamics tutorials"]}}

    Now, generate the appropriate suggestions for the given topic: "{topic}".

    **Language Mandate:** All suggestions MUST be in the following language code: '{language}'.
    """
    
    try:
        response = gemini_model.generate_content(prompt)
        
        # Clean up the response to ensure it's valid JSON, removing potential markdown.
        clean_response = response.text.strip()
        if clean_response.startswith("```json"):
            clean_response = clean_response[7:-3].strip()
        elif clean_response.startswith("```"):
             clean_response = clean_response[3:-3].strip()

        suggestions_dict = json.loads(clean_response)
        suggestions = suggestions_dict.get("suggestions", [])

        logging.warning(f"--- Found actionable search intents for '{topic}': {suggestions} ---")
        return suggestions

    except Exception as e:
        logging.error(f"Could not generate or parse actionable search intents for '{topic}': {e}")
        # Return an empty list if there's an error so the app doesn't crash.
        return []
    
def generate_explanation(word: str, streak_context: list = None, language: str = 'en', nonce: float = 0.0):
    """
    Generates a meaningful, concise explanation designed for learning and action, 
    and finds related images and agentic suggestions.
    """
    prompt = ""
    # This is the prompt for a new topic or the first in a streak.
    if not streak_context:
        prompt = f"""You are an Expert Explainer. Your audience is a curious, everyday global user who wants to understand the world better. Your goal is to provide a clear, concise, and practical understanding of '{word}' that makes them feel smart and empowered. This explanation will also be used by another AI to suggest real-world activities, so it must be grounded in practical reality.

Instructions:
1.  **Craft a Two-Sentence Explanation:**
    * **Sentence 1: What is it?** Define '{word}' in simple, direct terms. Use a relatable analogy if it helps clarify the core concept (e.g., "Think of it as...").
    * **Sentence 2: Why does it matter?** Explain its primary importance or what it enables in the real world. This should provide a clear hook for why someone should care.
2.  **Select "Deeper Dive" Sub-topics:**
    * Within your two sentences, embed a few (3-5) highly-focused sub-topics that are the *essential building blocks* or *core components* of '{word}'.
    * These sub-topics must be the absolute next logical step for someone wanting to go deeper. They are not just related terms; they are what you would need to understand next to truly grasp '{word}'. Think decomposition (what it's made of) or process (how it works).
    * Wrap all sub-topics in <click>tags</click>. If a fundamental formula is the best explanation, use LaTeX (e.g., <click>$E=mc^2$</click>).

**Example for 'API':**
An API (Application Programming Interface) is like a menu in a restaurant that allows different software programs to <click>request information</click> from each other. This is fundamentally how your weather app gets <click>forecast data</col> from a weather service, or how a travel site displays flights from various <click>airline systems</click>.

**Rules:**
- Your entire response MUST be only the two sentences. No headers, no greetings, no explanations of your instructions.
- Language Mandate: You MUST generate all user-facing text in the following language code: '{language}'. Do not use English unless the code is 'en'.

Nonce: {nonce}
"""
    else:
        # This is the prompt for a subsequent topic in an existing learning path.
        context_string = ", ".join(streak_context)
        # The last topic is the most immediate context.
        previous_topic = streak_context[-1]
        all_relevant_words_for_reiteration_check = [word] + streak_context
        reiteration_check_string = ", ".join(all_relevant_words_for_reiteration_check)
        
        prompt = f"""You are a Learning Navigator. Your user is on a journey of discovery and has just learned about '{previous_topic}' after starting with '{context_string}'. Now they want to understand '{word}'. Your task is to seamlessly connect the new topic to the old one.

Instructions:
1.  **Craft a Two-Sentence Explanation:**
    * **Sentence 1: How does this connect?** Explain what '{word}' is by explicitly showing how it builds upon, is a part of, or is the next logical concept after '{previous_topic}'.
    * **Sentence 2: What new understanding does this unlock?** Describe the new capability or the deeper layer of understanding that learning '{word}' now provides in their journey.
2.  **Select "Deeper Dive" Sub-topics:**
    * Within your explanation, embed a few (2-4) sub-topics that are the *next logical questions* or *deeper components* raised by your explanation.
    * These sub-topics must continue the learning path. They cannot be a reiteration of any term in '{reiteration_check_string}'.
    * Wrap all sub-topics in <click>tags</click>. Use LaTeX for essential formulas (e.g., <click>$y=mx+c$</click>).

**Example Context:** The user just learned about 'API' and now clicked on 'request information'.
**Your Task:** Define 'request information'.

**Example Output:**
In the context of an API, a <click>data request</click> is a structured message sent to a server, often using a protocol like <click>HTTP</click>. This is the action that actually 'asks the question', allowing an application to retrieve specific details like current temperature or available flight times, which are then delivered in a <click>formatted response</click> like JSON.

**Rules:**
- Your entire response MUST be only the two sentences. No headers, no greetings, no explanations of your instructions.
- Language Mandate: You MUST generate all user-facing text in the following language code: '{language}'. Do not use English unless the code is 'en'.

Nonce: {nonce}
"""

    try:
        # Step 1: Generate the text explanation
        # Assuming gemini_model is your generative model client
        response = gemini_model.generate_content(prompt)
        explanation_text = response.text.strip()
        
        # Step 2: Get image URLs for the topic
        image_urls = get_image_urls_for_topic(word)

        # --- Step 3: Get the new Agentic Suggestions ---
        # This function can now be more effective because the explanation is more practical
        suggestions = generate_agentic_suggestions(word, language, explanation_text)

        # Step 4: Return a dictionary containing all parts
        return {
            "explanation": explanation_text,
            "image_urls": image_urls,
            "suggestions": suggestions
        }
        
    except Exception as e:
        logging.error(f"Error in generate_explanation for word '{word}': {e}")
        # Return a valid structure even on error
        return {
            "explanation": f"Sorry, an error occurred while explaining '{word}'.",
            "image_urls": [],
            "suggestions": []
        }

def generate_quiz_from_text(word: str, explanation_text: str, streak_context: list = None, language: str = 'en', nonce: float = 0.0):
    """
    Generates a multiple-choice quiz question based on provided text.
    """
    context_hint_for_quiz = ""
    if streak_context:
        context_hint_for_quiz = f" The learning path so far included: {', '.join(streak_context)}."

    # UPDATED: The prompt now has a fallback instruction.
    prompt = f"""Based on the following explanation text for the term '{word}', generate a set of exactly 1 distinct multiple-choice quiz questions. The questions should test understanding of the key concepts presented in this specific text.{context_hint_for_quiz}

Explanation Text:
\"\"\"{explanation_text}\"\"\"

Language Mandate: You MUST generate the entire quiz (question, all options, and the explanation text) in the following language code: '{language}'. Do not use English unless the language code is 'en'.

For each question, strictly follow this exact format, including newlines:
**Question [Number]:** [Your Question Text Here]
A) [Option A Text]
B) [Option B Text]
C) [Option C Text]
D) [Option D Text]
Correct Answer: [Single Letter A, B, C, or D]
Explanation: [Optional: A brief explanation for the correct answer or why other options are incorrect]

CRITICAL: If the provided Explanation Text is too short, simple, or otherwise unsuitable for creating a meaningful, high-quality quiz question, you MUST respond with only the following exact text and nothing else:
---NO_QUIZ_POSSIBLE---

Ensure option keys are unique. Separate each complete question block with '---QUIZ_SEPARATOR---'.
Nonce: {nonce}
"""
    
    try:
        logging.warning(f"QUIZ PROMPT SENT TO AI: {prompt}")
        
        response = gemini_model.generate_content(prompt)
        llm_output_text = response.text.strip()
        
        # NEW: Check for the fallback response from the AI
        if "---NO_QUIZ_POSSIBLE---" in llm_output_text:
            logging.warning(f"AI determined no quiz was possible for word '{word}'.")
            return [] # Return an empty list, which is a stable response

        quiz_questions_array = [q.strip() for q in llm_output_text.split('---QUIZ_SEPARATOR---') if q.strip()]
        if not quiz_questions_array and llm_output_text:
            quiz_questions_array = [llm_output_text]
            
        return quiz_questions_array
    except Exception as e:
        logging.error(f"Error in generate_quiz_from_text for word '{word}': {e}")
        raise