# explore_generator.py

import google.generativeai as genai
import logging
import re
from googlesearch import search # Make sure this import is here

# FIX: Load the model once when the module is first imported.
gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')

def get_image_urls_for_topic(topic: str, num_images: int = 2):
    """
    Performs a Google search to find relevant image URLs for a topic.
    """
    image_urls = []
    # Use a query that's more likely to return pages with direct image links
    query = f'"{topic}" high-quality illustration diagram photo'
    
    try:
        # We search for more results to increase the chance of finding usable images
        search_results = search(query, num_results=10, lang="en")
        
        for url in search_results:
            # A simple regex to check if the URL looks like a direct image link
            if re.search(r'\.(jpg|jpeg|png|webp|gif)$', url):
                image_urls.append(url)
                if len(image_urls) >= num_images:
                    break # Stop once we have enough images
                    
        logging.warning(f"Found {len(image_urls)} image URLs for topic '{topic}': {image_urls}")
        return image_urls
        
    except Exception as e:
        logging.error(f"Error while searching for images for topic '{topic}': {e}")
        return []

def generate_explanation(word: str, streak_context: list = None, language: str = 'en', nonce: float = 0.0):
    """
    Generates an explanation, finds related images, and returns them together.
    """
    prompt = ""
    # This is the prompt for a new word or the first word in a streak.
    if not streak_context:
        prompt = f"""Your task is to define '{word}', acting as a knowledgeable guide introducing a foundational concept to a curious beginner.
Instructions: Define '{word}' in exactly two sentences using the simplest, most basic, and direct language suitable for a complete beginner with no prior knowledge; focus on its core, fundamental aspects. Within these sentences, embed the maximum number of distinct, foundational sub-topics (key terms, core concepts, related ideas) that are crucial not only for grasping '{word}' but also for sparking further inquiry and naturally leading towards a deeper exploration—think of these as initial pathways into a fascinating subject. These sub-topics must not be mere synonyms or rephrasing of '{word}'. If '{word}' involves mathematics, physics, chemistry, or similar fields, embed any critical fundamental formulas or equations (using LaTeX, e.g., $E=mc^2$) as sub-topics. Wrap all sub-topics (textual, formulas, equations) in <click>tags</click> (e.g., <click>energy conversion</click>, <click>$A=\pi r^2$</click>). Your response must consist strictly of the two definition sentences containing the embedded clickable sub-topics. Do not include any headers, introductory phrases, or these instructions in your output.
Example of the expected output format: Photosynthesis is a <click>biological process</click> in <click>plants</click> and other organisms converting <click>light energy</click> into <click>chemical energy</click>, often represented by <click>6CO_2+6H_2O+textLightrightarrowC_6H_12O_6+6O_2</click>. This process uses <click>carbon dioxide</click> and <click>water</click> to produce <click>glucose</click> (a <click>sugar</click>) and <click>oxygen</click>.
Language Mandate: You MUST generate all user-facing text in the following language code: '{language}'. Do not use English unless the code is 'en'.
Your response must consist strictly of the two definition sentences containing the embedded clickable sub-topics. Do not include any headers, introductory phrases, or these instructions in your output.
prompt += f"\\nNonce: {nonce}"
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
prompt += f"\\nNonce: {nonce}"
"""

    try:
        # Step 1: Generate the text explanation
        response = gemini_model.generate_content(prompt)
        explanation_text = response.text.strip()
        
        # Step 2: Get image URLs for the topic
        image_urls = get_image_urls_for_topic(word)

        # Step 3: Return a dictionary containing both parts
        return {
            "explanation": explanation_text,
            "image_urls": image_urls
        }
        
    except Exception as e:
        logging.error(f"Error in generate_explanation for word '{word}': {e}")
        # Return a valid structure even on error
        return {
            "explanation": f"Sorry, an error occurred while explaining '{word}'.",
            "image_urls": []
        }