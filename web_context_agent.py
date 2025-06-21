import google.generativeai as genai
import json
import logging
import os
import requests
from urllib.parse import quote_plus

# This is our new primary function that will be called from app.py
def get_routed_web_context(query: str, model: genai.GenerativeModel):
    """
    Acts as an Intent-Based Router. It analyzes the user's query, determines the best API to call,
    fetches the data, and returns it in a standardized format.
    """
    
    # 1. First, recognize the intent from the user's query
    try:
        intent, entity = _get_intent_from_query(query, model)
        logging.warning(f"AGENT LOG: Intent recognized for query '{query}' -> INTENT: {intent}, ENTITY: {entity}")
    except Exception as e:
        logging.error(f"Could not determine intent for query '{query}': {e}. Using fallback.")
        intent, entity = "FALLBACK_SEARCH", query

    # 2. Route to the correct API based on the recognized intent
    if intent == "NEWS":
        return _call_news_api(entity)
    elif intent == "VIDEO":
        return _call_youtube_api(entity)
    elif intent == "KNOWLEDGE":
        return _call_wikipedia_api(entity)
    elif intent == "EVENTS":
        return _call_ticketmaster_api(entity)
    elif intent == "FINANCE":
        return _call_alphavantage_api(entity)
    elif intent == "TRAVEL_HOTELS":
        return _call_hotels_api(entity)
    # --- FLIGHTS LOGIC IS SKIPPED FOR NOW ---
    #elif intent == "TRAVEL_FLIGHTS":
    #    return _call_flights_api(entity)
    elif intent == "SHOPPING":
        shopping_query = f"{entity} buy online price"
        return _perform_google_search(shopping_query)
    else: # Fallback for generic queries
        return _perform_google_search(query)


def _get_intent_from_query(query: str, model: genai.GenerativeModel):
    """
    Uses the LLM to classify the user's query into a specific intent category
    and extract the key entity for searching.
    """
    prompt = f"""
    You are an expert query analysis engine. Your task is to analyze the user's search query and classify it into one of the predefined categories. You must also extract the core search entity.

    Available Categories:
    - NEWS (for queries about current events, news)
    - VIDEO (for queries requesting videos, vlogs, visual explanations)
    - KNOWLEDGE (for queries asking for definitions, history, information)
    - EVENTS (for queries about tickets, concerts, festivals, sports)
    - FINANCE (for queries about stock prices, crypto, financial markets)
    - TRAVEL_HOTELS (for queries about hotels, stays, accommodations in a city)
    - SHOPPING (for queries about buying products, e-commerce)
    - FALLBACK_SEARCH (for anything else)

    Analyze the following user query: "{query}"

    Return your response as a single, raw, minified JSON object with two keys: "intent" and "entity".

    Example 1:
    Query: "concerts in London"
    Output: {{"intent": "EVENTS", "entity": "London"}}

    Example 2:
    Query: "stock price for TSLA"
    Output: {{"intent": "FINANCE", "entity": "TSLA"}}

    Example 3:
    Query: "Travel to Delhi"
    Output: {{"intent": "TRAVEL_FLIGHTS", "entity": "Delhi"}}
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

# ADD THIS NEW FUNCTION to your web_context_agent.py file
def _call_hotels_api(entity: str):
    """
    Calls a hotel API from RapidAPI to find places to stay in a city.
    """
    # You will get this key from RapidAPI after subscribing to a hotel API
    api_key = os.getenv("RAPIDAPI_KEY") 
    if not api_key:
        logging.error("RAPIDAPI_KEY is not set.")
        return []

    # This example uses the "Hotel Booking" API by API-Ninjas on RapidAPI
    # The URL and parameters might be different depending on which API you choose
    url = "https://hotel-booking.p.rapidapi.com/v1/hotels/search-by-city"
    params = {"city_name": entity, "country_name": "India"} # You might need to make 'country_name' dynamic
    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": "hotel-booking.p.rapidapi.com"
    }

    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        hotels = response.json().get("results", [])

        normalized_results = []
        for hotel in hotels:
            # The field names ('hotel_name', 'photo_url', etc.) will depend on the API you choose
            snippet = f"Rating: {hotel.get('rating', 'N/A')} Stars | Price: {hotel.get('price', 'N/A')}"
            normalized_results.append(
                _normalize_data(
                    item_type="Hotel",
                    title=hotel.get('hotel_name'),
                    url=hotel.get('url'), # Many APIs provide a booking URL
                    snippet=snippet,
                    image=hotel.get('photo_url')
                )
            )
        return normalized_results
    except requests.exceptions.RequestException as e:
        logging.error(f"RapidAPI Hotel search failed: {e}")
        return []
    except Exception as e:
        logging.error(f"An unexpected error occurred in _call_hotels_api: {e}")
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