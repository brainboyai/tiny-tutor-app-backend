import google.generativeai as genai
import json
import logging
import time
from googlesearch import search

def find_topic_image(topic: str):
    """
    Performs a dedicated Google Image search to find a single,
    high-quality, relevant image URL for a given topic.
    """
    try:
        # A targeted query for a high-quality, relevant image
        image_query = f"{topic} high resolution photo"
        logging.warning(f"AGENT: Searching for image with query: '{image_query}'")
        
        # We'll take the first result from the search
        results = [url for url in search(image_query, num_results=1, sleep_interval=1)]
        
        if results:
            logging.warning(f"AGENT: Found image for '{topic}': {results[0]}")
            return results[0]
            
    except Exception as e:
        logging.error(f"AGENT: Image search failed for topic '{topic}': {e}")
    
    return None

def get_web_context(topic: str, model: genai.GenerativeModel):
    """
    Analyzes a topic, generates search queries, executes them, and returns a structured
    list of the best web links, with detailed logging.
    """
    
    # --- Step 1: Generate optimal search queries for the given topic ---
    query_generation_prompt = f"""
    You are an expert search query generator. Your task is to analyze the user's topic, "{topic}", and generate a list of 3 optimal Google search queries to find relevant content covering: an official source, a guide/tutorial, and a video.
    Return your answer as a single, raw, minified JSON object with a single key "queries".
    """
    try:
        query_response = model.generate_content(query_generation_prompt)
        clean_response = query_response.text.strip().replace('```json', '').replace('```', '')
        queries_dict = json.loads(clean_response)
        queries = queries_dict.get("queries", [])
        if not queries:
            raise ValueError("Query generation failed.")
        # --- NEW: Logging generated queries ---
        logging.warning(f"AGENT LOG: Generated queries for '{topic}': {queries}")

    except (json.JSONDecodeError, ValueError) as e:
        logging.warning(f"Could not parse query generation response: {e}. Using fallback queries.")
        queries = [f"what is {topic}", f"{topic} guide", f"{topic} youtube"]
        logging.warning(f"AGENT LOG: Using fallback queries for '{topic}': {queries}")

    # --- Step 2: Execute each search query individually ---
    search_results_urls = {}
    
    try:
        for q in queries:
            results = [url for url in search(q, num_results=3)]
            search_results_urls[q] = results
            time.sleep(2)
        # --- NEW: Logging fetched URLs ---
        logging.warning(f"AGENT LOG: Fetched URLs for '{topic}': {json.dumps(search_results_urls, indent=2)}")

    except Exception as e:
        logging.error(f"Googlesearch library failed: {e}")
        return []

    # --- Step 3: Analyze the URLs to select the best link for each category ---
    if not search_results_urls:
        return []

    analysis_prompt = f"""
    You are an expert content curator. Based on the original topic "{topic}" and the following URLs, select the best link for each category: 'info', 'read', and 'watch'.
    Return a single, raw, minified JSON object: a list of exactly three dictionaries, each with "type", "title", "snippet", and "url" keys. Create a concise title and a helpful one-sentence snippet for each.
    SEARCH RESULT URLs: {json.dumps(search_results_urls)}
    """
    try:
        analysis_response = model.generate_content(analysis_prompt)
        clean_analysis_response = analysis_response.text.strip().replace('```json', '').replace('```', '')
        final_links = json.loads(clean_analysis_response)
        # --- NEW: Logging the final selected links ---
        logging.warning(f"AGENT LOG: Final selected links for '{topic}': {json.dumps(final_links, indent=2)}")

    except (json.JSONDecodeError, ValueError) as e:
        logging.error(f"Could not parse analysis response: {e}. Cannot provide web context.")
        final_links = []
        
    return final_links