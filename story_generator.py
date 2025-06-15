# story_generator.py

import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import logging
import json

# The prompt for generating a single turn of the story remains here.
BASE_PROMPT = """
You are 'Tiny Tutor,' an expert AI educator creating a JSON object for a single turn in a learning game. Your target audience is a 6th-grade science student. Your tone is exploratory and curious.

**--- CRITICAL RULE FOR JSON OUTPUT ---**
You MUST ensure the final output is a single, valid JSON object. For all string values in the JSON (like in the "dialogue" or "text" fields), you MUST use double quotes (`"`). If any text inside a string value requires a double quote character, you MUST escape it with a backslash (`\\"`). Adhering to this is mandatory.

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
5.  **JSON Validity:** You MUST ensure all text content, especially dialogue containing apostrophes or quotes, is properly escaped so the final output is a single, valid JSON object.
"""

# The expected JSON structure for the AI's response is defined here.
STORY_NODE_SCHEMA = {
    "type": "object",
    "properties": {
        "feedback_on_previous_answer": {"type": "string", "description": "DEPRECATED. Leave as an empty string. Feedback is now in the main dialogue for FEEDBACK turns."},
        "dialogue": {"type": "string", "description": "The AI teacher's main dialogue for this turn."},
        "image_prompts": {"type": "array", "items": {"type": "string"}, "description": "A list containing exactly one prompt for an image to display. For game turns, each option has its own prompt."},
        "interaction": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["Text-based Button Selection", "Image Selection", "Multi-Select Image Game"], "description": "The type of interaction required."},
                "options": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "leads_to": {"type": "string"},
                            "is_correct": {"type": "boolean", "description": "Used only for Multi-Select Image Game to mark correct answers."}
                        },
                        "required": ["text", "leads_to"]
                    }
                }
            },
            "required": ["type", "options"]
        }
    },
    "required": ["feedback_on_previous_answer", "dialogue", "image_prompts", "interaction"]
}


def generate_story_node(topic: str, history: list, last_choice_leads_to: str, language: str = 'en'):
    """
    Generates a single story node by calling the Gemini API.

    Args:
        language (str, optional): The language for the response. Defaults to 'en'
        topic: The overall topic of the story.
        history: The list of previous conversation turns.
        last_choice_leads_to: The 'leads_to' value from the user's last choice.

    Returns:
        A dictionary representing the parsed JSON of the story node.
    
    Raises:
        ValueError: If the API response is blocked or returns unreadable JSON.
        Exception: For other, more general API or network errors.
    """
    history_str = json.dumps(history, indent=2)
    
    prompt_to_send = (
        f"{BASE_PROMPT.format(topic=topic, language=language)}\n\n"
        f"--- YOUR CURRENT TASK ---\n"
        f"**Topic:** {topic}\n"
        f"**Conversation History:**\n{history_str}\n"
        f"**User's Last Choice leads_to:** '{last_choice_leads_to}'\n\n"
        f"Strictly follow the State Machine rules and Universal Principles to generate the correct JSON object for this state."
    )

    try:
        # **FIX:** Instantiate the GenerativeModel *before* calling generate_content.
        gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')
        
        generation_config = genai.types.GenerationConfig(response_mime_type="application/json", response_schema=STORY_NODE_SCHEMA)
        safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }
        
        # Now, call the method on the 'gemini_model' object.
        response = gemini_model.generate_content(
            prompt_to_send,
            generation_config=generation_config,
            safety_settings=safety_settings
        )

        if hasattr(response, 'prompt_feedback') and response.prompt_feedback.block_reason:
             raise ValueError(f"Prompt blocked for safety reasons: {response.prompt_feedback.block_reason}")

        parsed_node = json.loads(response.text)
        return parsed_node

    except json.JSONDecodeError as e:
        logging.error(f"JSONDecodeError in story_generator: Could not parse AI response. Error: {e}")
        raise ValueError("AI returned unreadable JSON format.")
    except Exception as e:
        logging.error(f"A general error occurred in story_generator: {e}")
        raise

