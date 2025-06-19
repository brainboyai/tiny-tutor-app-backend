import google.generativeai as genai
import json
import logging
import time # Import the standard time library
# Use the public 'googlesearch-python' library
from googlesearch import search

def get_web_context(topic: str, model: genai.GenerativeModel):
    """
    Analyzes a topic, generates search queries, executes them using the googlesearch library,
    and then analyzes the resulting URLs to return a structured list of the best links.
    """
    
    # --- Step 1: Generate optimal search queries for the given topic ---
    query_generation_prompt = f"""
    You are an expert search query generator. Your task is to analyze the user's topic, "{topic}", and generate a list of 3 optimal Google search queries to find the most relevant content for a learner. The queries should cover these categories:
    1. A primary informational or official source (e.g., official website, documentation).
    2. A guide or tutorial for beginners.
    3. An engaging video introduction (e.g., YouTube).

    Return your answer as a single, raw, minified JSON object with a single key "queries" which contains a list of these three search strings. Do not use markdown formatting.
    Example for topic "React.js": {{"queries":["what is react js","react js tutorial for beginners","react js crash course youtube"]}}
    """
    try:
        query_response = model.generate_content(query_generation_prompt)
        clean_response = query_response.text.strip().replace('```json', '').replace('```', '')
        queries_dict = json.loads(clean_response)
        queries = queries_dict.get("queries", [])
        if not queries:
            raise ValueError("Query generation failed.")
    except (json.JSONDecodeError, ValueError) as e:
        logging.warning(f"Could not parse query generation response: {e}. Using fallback queries.")
        queries = [f"what is {topic}", f"{topic} guide", f"{topic} youtube"]

    # --- Step 2: Execute each search query individually ---
    search_results_urls = {}
    
    try:
        for q in queries:
            logging.info(f"Executing search for query: {q}")
            # CORRECTED: Using the most basic call to search()
            # Taking the top 3 results for each query.
            results = [url for url in search(q, num_results=3)]
            search_results_urls[q] = results
            
            # Manually pause for 2 seconds to avoid rate-limiting.
            time.sleep(2)

    except Exception as e:
        logging.error(f"Googlesearch library failed: {e}")
        return []

    # --- Step 3: Analyze the URLs to select the best link for each category ---
    if not search_results_urls:
        return []

    analysis_prompt = f"""
    You are an expert content curator. Based on the original topic "{topic}" and the following list of URLs (grouped by search query), your task is to select the single best link for each of these three categories: 'info', 'read', and 'watch'.

    - 'info': The best official website, documentation, or encyclopedic page.
    - 'read': The best article, guide, or in-depth tutorial.
    - 'watch': The best introductory video (must be a YouTube link).

    Infer the best link for each category from the URLs provided. Return your answer as a single, raw, minified JSON object which is a list of exactly three dictionaries. Each dictionary must have "type", "title", "snippet", and "url" keys. Create a concise title and a helpful one-sentence snippet for each selected URL.
    
    Example response format: [{{"type":"info","title":"React Official Site","url":"https://react.dev/","snippet":"The official documentation and homepage for React."}}, ...]
    
    SEARCH RESULT URLs:
    {json.dumps(search_results_urls)}
    """
    try:
        # Second LLM call to analyze and select the best results
        analysis_response = model.generate_content(analysis_prompt)
        clean_analysis_response = analysis_response.text.strip().replace('```json', '').replace('```', '')
        final_links = json.loads(clean_analysis_response)
    except (json.JSONDecodeError, ValueError) as e:
        logging.error(f"Could not parse analysis response: {e}. Cannot provide web context.")
        final_links = []
        
    return final_links
