import google.generativeai as genai
import json
import logging
import os
import requests
from urllib.parse import quote_plus
from datetime import datetime, timedelta

# In web_context_agent.py, replace your get_routed_web_context function

# In web_context_agent.py

def get_routed_web_context(query: str, model: genai.GenerativeModel):
    """
    [UPGRADED] A universal router that gives EVERY tool a fallback to intelligent search.
    """
    try:
        intent, entity = _get_intent_from_query(query, model)
        logging.warning(f"AGENT LOG: Intent recognized for query '{query}' -> INTENT: {intent}, ENTITY: {entity}")
    except Exception as e:
        logging.error(f"Could not determine intent for query '{query}': {e}. Using fallback.")
        intent, entity = "FALLBACK_SEARCH", query

    results = []
    # This variable will track if we are using a specific tool or the final fallback
    is_fallback_search = True 

    if intent == "NEWS":
        logging.warning(f"--- Routing to NEWS API for entity: {entity} ---")
        results = _call_news_api(entity)
        is_fallback_search = False
    elif intent == "VIDEO":
        logging.warning(f"--- Routing to YOUTUBE API for entity: {entity} ---")
        results = _call_youtube_api(entity)
        is_fallback_search = False
    elif intent == "KNOWLEDGE":
        logging.warning(f"--- Routing to WIKIPEDIA API for entity: {entity} ---")
        results = _call_wikipedia_api(entity)
        is_fallback_search = False
    elif intent == "EVENTS":
        logging.warning(f"--- Routing to TICKETMASTER API for entity: {entity} ---")
        results = _call_ticketmaster_api(entity)
        is_fallback_search = False
    elif intent == "FINANCE":
        logging.warning(f"--- Routing to ALPHA VANTAGE API for entity: {entity} ---")
        results = _call_alphavantage_api(entity)
        is_fallback_search = False
    elif intent == "TRAVEL_HOTELS":
        logging.warning(f"--- Routing to HOTELS API for entity: {entity} ---")
        results = _call_hotels_api(entity)
        is_fallback_search = False
    
    # --- UNIVERSAL FALLBACK LOGIC ---
    # If a specific tool was used but it returned no results, we use the intelligent fallback.
    if not is_fallback_search and not results:
        logging.warning(f"--- Tool for intent '{intent}' had no results. Using intelligent fallback search. ---")
        return _perform_google_search(query, intent, entity)
    # If the initial intent was already a fallback search, just run it.
    elif is_fallback_search:
        logging.warning(f"--- Routing to INTELLIGENT FALLBACK for query: {query} ---")
        return _perform_google_search(query, intent, entity)
    # Otherwise, return the successful results from the specific tool.
    else:
        return results
    
def _get_intent_from_query(query: str, model: genai.GenerativeModel):
    """
    [UPGRADED] Uses the LLM to classify the query with higher precision
    and extract a cleaner entity.
    """
    prompt = f"""
    You are a highly precise query analysis engine. Your task is to analyze the user's query and classify it into one of the STRICT predefined categories. You must also extract the primary search entity.

    **CRITICAL INSTRUCTIONS:**
    1.  The 'entity' should be the primary noun (e.g., a city, company, or concept). DO NOT include modifiers like "this weekend", "in my area", or descriptive adjectives unless they are part of a formal name.
    2.  If a query contains a high level of specific detail beyond the main entity (e.g., a specific genre of music, a specific type of cuisine), it is often better to use 'FALLBACK_SEARCH' so a more detailed web search can be performed. The specialized tools may not support such detail.
    3.  If a query is ambiguous, use 'FALLBACK_SEARCH'.

    **Available Categories:**
    - NEWS, VIDEO, KNOWLEDGE, EVENTS, FINANCE, RESTAURANTS, TRAVEL_HOTELS, SHOPPING, FALLBACK_SEARCH

    --- EXAMPLES ---
    Query: "Events in Miami this weekend"
    Output: {{"intent": "EVENTS", "entity": "Miami"}}

    Query: "Events featuring Latin American music in Miami"
    Output: {{"intent": "FALLBACK_SEARCH", "entity": "Events featuring Latin American music in Miami"}}

    Query: "best 5-star hotels in Goa"
    Output: {{"intent": "TRAVEL_HOTELS", "entity": "Goa"}}
    ---

    Analyze the following user query: "{query}"

    Return your response as a single, raw, minified JSON object.
    """
    
    response = model.generate_content(prompt)
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
# In web_context_agent.py

def _call_ticketmaster_api(entity: str):
    """
    Calls the Ticketmaster API and defensively normalizes the results
    to prevent frontend crashes from incomplete data.
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

        events = response.json().get('_embedded', {}).get('events', [])
        
        logging.warning(f"--- Found {len(events)} events in Ticketmaster response. ---")
        if not events:
            return []

        normalized_results = []
        for event in events:
            # --- Defensive Normalization Logic ---
            # Provide a default value for each piece of data to ensure the frontend never crashes.
            
            title = event.get('name') or "Event Title Not Available"
            event_url = event.get('url') or "#"
            
            # Safely find the best available image
            image_url = None
            if event.get('images') and isinstance(event.get('images'), list):
                image_url = next((img.get('url') for img in event['images'] if img.get('ratio') == '16_9'), None)

            # Safely get the date
            date = "Date N/A"
            if event.get('dates', {}).get('start', {}).get('localDate'):
                date = event['dates']['start']['localDate']
            
            snippet = f"Date: {date}"

            normalized_results.append(
                _normalize_data('Event', title, event_url, snippet, image_url)
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
    [UPGRADED] An intelligent fallback search function with a more precise
    query optimization prompt.
    """
    try:
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        query_optimizer_prompt = f"""
        You are a Google Search query optimization expert. Your task is to take a user's original query, their inferred 'intent', and the key 'entity', and generate a single, highly precise Google search query string.

        **Instructions:**
        - To improve relevance, ensure the main 'entity' is a mandatory part of the search, often by using double quotes around it if it's a multi-word name.
        - Use advanced operators like `OR` and `site:` to query high-quality domains relevant to the intent.

        **User's Original Query:** "{original_query}"
        **Inferred Intent:** "{intent}"
        **Key Entity:** "{entity}"

        --- EXAMPLES ---
        1. Intent: RESTAURANTS, Entity: "Goa"
           Optimized Query: "best restaurants in "Goa"" site:zomato.com OR "top rated restaurants Goa" site:tripadvisor.com

        2. Intent: KNOWLEDGE, Entity: "History of Delhi"
           Optimized Query: "history of "New Delhi"" OR "Delhi Sultanate timeline" site:en.wikipedia.org OR site:britannica.com
        ---

        Based on the user's request, what is the single best, optimized search query string?
        """
        response = model.generate_content(query_optimizer_prompt)
        optimized_query = response.text.strip()
        logging.warning(f"--- Optimized Google Search query: '{optimized_query}' ---")
    except Exception as e:
        logging.error(f"Failed to generate optimized query: {e}. Using original query.")
        optimized_query = original_query

    # --- Execute the Search (with existing retry logic) ---
    # ... (the rest of this function remains exactly the same as the previous version) ...
    api_key = os.getenv("GOOGLE_SEARCH_API_KEY")
    search_engine_id = os.getenv("SEARCH_ENGINE_ID")
    if not api_key or not search_engine_id: return []

    url = "https://www.googleapis.com/customsearch/v1"
    params = {'key': api_key, 'cx': search_engine_id, 'q': optimized_query, 'num': 8}
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        search_results = response.json().get('items', [])

        if not search_results:
            logging.warning(f"--- Optimized query returned no results. Retrying with simple query: '{original_query}' ---")
            params['q'] = original_query
            response = requests.get(url, params=params)
            response.raise_for_status()
            search_results = response.json().get('items', [])

        normalized_results = []
        for item in search_results:
            pagemap = item.get('pagemap', {})
            cse_image = pagemap.get('cse_image', [{}])
            image_url = cse_image[0].get('src') if cse_image and isinstance(cse_image, list) else None
            normalized_results.append({ "type": "Web Link", "title": item.get('title'), "url": item.get('link'), "snippet": item.get('snippet'), "image": image_url })
        return normalized_results
        
    except Exception as e:
        logging.error(f"An unexpected error occurred in _perform_Google Search: {e}")
        return []