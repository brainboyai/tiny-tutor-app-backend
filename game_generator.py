# game_generator.py

import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import logging
import json
import re
import random
from urllib.parse import quote

# --- Asset Management Logic (Integrated) ---

# The base URL for your raw GitHub content.
ASSET_BASE_URL = "https://raw.githubusercontent.com/brainboyai/tiny-tutor-game-objects/main/"

def get_image_urls(object_names: list[str]) -> dict[str, str]:
    """
    Constructs full image URLs for a list of object names from the GitHub repo.

    Args:
        object_names: A list of object names (e.g., ['Tiger', 'Rice', 'Wolf']).

    Returns:
        A dictionary mapping each object name to its corresponding image URL.
    """
    image_urls = {}
    for name in object_names:
        if not name or not isinstance(name, str):
            continue
        
        # Clean and format the name for the URL.
        # quote() handles spaces and special characters, e.g., "Piger (1)" -> "Piger%20(1)".
        url_friendly_name = quote(name.strip())

        # Randomly choose between the base name ("cow.png") and a variant ("cow (1).png")
        if random.choice([True, False]):
            image_filename = f"{url_friendly_name}%20(1).png"
        else:
            image_filename = f"{url_friendly_name}.png"
            
        # All GitHub image names are lowercase, so we convert the final URL.
        full_url = f"{ASSET_BASE_URL}{image_filename.lower()}"
        image_urls[name] = full_url
        
    return image_urls

# --- End of Asset Management Logic ---


# The prompt to the AI, instructing it how to design the game content.
PROMPT_TEMPLATE = """
You are an expert educational game designer and developer. Your task is to generate the content for a complete, single-file HTML game for the topic: "TOPIC_PLACEHOLDER" using the Kaboom.js game engine. The game is a fast-paced "Tap the Right Ones" challenge.

---
### **MANDATORY WORKFLOW**
---
1.  **Analyze Topic & Create Content:**
    * Deeply analyze the topic: **"TOPIC_PLACEHOLDER"**.
    * Your primary task is to generate the following content:
        1.  **Game Title:** A short, fun title for the game.
        2.  **Game Instructions:** A clear, one-sentence instruction for the player.
        3.  **`correctItems`**: A JavaScript array of strings that are correct examples of the topic.
        4.  **`incorrectItems`**: A JavaScript array of strings that are plausible but incorrect distractors.
    * The item lists should be rich and varied. Aim for 5-10 items each.

2.  **Format Your Output:** At the very beginning of your response, you MUST state the content you have generated, with each item on a new line.

    * **Example for topic "Herbivores":**
    * Game Title: Herbivore Hunt
    * Game Instructions: Tap all the animals that only eat plants!
    * Correct Items: ["Cow", "Goat", "Rabbit", "Deer", "Sheep", "Horse", "Zebra"]
    * Incorrect Items: ["Lion", "Tiger", "Shark", "Wolf", "Fox", "Bear"]

3.  **Provide ONLY The Content:** Do not output any HTML. Your entire response should just be the four lines of content as specified above.
"""

# The HTML structure for the game, with placeholders for the AI-generated content.
GAME_HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>{title}</title>
    <style>body, html {{ margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background: #000; }}</style>
</head>
<body>
    <script src="https://unpkg.com/kaboom@3000.0.1/dist/kaboom.js"></script>
    <script>
        kaboom({{ width: 800, height: 600, letterbox: true, background: [20, 20, 30] }});

        // --- Asset and Item Data (Injected by Backend) ---
        const assets = {assets_json};
        const correctItems = {correct_items_json};
        const incorrectItems = {incorrect_items_json};
        const gameTitle = {title_json};
        const gameInstructions = {instructions_json};

        // Load all sprites from the URLs
        for (const name in assets) {{
            if (assets[name]) {{
                // Use a try-catch to handle cases where an image fails to load
                try {{
                    loadSprite(name, assets[name], {{ crossOrigin: "anonymous" }});
                }} catch (e) {{
                    console.error(`Could not load sprite for ${{name}} from ${{assets[name]}}`, e);
                }}
            }}
        }}
        
        function chooseMultiple(arr, num) {{
            const shuffled = [...arr].sort(() => 0.5 - Math.random());
            return shuffled.slice(0, num);
        }}

        scene("start", () => {{
             add([ text(gameTitle, {{ size: 48, font: "sans-serif", width: width() - 100 }}), pos(width() / 2, height() / 2 - 120), anchor("center") ]);
             add([ text(gameInstructions, {{ size: 22, font: "sans-serif", width: width() - 100 }}), pos(width() / 2, height() / 2 - 20), anchor("center") ]);
             add([ text("Click to Start", {{ size: 32, font: "sans-serif" }}), pos(width() / 2, height() / 2 + 80), anchor("center") ]);
            onClick(() => go("game", {{ level: 1, score: 0 }}));
        }});

        scene("game", ({{ level, score }}) => {{
            let timer = 15;
            const itemsToFind = chooseMultiple(correctItems, Math.min(2 + level, correctItems.length));
            let correctTaps = 0;

            const scoreLabel = add([ text(`Score: ${{score}}`), pos(24, 24), {{ layer: "ui" }} ]);
            const timerLabel = add([ text(`Time: ${{timer.toFixed(1)}}`), pos(width() - 24, 24), anchor("topright"), {{ layer: "ui" }} ]);
            const levelLabel = add([ text(`Level: ${{level}}`), pos(width() / 2, 24), anchor("top"), {{ layer: "ui" }} ]);
            add([ text("Find: " + itemsToFind.join(', '), {{ size: 18, width: width() - 40 }}), pos(width()/2, 60), anchor("top")]);

            function spawnObject(itemName, itemTag) {{
                const speed = 80 + (level * 15);
                const obj = add([
                    pos(rand(80, width() - 80), rand(120, height() - 80)),
                    area({{ scale: 0.8 }}),
                    anchor("center"),
                    move(choose([UP, DOWN, LEFT, RIGHT]), speed),
                    "object",
                    itemTag,
                    {{ name: itemName }}
                ]);

                // Check if the sprite exists before trying to add it
                if (getSprite(itemName)) {{
                    obj.add(sprite(itemName, {{ width: 90, height: 90 }}));
                }} else {{
                    // Fallback to a rectangle with text if the image failed to load
                    obj.add(rect(120, 50, {{ radius: 8 }}));
                    obj.add(color(200, 200, 200));
                    obj.add(text(itemName, {{ size: 16, width: 110, align: "center" }}));
                    obj.add(color(0,0,0)); // Text color
                }}
            }}

            itemsToFind.forEach(name => spawnObject(name, "correct"));
            chooseMultiple(incorrectItems, 2 + level).forEach(name => spawnObject(name, "incorrect"));
            
            onClick("correct", (item) => {{
                if (itemsToFind.includes(item.name)) {{
                    destroy(item);
                    score += 10;
                    correctTaps++;
                    scoreLabel.text = `Score: ${{score}}`;
                    addKaboom(item.pos);
                    if (correctTaps >= itemsToFind.length) {{
                        go("game", {{ level: level + 1, score: score }});
                    }}
                }}
            }});

            onClick("incorrect", (item) => {{
                shake(15);
                score = Math.max(0, score - 5);
                scoreLabel.text = `Score: ${{score}}`;
            }});

            onUpdate("object", (item) => {{
                if (item.pos.x < 40) {{ item.pos.x = width() - 40; }}
                if (item.pos.x > width() - 40) {{ item.pos.x = 40; }}
                if (item.pos.y < 80) {{ item.pos.y = height() - 40; }}
                if (item.pos.y > height() - 40) {{ item.pos.y = 80; }}
            }});
            
            onUpdate(() => {{
                timer -= dt();
                timerLabel.text = `Time: ${{timer.toFixed(1)}}`;
                if (timer <= 0) {{
                    go("end", {{ finalScore: score }});
                }}
            }});
        }});

        scene("end", ({{ finalScore }}) => {{
            add([ text("Time's Up!", {{ size: 60 }}), pos(width()/2, height()/2 - 80), anchor("center") ]);
            add([ text(`Final Score: ${{finalScore}}`, {{ size: 40 }}), pos(width() / 2, height() / 2), anchor("center"), ]);
            add([ text("Click to play again", {{ size: 24 }}), pos(width() / 2, height() / 2 + 80), anchor("center"), ]);
            onClick(() => go("start"));
        }});
        
        go("start");
    </script>
</body>
</html>
"""

def parse_ai_reasoning(reasoning_text: str):
    """Parses the reasoning text from the AI to extract game metadata."""
    title_match = re.search(r"Game Title:\s*(.*)", reasoning_text)
    instructions_match = re.search(r"Game Instructions:\s*(.*)", reasoning_text)
    correct_match = re.search(r"Correct Items:\s*(\[.*?\])", reasoning_text, re.DOTALL)
    incorrect_match = re.search(r"Incorrect Items:\s*(\[.*?\])", reasoning_text, re.DOTALL)

    title = title_match.group(1).strip() if title_match else "Tiny Tutor Game"
    instructions = instructions_match.group(1).strip() if instructions_match else "Tap the correct items!"
    
    try:
        correct_items = json.loads(correct_match.group(1)) if correct_match else []
        incorrect_items = json.loads(incorrect_match.group(1)) if incorrect_match else []
    except (json.JSONDecodeError, AttributeError):
        correct_items = []
        incorrect_items = []

    return title, instructions, correct_items, incorrect_items


def generate_game_for_topic(topic: str):
    """Generates game HTML by calling the Gemini API and injecting content."""
    try:
        prompt = PROMPT_TEMPLATE.replace("TOPIC_PLACEHOLDER", topic)

        gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')
        safety_settings = {HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE}
        
        response = gemini_model.generate_content(prompt, safety_settings=safety_settings)
        reasoning_text = response.text.strip()
        
        # Parse the entire AI response to get our structured data
        title, instructions, correct_items, incorrect_items = parse_ai_reasoning(reasoning_text)

        if not correct_items or not incorrect_items:
             raise ValueError(f"AI did not return valid item lists. Full response: {reasoning_text}")

        # Get image URLs for all items from the asset helper
        all_game_objects = correct_items + incorrect_items
        asset_urls = get_image_urls(all_game_objects)

        # Inject the dynamic data into the HTML template
        final_html = GAME_HTML_TEMPLATE.format(
            title=title,
            assets_json=json.dumps(asset_urls),
            correct_items_json=json.dumps(correct_items),
            incorrect_items_json=json.dumps(incorrect_items),
            title_json=json.dumps(title),
            instructions_json=json.dumps(instructions)
        )
        
        # The "reasoning" is the full text output from the AI for debugging or display
        return reasoning_text, final_html

    except Exception as e:
        logging.error(f"Exception in generate_game_for_topic for topic '{topic}': {e}")
        # Provide a user-friendly error message in the game window itself
        error_html = f"<h1>Error Generating Game</h1><p>An error occurred: {e}</p><p>Please try a different topic.</p>"
        return f"Internal Server Error: {e}", error_html

