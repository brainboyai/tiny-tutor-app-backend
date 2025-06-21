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

    # NEW: Add specific logging for each route
    if intent == "NEWS":
        logging.warning(f"--- Routing to NEWS API for entity: {entity} ---")
        return _call_news_api(entity)
    elif intent == "VIDEO":
        logging.warning(f"--- Routing to YOUTUBE API for entity: {entity} ---")
        return _call_youtube_api(entity)
    elif intent == "KNOWLEDGE":
        logging.warning(f"--- Routing to WIKIPEDIA API for entity: {entity} ---")
        return _call_wikipedia_api(entity)
    elif intent == "EVENTS":
        logging.warning(f"--- Routing to TICKETMASTER API for entity: {entity} ---")
        return _call_ticketmaster_api(entity)
    elif intent == "FINANCE":
        logging.warning(f"--- Routing to ALPHA VANTAGE API for entity: {entity} ---")
        return _call_alphavantage_api(entity)
    elif intent == "RESTAURANTS":
        # We need a function for this, for now, we can use the fallback
        logging.warning(f"--- Routing to RESTAURANTS (using fallback search for now) for entity: {entity} ---")
        return _perform_google_search(f"best restaurants in {entity}")
    elif intent == "TRAVEL_HOTELS":
        logging.warning(f"--- Routing to HOTELS API for entity: {entity} ---")
        return _call_hotels_api(entity)
    elif intent == "SHOPPING":
        logging.warning(f"--- Routing to SHOPPING (using fallback search) for entity: {entity} ---")
        shopping_query = f"{entity} buy online price"
        return _perform_google_search(shopping_query)
    else: 
        logging.warning(f"--- No specific tool found. Routing to FALLBACK GOOGLE SEARCH for query: {query} ---")
        return _perform_google_search(query)

def _get_intent_from_query(query: str, model: genai.GenerativeModel):
    """
    Uses the LLM to classify the user's query into a specific intent category
    and extract the key entity for searching.
    """
    prompt = f"""
    You are an expert query analysis engine. Your task is to analyze the user's search query and classify it into one of the STRICT predefined categories. You must also extract the core search entity.

    Available Categories:
    - NEWS (for queries about current events and news)
    - VIDEO (for queries requesting videos, vlogs, visual media)
    - KNOWLEDGE (for queries asking for definitions, history, guides, information)
    - EVENTS (for queries about tickets, concerts, festivals, sports)
    - FINANCE (for queries about stock prices, crypto, financial markets)
    - RESTAURANTS (for queries about finding places to eat, food, dining)
    - TRAVEL_HOTELS (for queries specifically about hotels, stays, accommodations)
    - SHOPPING (for queries about buying products, e-commerce)
    - FALLBACK_SEARCH (for anything else or ambiguous queries)

    Analyze the following user query: "{query}"

    Return your response as a single, raw, minified JSON object with two keys: "intent" and "entity".

    Example 1:
    Query: "restaurants in Hyderabad"
    Output: {{"intent": "RESTAURANTS", "entity": "Hyderabad"}}

    Example 2:
    Query: "Delhi travel guide"
    Output: {{"intent": "KNOWLEDGE", "entity": "Delhi"}}
    """
    
    response = model.generate_content(prompt)
    analysis = json.loads(response.text.strip())
    return analysis.get("intent"), analysis.get("entity")

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

def _call_ticketmaster_api(entity: str):
    api_key = os.getenv("TICKETMASTER_API_KEY")
    if not api_key: return []
    url = f"https://app.ticketmaster.com/discovery/v2/events.json?apikey={api_key}&keyword={quote_plus(entity)}&size=5"
    try:
        response = requests.get(url)
        response.raise_for_status()
        events = response.json().get('_embedded', {}).get('events', [])
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

# In web_context_agent.py, replace the entire _call_hotels_api function

def _call_hotels_api(entity: str):
    """
    Calls the Booking.com API using a 2-step process:
    1. Gets a destination ID from the city name using the auto-complete endpoint.
    2. Searches for hotels using that destination ID.
    """
    api_key = os.getenv("RAPIDAPI_KEY")
    if not api_key:
        logging.error("RAPIDAPI_KEY is not set.")
        return []

    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": "booking-com18.p.rapidapi.com"
    }

    # --- STEP 1: Get Destination ID from city name ---
    try:
        autocomplete_url = "https://booking-com18.p.rapidapi.com/web/stays/auto-complete"
        autocomplete_params = {"query": entity}
        
        logging.warning(f"--- Calling Hotels Auto-Complete for entity: {entity} ---")
        ac_response = requests.get(autocomplete_url, headers=headers, params=autocomplete_params)
        ac_response.raise_for_status()
        
        # Extract the dest_id from the first result
        # Note: The response structure might vary slightly.
        # This assumes the first result is the most relevant.
        ac_data = ac_response.json().get("data", [])
        if not ac_data or "dest_id" not in ac_data[0]:
            logging.error(f"Could not find a destination ID for '{entity}' in auto-complete response.")
            return []
            
        dest_id = ac_data[0]["dest_id"]
        dest_type = ac_data[0]["dest_type"]
        logging.warning(f"--- Found dest_id: {dest_id} for entity: {entity} ---")

    except Exception as e:
        logging.error(f"Hotel auto-complete request failed for '{entity}': {e}")
        return []

    # --- STEP 2: Search for hotels using the Destination ID ---
    try:
        search_url = "https://booking-com18.p.rapidapi.com/web/stays/search"
        
        # Generate default check-in/check-out dates for 3 months from now
        checkin_date = (datetime.now() + timedelta(days=90)).strftime('%Y-%m-%d')
        checkout_date = (datetime.now() + timedelta(days=91)).strftime('%Y-%m-%d')

        search_params = {
            "destId": dest_id,
            "destType": dest_type,
            "checkin": checkin_date,
            "checkout": checkout_date
        }
        
        logging.warning(f"--- Calling Hotels Search with dest_id: {dest_id} ---")
        search_response = requests.get(search_url, headers=headers, params=search_params)
        search_response.raise_for_status()

        hotels = search_response.json().get("results", [])
        if not hotels:
            logging.warning(f"No hotel results found for dest_id: {dest_id}")
            return []

        # Normalize the data from the search results
        normalized_results = []
        for hotel in hotels:
            snippet = f"Review Score: {hotel.get('reviewScore', 'N/A')} / 10"
            image_url = hotel.get('photoUrls', [{}])[0].get('s') if hotel.get('photoUrls') else None
            normalized_results.append(
                _normalize_data(
                    "Hotel",
                    hotel.get('name'),
                    hotel.get('url'),
                    snippet,
                    image_url
                )
            )
        return normalized_results

    except Exception as e:
        logging.error(f"Hotel search request failed for dest_id '{dest_id}': {e}")
        return []

        
#def _call_flights_api(entity: str):
#    logging.warning(f"--- Flights API function called for '{entity}', but it is not implemented yet. ---")
#    return []

def _perform_google_search(query: str):
    """
    This is the fallback search function. It uses the exact names you specified.
    - Function name: _perform_google_search
    - API Key variable: Google Search_API_KEY
    """
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
        search_results = response.json().get('items', [])

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

    except requests.exceptions.RequestException as e:
        logging.error(f"Google Search API request failed: {e}")
        return []
    except Exception as e:
        logging.error(f"An unexpected error occurred in _perform_google_search: {e}")
        return []