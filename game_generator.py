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
    Constructs a full image URL for each object name.
    This function correctly handles names with spaces and variants like "(1)".
    For example, an AI-generated item named "Bengal Tiger (1)" will correctly
    look for a file named "bengal tiger (1).png".
    """
    image_urls = {}
    for name in object_names:
        if not name or not isinstance(name, str):
            continue

        # Clean the name: lowercase, strip whitespace.
        cleaned_name = name.strip().lower()
        # URL-encode the cleaned name to handle spaces and parentheses.
        # e.g., "bengal tiger (1)" -> "bengal%20tiger%20(1)"
        url_friendly_name = quote(cleaned_name)

        # Construct the final URL.
        image_filename = f"{url_friendly_name}.png"
        full_url = f"{ASSET_BASE_URL}{image_filename}"
        # The key is the original name from the AI, so we can find it later.
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
        // Standard global initialization for maximum stability
        kaboom({{
            width: 800,
            height: 600,
            letterbox: true,
            background: [20, 20, 30],
        }});

        // --- Asset and Item Data (Injected by Backend) ---
        const assets = {assets_json};
        const correctItems = {correct_items_json};
        const incorrectItems = {incorrect_items_json};
        const gameTitle = {title_json};
        const gameInstructions = {instructions_json};

        for (const name in assets) {{
            if (assets[name]) {{
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
            let timer = 20 - level > 5 ? 20 - level : 5;
            const itemsToFind = chooseMultiple(correctItems, Math.min(2 + level, 5));
            let correctTaps = 0;
            
            const scoreLabel = add([ text(`Score: ${{score}}`), pos(24, 24) ]);
            const levelLabel = add([ text(`Level: ${{level}}`), pos(width() / 2, 24), anchor("top") ]);
            const timerLabel = add([ text(`Time: ${{timer.toFixed(1)}}`), pos(width() - 24, 24), anchor("topright") ]);
            add([ text("Find: " + itemsToFind.join(', '), {{ size: 18, width: width() - 40, align: "center" }}), pos(width()/2, 60), anchor("center") ]);
            
            // --- NEW: Grid Logic with Fixed Box Sizes ---
            const gridConf = {{
                level1: {{rows: 2, cols: 3}},
                level2: {{rows: 2, cols: 4}},
                level3: {{rows: 3, cols: 4}},
                level4: {{rows: 3, cols: 5}},
                default: {{rows: 4, cols: 5}},
            }};

            const currentGrid = gridConf[`level${{level}}`] || gridConf.default;
            const boxSize = 110;
            const gap = 15;

            const totalGridWidth = (currentGrid.cols * boxSize) + ((currentGrid.cols - 1) * gap);
            const totalGridHeight = (currentGrid.rows * boxSize) + ((currentGrid.rows - 1) * gap);
            
            const gridOriginX = (width() - totalGridWidth) / 2;
            const gridOriginY = 120;

            const totalSlots = currentGrid.cols * currentGrid.rows;
            const incorrectCount = totalSlots - itemsToFind.length;
            const itemsForGrid = [...itemsToFind, ...chooseMultiple(incorrectItems, incorrectCount)];
            const shuffledItems = itemsForGrid.sort(() => 0.5 - Math.random());
            
            for (let i = 0; i < shuffledItems.length; i++) {{
                const itemName = shuffledItems[i];
                const isCorrect = itemsToFind.includes(itemName);

                const row = Math.floor(i / currentGrid.cols);
                const col = i % currentGrid.cols;

                const x = gridOriginX + col * (boxSize + gap) + boxSize / 2;
                const y = gridOriginY + row * (boxSize + gap) + boxSize / 2;
                
                const box = add([
                    pos(x, y),
                    rect(boxSize, boxSize, {{ radius: 12 }}),
                    color(40, 45, 55),
                    outline(4, color(80, 85, 95)),
                    area(),
                    anchor("center"),
                    "object",
                    {{
                        isCorrect: isCorrect,
                        tapped: false,
                    }}
                ]);

                if (getSprite(itemName)) {{
                    box.add([
                        sprite(itemName, {{ width: boxSize - 20, height: boxSize - 20 }}),
                        anchor("center"),
                    ]);
                }} else {{
                    box.add([
                        text(itemName, {{ size: 16 }}),
                        anchor("center"),
                        color(255, 255, 255),
                    ]);
                }}
            }}
            
            onClick("object", (obj) => {{
                if (obj.tapped) return;

                if (obj.isCorrect) {{
                    obj.tapped = true;
                    obj.color = hsl2rgb(0.33, 0.7, 0.6);
                    burp();
                    correctTaps++;
                    score += 10;
                    scoreLabel.text = `Score: ${{score}}`;

                    if (correctTaps >= itemsToFind.length) {{
                        wait(0.5, () => go("game", {{ level: level + 1, score: score }}));
                    }}
                }} else {{
                    obj.tapped = true;
                    obj.color = hsl2rgb(0, 0.7, 0.6);
                    shake(10);
                    score = Math.max(0, score - 5);
                    scoreLabel.text = `Score: ${{score}}`;
                }}
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
        
        title, instructions, correct_items, incorrect_items = parse_ai_reasoning(reasoning_text)

        if not correct_items or not incorrect_items:
             raise ValueError(f"AI did not return valid item lists. Full response: {reasoning_text}")

        all_game_objects = correct_items + incorrect_items
        asset_urls = get_image_urls(all_game_objects)

        final_html = GAME_HTML_TEMPLATE.format(
            title=title,
            assets_json=json.dumps(asset_urls),
            correct_items_json=json.dumps(correct_items),
            incorrect_items_json=json.dumps(incorrect_items),
            title_json=json.dumps(title),
            instructions_json=json.dumps(instructions)
        )
        
        return reasoning_text, final_html

    except Exception as e:
        logging.error(f"Exception in generate_game_for_topic for topic '{topic}': {e}")
        error_html = f"<h1>Error Generating Game</h1><p>An error occurred: {e}</p><p>Please try a different topic.</p>"
        return f"Internal Server Error: {e}", error_html

