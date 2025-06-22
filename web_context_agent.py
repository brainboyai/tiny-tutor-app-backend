import google.generativeai as genai
import json
import logging
import os
import requests
from urllib.parse import quote_plus
from datetime import datetime, timedelta

# In web_context_agent.py, replace your get_routed_web_context function

def get_routed_web_context(query: str, model: genai.GenerativeModel):
    """
    Acts as an Intent-Based Router. It analyzes the user's query, determines the best API to call,
    fetches the data, and returns it in a standardized format.
    """
    
    try:
        intent, entity = _get_intent_from_query(query, model)
        logging.warning(f"AGENT LOG: Intent recognized for query '{query}' -> INTENT: {intent}, ENTITY: {entity}")
    except Exception as e:
        logging.error(f"Could not determine intent for query '{query}': {e}. Using fallback.")
        intent, entity = "FALLBACK_SEARCH", query

  # Replace your router function with this new version
def get_routed_web_context(query: str, model: genai.GenerativeModel):
    """
    Acts as an Intent-Based Router.
    [FINAL VERSION with Event Fallback]
    """
    try:
        intent, entity = _get_intent_from_query(query, model)
        logging.warning(f"AGENT LOG: Intent recognized for query '{query}' -> INTENT: {intent}, ENTITY: {entity}")
    except Exception as e:
        logging.error(f"Could not determine intent for query '{query}': {e}. Using fallback.")
        intent, entity = "FALLBACK_SEARCH", query

    if intent == "EVENTS":
        logging.warning(f"--- Routing to TICKETMASTER API for entity: {entity} ---")
        event_results = _call_ticketmaster_api(entity)
        # If the specific tool (Ticketmaster) returns results, use them.
        if event_results:
            return event_results
        # Otherwise, use the intelligent fallback search.
        else:
            logging.warning(f"--- Ticketmaster had no results. Using intelligent fallback search for events in {entity}. ---")
            return _perform_google_search(query, intent, entity)

    # --- The rest of the router logic remains the same ---
    elif intent == "NEWS":
        logging.warning(f"--- Routing to NEWS API for entity: {entity} ---")
        return _call_news_api(entity)
    elif intent == "VIDEO":
        logging.warning(f"--- Routing to YOUTUBE API for entity: {entity} ---")
        return _call_youtube_api(entity)
    elif intent == "KNOWLEDGE":
        logging.warning(f"--- Routing to WIKIPEDIA API for entity: {entity} ---")
        return _call_wikipedia_api(entity)
    elif intent == "FINANCE":
        logging.warning(f"--- Routing to ALPHA VANTAGE API for entity: {entity} ---")
        return _call_alphavantage_api(entity)
    elif intent == "RESTAURANTS":
        logging.warning(f"--- Routing to RESTAURANTS (using intelligent fallback search) for entity: {entity} ---")
        return _perform_google_search(query, intent, entity)
    elif intent == "TRAVEL_HOTELS":
        logging.warning(f"--- Routing to HOTELS API for entity: {entity} ---")
        return _call_hotels_api(entity)
    elif intent == "SHOPPING":
        logging.warning(f"--- Routing to SHOPPING (using intelligent fallback search) for entity: {entity} ---")
        return _perform_google_search(query, "SHOPPING", entity)
    else: 
        logging.warning(f"--- No specific tool found. Routing to INTELLIGENT FALLBACK for query: {query} ---")
        return _perform_google_search(query, intent, entity)

def _get_intent_from_query(query: str, model: genai.GenerativeModel):
    """
    Uses the LLM to classify the user's query into a specific intent category
    and extract the key entity for searching. [IMPROVED VERSION]
    """
    prompt = f"""
    You are a precise query analysis engine. Your task is to analyze the user's search query and classify it into one of the STRICT predefined categories. You must also extract the core search entity.

    **Instructions:**
    - Be very specific. If a query explicitly mentions 'hotels', 'stays', or 'accommodations', use 'TRAVEL_HOTELS'.
    - If a query uses broader travel terms like 'tourism packages', 'tours', or 'things to do', it is a general search and you MUST use 'FALLBACK_SEARCH'.
    - If using 'FALLBACK_SEARCH', the 'entity' should be the entire original query.

    **Available Categories:**
    - NEWS, VIDEO, KNOWLEDGE, EVENTS, FINANCE, RESTAURANTS, TRAVEL_HOTELS, SHOPPING, FALLBACK_SEARCH

    **Analyze the following user query:** "{query}"

    --- EXAMPLES OF NUANCE ---
    Query: "Hyderabad tourism packages"
    Output: {{"intent": "FALLBACK_SEARCH", "entity": "Hyderabad tourism packages"}}

    Query: "best hotels in Hyderabad"
    Output: {{"intent": "TRAVEL_HOTELS", "entity": "Hyderabad"}}

    Query: "things to do in Paris this weekend"
    Output: {{"intent": "FALLBACK_SEARCH", "entity": "things to do in Paris this weekend"}}

    Query: "concerts in Paris this weekend"
    Output: {{"intent": "EVENTS", "entity": "Paris this weekend"}}
    ---

    Return your response as a single, raw, minified JSON object with two keys: "intent" and "entity". Your response MUST be ONLY the JSON object and nothing else.
    """
    
    response = model.generate_content(prompt)
    # Adding a defensive check in case the model still returns a non-JSON response
    try:
        analysis = json.loads(response.text.strip())
        return analysis.get("intent"), analysis.get("entity")
    except json.JSONDecodeError:
        logging.error(f"Failed to decode JSON from intent recognition for query: '{query}'. Defaulting to fallback.")
        return "FALLBACK_SEARCH", query
    
# --- API Helper Functions ---

def _normalize_data(item_type, title, url, snippet, image=None):
    """A simple helper to create a standardized dictionary."""
    return {"type": item_type, "title": title, "url": url, "snippet": snippet, "image": image}

def _call_news_api(entity: str):
    api_key = os.getenv("NEWS_API_KEY")
    if not api_key: return []
    url = f"https://newsapi.org/v2/everything?q={quote_plus(entity)}&apiKey={api_key}&pageSize=5&sortBy=relevancy"
    try:
        response = requests.get(url)
        response.raise_for_status()
        articles = response.json().get('articles', [])
        normalized_results = [
            _normalize_data('News', a.get('title'), a.get('url'), a.get('description'), a.get('urlToImage'))
            for a in articles
        ]
        return normalized_results
    except Exception as e:
        logging.error(f"NewsAPI request failed for '{entity}': {e}")
        return []

def _call_youtube_api(entity: str):
    api_key = os.getenv("GOOGLE_SEARCH_API_KEY") # Uses your existing key
    if not api_key: return []
    url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={quote_plus(entity)}&type=video&key={api_key}&maxResults=5"
    try:
        response = requests.get(url)
        response.raise_for_status()
        videos = response.json().get('items', [])
        normalized_results = []
        for v in videos:
            if v.get('id', {}).get('videoId'): # Ensure it's a valid video item
                normalized_results.append(
                    _normalize_data('Video', v['snippet']['title'], f"https://www.youtube.com/watch?v={v['id']['videoId']}", v['snippet']['description'], v['snippet']['thumbnails']['high']['url'])
                )
        return normalized_results
    except Exception as e:
        logging.error(f"YouTube API request failed for '{entity}': {e}")
        return []

def _call_wikipedia_api(entity: str):
    url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={quote_plus(entity)}&format=json&srlimit=5"
    try:
        response = requests.get(url, headers={'User-Agent': 'TinyTutorApp/1.0'})
        response.raise_for_status()
        pages = response.json().get('query', {}).get('search', [])
        normalized_results = [
            _normalize_data('Knowledge', p['title'], f"http://en.wikipedia.org/?curid={p['pageid']}", p['snippet'].replace('<span class="searchmatch">', '').replace('</span>', ''))
            for p in pages
        ]
        return normalized_results
    except Exception as e:
        logging.error(f"Wikipedia API request failed for '{entity}': {e}")
        return []

# In web_context_agent.py, replace the existing function with this one

# Replace your Ticketmaster function with this cleaned-up version
def _call_ticketmaster_api(entity: str):
    """
    Calls the Ticketmaster API.
    [PRODUCTION VERSION]
    """
    api_key = os.getenv("TICKETMASTER_API_KEY")
    if not api_key: 
        logging.error("TICKETMASTER_API_KEY is not set.")
        return []

    url = f"https://app.ticketmaster.com/discovery/v2/events.json?apikey={api_key}&keyword={quote_plus(entity)}&size=5"
    try:
        logging.warning(f"--- Calling Ticketmaster API for entity: {entity} ---")
        response = requests.get(url, timeout=25)
        response.raise_for_status()

        # The raw response has been removed now that we know the issue
        events = response.json().get('_embedded', {}).get('events', [])
        
        logging.warning(f"--- Found {len(events)} events in Ticketmaster response. ---")
        if not events:
            return []

        normalized_results = []
        for event in events:
            image_url = next((img['url'] for img in event.get('images', []) if img.get('ratio') == '16_9'), None)
            snippet = f"Date: {event.get('dates', {}).get('start', {}).get('localDate', 'N/A')}"
            normalized_results.append(
                _normalize_data('Event', event.get('name'), event.get('url'), snippet, image_url)
            )
        return normalized_results
    except Exception as e:
        logging.error(f"Ticketmaster API request failed for '{entity}': {e}")
        return []
    
def _call_alphavantage_api(entity: str):
    api_key = os.getenv("ALPHAVANTAGE_API_KEY")
    if not api_key: return []
    url = f"https://www.alphavantage.co/query?function=SYMBOL_SEARCH&keywords={quote_plus(entity)}&apikey={api_key}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        matches = response.json().get('bestMatches', [])
        normalized_results = []
        for match in matches:
            symbol = match.get('1. symbol')
            name = match.get('2. name')
            snippet = f"Symbol: {symbol}, Type: {match.get('3. type')}, Region: {match.get('4. region')}"
            finance_url = f"https://finance.yahoo.com/q?s={symbol}"
            normalized_results.append(
                _normalize_data('Finance', name, finance_url, snippet)
            )
        return normalized_results
    except Exception as e:
        logging.error(f"Alpha Vantage API request failed for '{entity}': {e}")
        return []

# In web_context_agent.py, this is the final, production-ready version.

def _call_hotels_api(entity: str):
    """
    Calls the fast, single-step Tripadvisor Scraper API and correctly
    parses and filters the results using the final, correct key names.
    """
    api_key = os.getenv("RAPIDAPI_KEY")
    if not api_key:
        logging.error("RAPIDAPI_KEY is not set.")
        return []

    url = "https://tripadvisor-scraper.p.rapidapi.com/hotels/search"
    params = {"query": entity}
    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": "tripadvisor-scraper.p.rapidapi.com"
    }

    try:
        logging.warning(f"--- Calling Tripadvisor Scraper Hotel API for entity: {entity} ---")
        response = requests.get(url, headers=headers, params=params, timeout=25)
        response.raise_for_status()
        
        all_results = response.json()
        if not all_results:
            logging.warning(f"API returned an empty list for city: {entity}")
            return []

        # Filter the list to only include actual hotels ('accommodation').
        hotels = [item for item in all_results if item.get('type') == 'accommodation']
        if not hotels:
            logging.warning(f"No hotel results found after filtering for city: {entity}")
            return []

        logging.warning(f"--- Success! Normalizing {len(hotels)} hotel results from Tripadvisor Scraper. ---")
        normalized_results = []
        for hotel in hotels[:5]: # Take the first 5 results
            
            # --- FINAL FIXES ARE HERE ---
            # Using the correct keys based on the data you provided.
            title = hotel.get('name') or "Title Not Available"
            hotel_url = hotel.get('link') or "#"
            image_url = hotel.get('thumbnail_url') # Correct key for the image

            # This API doesn't provide rating/reviews, so these will correctly show "N/A"
            rating = hotel.get('rating') or "N/A"
            reviews = hotel.get('reviewsCount') or "0"
            snippet = "View on TripAdvisor"
            
            normalized_results.append(
                _normalize_data(
                    "Hotel",
                    title,
                    hotel_url,
                    snippet,
                    image_url
                )
            )
        return normalized_results

    except requests.exceptions.RequestException as e:
        logging.error(f"Tripadvisor Scraper Hotel search failed: {e}")
        return []
    except Exception as e:
        logging.error(f"An unexpected error occurred in _call_hotels_api: {e}")
        return []
        
#def _call_flights_api(entity: str):
#    logging.warning(f"--- Flights API function called for '{entity}', but it is not implemented yet. ---")
#    return []


# In web_context_agent.py

def _perform_google_search(original_query: str, intent: str, entity: str):
    """
    An intelligent fallback search function that first uses an LLM to generate an
    optimized, precise Google Search query based on the user's intent, then executes it.
    """
    # --- 1. Generate the Optimized Query using AI ---
    try:
        # This prompt turns the LLM into a Google Search expert
        query_optimizer_prompt = f"""
        You are a Google Search query optimization expert. Your task is to take a user's original query, their inferred 'intent', and the key 'entity', and generate a single, highly precise Google search query string that will yield the best possible results.

        **Instructions:**
        - Use advanced search operators like "" for exact phrases, OR for alternatives, and site: for specific high-quality domains.
        - Tailor the query to the intent. For KNOWLEDGE, prioritize encyclopedic sites. For technical topics, prioritize official documentation or tutorials.
        - The goal is precision, not just keyword matching.

        **User's Original Query:** "{original_query}"
        **Inferred Intent:** "{intent}"
        **Key Entity:** "{entity}"

        --- EXAMPLES ---
        1. Intent: KNOWLEDGE, Entity: "History of Delhi"
           Optimized Query: "history of Delhi" OR "Delhi Sultanate timeline" site:en.wikipedia.org OR site:britannica.com

        2. Intent: SHOPPING, Entity: "Tesla Model 3"
           Optimized Query: "buy Tesla Model 3" official price OR "Model 3 reviews 2025"

        3. Intent: RESTAURANTS, Entity: "Hyderabad"
           Optimized Query: "best restaurants in Hyderabad" site:zomato.com OR "top 10 places to eat Hyderabad"

        Based on the user's request, what is the single best, optimized search query string?
        """
        # Note: We are using the main 'genai' instance configured in app.py
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        response = model.generate_content(query_optimizer_prompt)
        optimized_query = response.text.strip()
        logging.warning(f"--- Optimized Google Search query: '{optimized_query}' ---")
    except Exception as e:
        logging.error(f"Failed to generate optimized query: {e}. Using original query as fallback.")
        optimized_query = original_query

    # --- 2. Execute the Search with the Optimized Query ---
    api_key = os.getenv("GOOGLE_SEARCH_API_KEY")
    search_engine_id = os.getenv("SEARCH_ENGINE_ID")
    
    if not api_key or not search_engine_id:
        logging.error("Google Search_API_KEY or SEARCH_ENGINE_ID are not set in the environment.")
        return []

    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        'key': api_key,
        'cx': search_engine_id,
        'q': optimized_query, # Use the new, smarter query
        'num': 8
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        search_results = response.json().get('items', [])
        # --- NEW: Retry Logic ---
        # If the optimized query returned no results, try again with the simple query.
        if not search_results:
            logging.warning(f"--- Optimized query returned no results. Retrying with simple query: '{original_query}' ---")
            params['q'] = original_query # Switch to the original query
            response = requests.get(url, params=params)
            response.raise_for_status()
            search_results = response.json().get('items', [])

        # ... (The normalization part of the function remains the same)
        normalized_results = []
        for item in search_results:
            pagemap = item.get('pagemap', {})
            cse_image = pagemap.get('cse_image', [{}])
            image_url = cse_image[0].get('src') if cse_image and isinstance(cse_image, list) else None
            normalized_results.append({
                "type": "Web Link",
                "title": item.get('title'),
                "url": item.get('link'),
                "snippet": item.get('snippet'),
                "image": image_url
            })
        return normalized_results
    except Exception as e:
        logging.error(f"An unexpected error occurred in  _perform_google_search: {e}")
        return []