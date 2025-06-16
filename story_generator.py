# story_generator.py

import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import logging
import json

# MODIFIED: New prompt instructs the AI to return simple, delimited text, not a complex JSON object.
# This makes the AI's job easier and prevents syntax errors.
BASE_PROMPT = """
You are 'Tiny Tutor,' an expert AI educator creating content for a learning game.
Your response MUST be plain text, with each part separated by the exact delimiter "|||TTPART|||".

**CRITICAL RULE:** Do NOT output a JSON object. Output ONLY the raw text content for each part in the specified order. You must handle all text, especially with apostrophes or special characters, as plain text.

**Response Structure (Use this exact order and delimiter):**
1.  **Feedback Text:** (e.g., "Correct!", "Not quite.", or "N/A" if it's the first turn)
2.  **Dialogue Text:** (The main dialogue for this turn. NEVER leave this blank.)
3.  **Image Prompt Text:** (A single, descriptive prompt for an image)
4.  **Interaction Type:** (Must be one of: "Text-based Button Selection", "Multi-Select Image Game")
5.  **Options Data:** (A list of options, each on a new line, formatted as: `DisplayText;;;LeadsToValue;;;IsCorrectValue`)
    * `IsCorrectValue` should be `true` or `false`.

---
**Example Output for a Question Turn (Language: fr):**
N/A|||TTPART|||Maintenant, une petite question pour voir si vous avez suivi. Qu'est-ce qui est essentiel pour la photosynthèse ?|||TTPART|||Photorealistic image of a sunbeam shining on a lush, green leaf, highlighting its veins.|||TTPART|||Text-based Button Selection|||TTPART|||Lumière du soleil;;;Correct;;;false
L'eau;;;Incorrect;;;false
La lune;;;Incorrect;;;false
La terre;;;Incorrect;;;false

---
**Core State Machine (Follow this strictly based on `last_choice_leads_to`):**
* If `last_choice_leads_to` is **null** -> Generate a **WELCOME** turn.
* If `last_choice_leads_to` is **'begin_explanation'** -> Generate an **EXPLANATION** turn.
* If `last_choice_leads_to` is **'ask_question'** -> Generate a **QUESTION** or **GAME** turn.
* If `last_choice_leads_to` is **'Correct'** or **'Incorrect'** -> Generate a **FEEDBACK** turn. The dialogue should contain the feedback (e.g., "Correct!").
* If `last_choice_leads_to` is **'explain_answer'** -> Generate an **EXPLAIN_ANSWER** turn.
* If `last_choice_leads_to` is **'request_summary'** -> Generate a **SUMMARY** turn.

**Universal Principles:**
1.  **Language Mandate:** You MUST generate all user-facing text in the language code: '{language}'.
2.  **No Loops or Repetition:** Review the history. Do not repeat content or get stuck in a loop. Always progress the conversation.
"""

# This model instance is loaded once and reused, which is efficient.
gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')

def generate_story_node(topic: str, history: list, last_choice_leads_to: str, language: str = 'en'):
    """
    Generates a single story node by calling the Gemini API and reliably parsing its text response.
    """
    history_str = json.dumps(history, indent=2)
    
    prompt_to_send = (
        f"{BASE_PROMPT.format(topic=topic, language=language)}\n\n"
        f"--- YOUR CURRENT TASK ---\n"
        f"**Topic:** {topic}\n"
        f"**Conversation History:**\n{history_str}\n"
        f"**User's Last Choice leads_to:** '{last_choice_leads_to}'\n\n"
        f"Strictly follow all rules to generate the raw text response."
    )

    response_text = "" # Initialize to ensure it exists for logging
    try:
        safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }
        
        # We now ask for plain text, which is much more reliable than asking for JSON.
        response = gemini_model.generate_content(
            prompt_to_send,
            safety_settings=safety_settings
        )
        response_text = response.text

        if not response_text:
            raise ValueError("AI returned an empty response.")
        
        # MODIFIED: Parse the AI's simple text response and build the JSON object ourselves.
        parts = response_text.split('|||TTPART|||')
        if len(parts) < 5:
            logging.error(f"AI response did not have 5 parts: {response_text}")
            raise ValueError("AI returned a malformed text structure.")

        feedback_text = parts[0].strip()
        dialogue_text = parts[1].strip()
        image_prompt = parts[2].strip()
        interaction_type = parts[3].strip()
        options_raw = parts[4].strip().split('\n')

        # Add validation to prevent blank dialogues from corrupting the history
        if not dialogue_text or len(dialogue_text) < 3:
            raise ValueError("AI generated a blank or invalid dialogue.")

        options_list = []
        for opt_line in options_raw:
            if not opt_line: continue
            opt_parts = opt_line.split(';;;')
            if len(opt_parts) >= 2:
                option = {
                    "text": opt_parts[0].strip(),
                    "leads_to": opt_parts[1].strip(),
                    "is_correct": len(opt_parts) > 2 and opt_parts[2].strip().lower() == 'true'
                }
                options_list.append(option)
        
        # Construct the final JSON object that the frontend expects.
        parsed_node = {
            "feedback_on_previous_answer": feedback_text if feedback_text != "N/A" else "",
            "dialogue": dialogue_text,
            "image_prompts": [image_prompt],
            "interaction": {
                "type": interaction_type,
                "options": options_list
            }
        }
        return parsed_node

    except Exception as e:
        # This will now log the exact text the AI sent back, which is invaluable for debugging.
        logging.error(f"Error in story_generator: {e}\nFull AI Response was:\n---\n{response_text}\n---")
        raise ValueError(f"AI returned unreadable data. Details: {e}")

