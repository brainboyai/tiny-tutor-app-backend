# explore_generator.py

import google.generativeai as genai
import logging

def generate_explanation(word: str, streak_context: list = None, language: str = 'en'):
    """
    Generates a simple or context-aware explanation for a word.

    Args:
        word (str): The word or concept to explain.
        streak_context (list, optional): A list of previously explored words in the streak.
                                          If provided, the explanation will be contextual. Defaults to None.
        language (str, optional): The language for the response. Defaults to 'en'
        
    Returns:
        str: The generated explanation text.
    
    Raises:
        Exception: If the Gemini API call fails.
    """
    prompt = ""
    if not streak_context:
        # This is the prompt for a new word or the first word in a streak.
        prompt = f"""Your task is to define '{word}', acting as a knowledgeable guide introducing a foundational concept to a curious beginner.
Instructions: Define '{word}' in exactly two sentences using the simplest, most basic, and direct language suitable for a complete beginner with no prior knowledge; focus on its core, fundamental aspects. Within these sentences, embed the maximum number of distinct, foundational sub-topics (key terms, core concepts, related ideas) that are crucial not only for grasping '{word}' but also for sparking further inquiry and naturally leading towards a deeper exploration—think of these as initial pathways into a fascinating subject. These sub-topics must not be mere synonyms or rephrasing of '{word}'. If '{word}' involves mathematics, physics, chemistry, or similar fields, embed any critical fundamental formulas or equations (using LaTeX, e.g., $E=mc^2$) as sub-topics. Wrap all sub-topics (textual, formulas, equations) in <click>tags</click> (e.g., <click>energy conversion</click>, <click>$A=\pi r^2$</click>). Your response must consist strictly of the two definition sentences containing the embedded clickable sub-topics. Do not include any headers, introductory phrases, or these instructions in your output.
Example of the expected output format: Photosynthesis is a <click>biological process</click> in <click>plants</click> and other organisms converting <click>light energy</click> into <click>chemical energy</click>, often represented by <click>6CO_2+6H_2O+textLightrightarrowC_6H_12O_6+6O_2</click>. This process uses <click>carbon dioxide</click> and <click>water</click> to produce <click>glucose</click> (a <click>sugar</click>) and <click>oxygen</click>.
Language Mandate: You MUST generate all user-facing text in the following language code: '{language}'. Do not use English unless the code is 'en'.
Your response must consist strictly of the two definition sentences containing the embedded clickable sub-topics. Do not include any headers, introductory phrases, or these instructions in your output.

"""
    else:
        # This is the prompt for a subsequent word in an existing streak, requiring context.
        context_string = ", ".join(streak_context)
        all_relevant_words_for_reiteration_check = [word] + streak_context
        reiteration_check_string = ", ".join(all_relevant_words_for_reiteration_check)
        prompt = f"""Your task is to define '{word}', acting as a teacher guiding a student step-by-step down a 'rabbit hole' of knowledge. The student has already learned about the following concepts in this order: '{context_string}'.
Instructions: Define '{word}' in exactly two sentences using the simplest, most basic, and direct language suitable for a complete beginner. Your explanation must clearly show how '{word}' relates to, builds upon, or offers a new dimension to the established learning path of '{context_string}'. Focus on its core aspects as they specifically connect to this narrative of exploration. Within these sentences, embed the maximum number of distinct, foundational sub-topics (key terms, core concepts, related ideas). These sub-topics should be crucial for understanding '{word}' within this specific learning sequence and should themselves be chosen to intelligently suggest further avenues of exploration, continuing the streak of discovery. Crucially, these embedded sub-topics must not be a simple reiteration of any words found in '{reiteration_check_string}'. If '{word}' (when considered in the context of '{context_string}') involves mathematics, physics, chemistry, or similar fields, embed any critical fundamental formulas or equations (using LaTeX, e.g., $E=mc^2$) as sub-topics. Wrap all sub-topics (textual, formulas, equations) in <click>tags</click> (e.g., <click>relevant concept</click>, <click>$y=mx+c$</click>). Your response must consist strictly of the two definition sentences containing the embedded clickable sub-topics. Do not include any headers, introductory phrases, or these instructions in your output.
Example of the expected output format: Photosynthesis is a <click>biological process</click> in <click>plants</click> and other organisms converting <click>light energy</click> into <click>chemical energy</click>, often represented by <click>6CO2​+6H2​O+Light→C6​H12​O6​+6O2​</click>. This process uses <click>carbon dioxide</click> and <click>water</click> to produce <click>glucose</click> (a <click>sugar</click>) and <click>oxygen</click>.
Language Mandate: You MUST generate all user-facing text in the following language code: '{language}'. Do not use English unless the code is 'en'.
Your response must consist strictly of the two definition sentences containing the embedded clickable sub-topics. Do not include any headers, introductory phrases, or these instructions in your output.

"""
    try:
        gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')
        response = gemini_model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        logging.error(f"Error in generate_explanation for word '{word}': {e}")
        raise

def generate_quiz_from_text(word: str, explanation_text: str, streak_context: list = None, language: str = 'en'):
    """
    Generates a multiple-choice quiz question based on provided text.

    Args:
        word (str): The word the explanation is for.
        explanation_text (str): The text to base the quiz on.
        streak_context (list, optional): A list of previously explored words. Defaults to None.

    Returns:
        list: A list containing a single formatted quiz question string.
    
    Raises:
        Exception: If the Gemini API call fails.
    """
    context_hint_for_quiz = ""
    if streak_context:
        context_hint_for_quiz = f" The learning path so far included: {', '.join(streak_context)}."

    prompt = (
        f"Based on the following explanation text for the term '{word}', generate a set of exactly 1 distinct multiple-choice quiz questions. "
        f"The questions should test understanding of the key concepts presented in this specific text.{context_hint_for_quiz}\n\n"
        f"Explanation Text:\n\"\"\"{explanation_text}\"\"\"\n\n"
        f"Language Mandate: You MUST generate the entire quiz (question, options, explanation) in the following language code: '{language}'.\n\n"
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
    
    try:
        gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')
        response = gemini_model.generate_content(prompt)
        llm_output_text = response.text.strip()
        
        quiz_questions_array = [q.strip() for q in llm_output_text.split('---QUIZ_SEPARATOR---') if q.strip()]
        if not quiz_questions_array and llm_output_text:
            quiz_questions_array = [llm_output_text]
            
        return quiz_questions_array
    except Exception as e:
        logging.error(f"Error in generate_quiz_from_text for word '{word}': {e}")
        raise

