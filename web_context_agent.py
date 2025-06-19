import google.generativeai as genai

def get_web_context(topic: str, model: genai.GenerativeModel):
    """
    Analyzes a topic, generates search queries, and returns a structured
    list of the best web links for different categories.
    """
    # This prompt asks the AI to act as a search expert.
    # It will analyze the user's topic and generate targeted search queries
    # to find the most relevant articles, videos, and services.
    prompt = f"""
    You are a sophisticated search query generator. Your task is to analyze the user's topic, "{topic}", and generate a list of 3-5 optimal Google search queries to find the most relevant, high-quality content for them across different categories: informational articles, video content, and related services or products.

    Return your answer as a JSON object with a single key "queries" which contains a list of these search strings.

    Example for topic "Delhi":
    {{
      "queries": [
        "best Delhi tourism blog",
        "Delhi travel guide for first-timers",
        "top sights in Delhi youtube vlog",
        "book hotels in Delhi"
      ]
    }}

    Example for topic "Protein Foods":
    {{
      "queries": [
        "buy high protein foods online",
        "high protein snack recipes",
        "best sources of plant-based protein",
        "youtube high protein meal prep"
      ]
    }}
    """
    
    # Generate the search queries using the Gemini model
    response = model.generate_content(prompt)
    
    # The rest of this function would involve:
    # 1. Parsing the JSON response to get the list of queries.
    # 2. Executing these queries using a search tool.
    # 3. Analyzing the search results to pick the best link for each category.
    # 4. Returning the final structured list of links.
    
    # For now, to demonstrate the query generation, we will return a placeholder.
    # In a real implementation, this would be replaced with the full logic.
    if "stanford" in topic.lower():
        return [
            {
              "type": "info",
              "title": "Stanford University",
              "url": "https://www.stanford.edu/",
              "snippet": "The official website of Stanford University, a place of discovery, creativity, and innovation."
            },
            {
              "type": "read",
              "title": "Stanford University Online Courses",
              "url": "https://www.coursera.org/partners/stanford",
              "snippet": "Explore free online courses from Stanford, covering subjects from computer science to arts & humanities."
            },
            {
              "type": "watch",
              "title": "Stanford University | 4K Campus Tour",
              "url": "https://www.youtube.com/watch?v=ststYQuE4hE",
              "snippet": "A stunning 4K walking tour of the beautiful Stanford University campus, showcasing its architecture and vibrant student life."
            }
        ]
    
    return [] # Return empty list if no specific logic matches