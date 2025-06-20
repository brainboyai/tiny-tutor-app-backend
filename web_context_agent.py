import google.generativeai as genai
import json
import logging
import os
import requests

def _perform_google_search(query: str):
    """Helper function to call the Google Custom Search API."""
    api_key = os.getenv("GOOGLE_SEARCH_API_KEY")
    search_engine_id = os.getenv("SEARCH_ENGINE_ID")
    
    if not api_key or not search_engine_id:
        logging.error("GOOGLE_SEARCH_API_KEY or SEARCH_ENGINE_ID are not set in the environment.")
        return []

    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        'key': api_key,
        'cx': search_engine_id,
        'q': query,
        'num': 8
    }
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        search_results = response.json()
        return [item['link'] for item in search_results.get('items', [])]
    except requests.exceptions.RequestException as e:
        logging.error(f"Google Search API request failed: {e}")
        return []

def get_web_context(topic: str, model: genai.GenerativeModel):
    """
    Analyzes a topic, generates a search query, executes it via the official API,
    and returns a structured list of the best web links.
    """
    query_generation_prompt = f"""
    You are an expert search query generator. Your task is to analyze the user's topic, "{topic}", and generate a single, optimal Google search query string to find the most relevant and diverse content. The query should aim to find an official source, a guide/tutorial, and a video.
    Return your answer as a single, raw, minified JSON object with a single key "query".
    Example for topic "Photosynthesis": {{"query": "photosynthesis process for kids explained youtube official biology site"}}
    """
    try:
        query_response = model.generate_content(query_generation_prompt)
        queries_dict = json.loads(query_response.text.strip().replace('```json', '').replace('```', ''))
        query = queries_dict.get("query", f"{topic} official site and youtube guide")
    except (json.JSONDecodeError, ValueError, AttributeError):
        query = f"{topic} official site and youtube guide"
    
    logging.warning(f"AGENT LOG: Using query for '{topic}': '{query}'")
    
    # This now correctly calls our helper function that uses the official API
    search_results_urls = _perform_google_search(query)
    
    if not search_results_urls:
        return []

    analysis_prompt = f"""
    You are an expert content curator. Based on the original topic "{topic}" and the following list of URLs, select the best link for each category: 'info', 'read', and 'watch'.
    Return a single, raw, minified JSON object: a list of up to three dictionaries, each with "type", "title", "snippet", and "url" keys. Create a concise title and a helpful one-sentence snippet for each.
    SEARCH RESULT URLs: {json.dumps(search_results_urls)}
    """
    try:
        analysis_response = model.generate_content(analysis_prompt)
        final_links = json.loads(analysis_response.text.strip().replace('```json', '').replace('```', ''))
    except (json.JSONDecodeError, ValueError, AttributeError):
        final_links = []
        
    return final_links
