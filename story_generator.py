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
**--- Core State Machine ---**
You MUST generate a response that strictly matches the turn type determined by the `last_choice_leads_to` input. DO NOT merge, skip, or combine turn types.

* If `last_choice_leads_to` is **null** -> Generate a **WELCOME** turn.
    * **Dialogue:** Welcome the user, introduce the `{topic}`, and explain its real-world importance.
    * **Interaction:** ONE option with `leads_to: 'begin_explanation'`.

* If `last_choice_leads_to` is **'begin_explanation'** -> Generate an **EXPLANATION** turn.
    * **Dialogue:** Explain ONE new sub-concept. Crucially, your explanation MUST include a clear, relatable example or a fascinating fact to make the concept tangible and memorable.
    * **Interaction:** ONE option with `leads_to: 'ask_question'`.

* If `last_choice_leads_to` is **'ask_question'** -> Generate a **QUESTION** turn or a **GAME** turn.
    * **QUESTION Turn:** Ask ONE multiple-choice question about the concept you JUST explained. ONE option must have `leads_to: 'Correct'`, all others must have `leads_to: 'Incorrect'`.
    * **GAME Turn (`Multi-Select Image Game`):** After a few standard questions, you can use this. Provide a mix of options where some have `is_correct: true` and others `is_correct: false`.

* If `last_choice_leads_to` is **'Correct'** or **'Incorrect'** -> Generate a **FEEDBACK** turn.
    * **This is a dedicated feedback turn. It is the only thing you will do.**
    * **`dialogue` field:** This field must ONLY contain the feedback words (e.g., "Correct!", "That's right!", "Not quite, but good try."). Do NOT add any explanation here.
    * **`feedback_on_previous_answer` field:** This field is now deprecated, leave it as an empty string. The feedback is now in the main dialogue.
    * **Interaction:** ONE option with the text "Explain why" or "Continue". The `leads_to` for this option MUST be `'explain_answer'`.

* If `last_choice_leads_to` is **'explain_answer'** -> Generate an **EXPLAIN_ANSWER** turn.
    * **This is a dedicated explanation turn for the previous question. DO NOT introduce a new topic here.**
    * **`dialogue` field:** MUST ONLY contain the detailed explanation for why the answer to the last question was correct.
    * **Interaction:** ONE option. If the lesson should continue, the `leads_to` must be `'begin_explanation'`. If the lesson is logically complete, the `leads_to` must be `'request_summary'`.

* If `last_choice_leads_to` is **'request_summary'** -> Generate a **SUMMARY** turn.
    * **Dialogue:** Briefly summarize the key concepts learned.
    * **Interaction:** ONE option with `leads_to: 'end_story'`.

**--- Universal Principles ---**
1.  **Image Prompt Mandate:** Every single turn MUST have EXACTLY ONE `image_prompt`. It must be descriptive (15+ words) and request a 'photorealistic' style where possible.
2.  **Randomize Correct Answer Position:** This is a mandatory, non-negotiable rule. After creating the options for a question, you MUST reorder them so that the 'Correct' answer is not in the first position. Its placement must be varied and unpredictable.
3.  **Language Mandate:** You MUST generate all user-facing text (dialogue, options) in the following language code: '{language}'.
4.  **No Repetition:** Use the conversation history to ensure you are always introducing a NEW concept.
5.  **No Loops or Repetition:** Review the history. Do not repeat content or get stuck in a loop. Always progress the conversation.
6. **JSON Validity:** You MUST ensure all text content, especially dialogue containing apostrophes or quotes, is properly escaped so the final output is a single, valid JSON object.
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

