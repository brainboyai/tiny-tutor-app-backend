import google.generativeai as genai
import json
import logging
import time
from googlesearch import search

def get_web_context(topic: str, model: genai.GenerativeModel):
    """
    Analyzes a topic, generates a single optimal search query, executes it,
    and returns a structured list of the best web links.
    """
    
    # --- Step 1: Generate ONE optimal search query for the given topic ---
    query_generation_prompt = f"""
    You are an expert search query generator. Your task is to analyze the user's topic, "{topic}", and generate a single, optimal Google search query string to find the most relevant and diverse content. The query should aim to find an official source, a guide/tutorial, and a video.
    Return your answer as a single, raw, minified JSON object with a single key "query".
    Example for topic "Photosynthesis": {{"query": "photosynthesis process for kids explained youtube official biology site"}}
    """
    try:
        query_response = model.generate_content(query_generation_prompt)
        clean_response = query_response.text.strip().replace('```json', '').replace('```', '')
        queries_dict = json.loads(clean_response)
        query = queries_dict.get("query")
        if not query:
            raise ValueError("Query generation failed.")
        logging.warning(f"AGENT LOG: Generated single query for '{topic}': \"{query}\"")

    except (json.JSONDecodeError, ValueError) as e:
        logging.warning(f"Could not parse query generation response: {e}. Using fallback query.")
        query = f"{topic} official site and youtube guide"
        logging.warning(f"AGENT LOG: Using fallback query for '{topic}': \"{query}\"")

    # --- Step 2: Execute the single search query ---
    search_results_urls = []
    
    try:
        # Execute a single search with more results, which is more efficient
        search_results_urls = [url for url in search(query, num_results=8)]
        logging.warning(f"AGENT LOG: Fetched URLs for '{topic}': {json.dumps(search_results_urls, indent=2)}")

    except Exception as e:
        logging.error(f"Googlesearch library failed for query '{query}': {e}")
        return []

    # --- Step 3: Analyze the URLs to select the best link for each category ---
    if not search_results_urls:
        return []

    # The analysis prompt is updated to expect a simple list of URLs
    analysis_prompt = f"""
    You are an expert content curator. Based on the original topic "{topic}" and the following list of URLs, select the best link for each category: 'info', 'read', and 'watch'.
    Return a single, raw, minified JSON object: a list of up to three dictionaries, each with "type", "title", "snippet", and "url" keys. Create a concise title and a helpful one-sentence snippet for each.
    SEARCH RESULT URLs: {json.dumps(search_results_urls)}
    """
    try:
        analysis_response = model.generate_content(analysis_prompt)
        clean_analysis_response = analysis_response.text.strip().replace('```json', '').replace('```', '')
        final_links = json.loads(clean_analysis_response)
        logging.warning(f"AGENT LOG: Final selected links for '{topic}': {json.dumps(final_links, indent=2)}")

    except (json.JSONDecodeError, ValueError) as e:
        logging.error(f"Could not parse analysis response: {e}. Cannot provide web context.")
        final_links = []
        
    return final_links