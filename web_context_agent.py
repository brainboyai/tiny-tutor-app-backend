import google.generativeai as genai
import json
import logging
from google_search import search

def get_web_context(topic: str, model: genai.GenerativeModel):
    """
    Analyzes a topic, generates search queries, executes them, analyzes the results,
    and returns a structured list of the best web links.
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
        # First LLM call to get the best search terms
        query_response = model.generate_content(query_generation_prompt)
        queries_dict = json.loads(query_response.text)
        queries = queries_dict.get("queries", [])
        if not queries:
            raise ValueError("Query generation failed.")
    except (json.JSONDecodeError, ValueError) as e:
        logging.warning(f"Could not parse query generation response: {e}. Using fallback queries.")
        queries = [f"what is {topic}", f"{topic} guide", f"{topic} youtube"]

    # --- Step 2: Execute the search queries ---
    try:
        search_results_data = search(queries=queries)
    except Exception as e:
        logging.error(f"Google Search tool failed: {e}")
        return [] # Return empty if the search tool itself fails

    # --- Step 3: Analyze search results to select the best link for each category ---
    analysis_prompt = f"""
    You are an expert content curator. Based on the original topic "{topic}" and the following Google search results, your task is to select the single best link for each of these three categories: 'info', 'read', and 'watch'.

    - 'info': The best official website, documentation, or encyclopedic page.
    - 'read': The best article, guide, or in-depth tutorial.
    - 'watch': The best introductory video.

    Return your answer as a single, raw, minified JSON object which is a list of exactly three dictionaries. Each dictionary must have "type", "title", "snippet", and "url" keys.
    Example: [{{"type":"info","title":"React","url":"https://react.dev/","snippet":"The official documentation for React..."}}, ...]
    
    SEARCH RESULTS:
    {json.dumps(search_results_data)}
    """
    try:
        # Second LLM call to analyze and select the best results
        analysis_response = model.generate_content(analysis_prompt)
        final_links = json.loads(analysis_response.text)
    except (json.JSONDecodeError, ValueError) as e:
        logging.error(f"Could not parse analysis response: {e}. Cannot provide web context.")
        final_links = []
        
    return final_links