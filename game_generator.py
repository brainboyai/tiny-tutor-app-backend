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
    """
    image_urls = {}
    for name in object_names:
        if not name or not isinstance(name, str):
            continue
        
        url_friendly_name = quote(name.strip())
        image_filename = f"{url_friendly_name}.png"
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
        // *** FIX: Initialize Kaboom into a context object 'k' ***
        const k = kaboom({{
            width: 800,
            height: 600,
            letterbox: true,
            background: [20, 20, 30],
            global: false // Explicitly disable global injection
        }});

        // *** FIX: Call all Kaboom functions as methods of the context object 'k' ***
        k.layers(["obj", "ui"], "obj");

        const assets = {assets_json};
        const correctItems = {correct_items_json};
        const incorrectItems = {incorrect_items_json};
        const gameTitle = {title_json};
        const gameInstructions = {instructions_json};

        for (const name in assets) {{
            if (assets[name]) {{
                try {{
                    k.loadSprite(name, assets[name], {{ crossOrigin: "anonymous" }});
                }} catch (e) {{
                    console.error(`Could not load sprite for ${{name}} from ${{assets[name]}}`, e);
                }}
            }}
        }}
        
        function chooseMultiple(arr, num) {{
            const shuffled = [...arr].sort(() => 0.5 - Math.random());
            return shuffled.slice(0, num);
        }}

        k.scene("start", () => {{
             k.add([ k.text(gameTitle, {{ size: 48, font: "sans-serif", width: k.width() - 100 }}), k.pos(k.width() / 2, k.height() / 2 - 120), k.anchor("center") ]);
             k.add([ k.text(gameInstructions, {{ size: 22, font: "sans-serif", width: k.width() - 100 }}), k.pos(k.width() / 2, k.height() / 2 - 20), k.anchor("center") ]);
             k.add([ k.text("Click to Start", {{ size: 32, font: "sans-serif" }}), k.pos(k.width() / 2, k.height() / 2 + 80), k.anchor("center") ]);
            k.onClick(() => k.go("game", {{ level: 1, score: 0 }}));
        }});

        k.scene("game", ({{ level, score }}) => {{
            let timer = 15;
            const itemsToFind = chooseMultiple(correctItems, Math.min(2 + level, correctItems.length));
            let correctTaps = 0;
            
            function makeUIPanel(p, icon, initialText) {{
                const panel = k.add([
                    k.rect(180, 40, {{ radius: 8 }}),
                    k.pos(p),
                    k.anchor("center"),
                    k.color(10, 10, 15),
                    k.outline(2, k.color(80, 85, 95)),
                    k.layer("ui")
                ]);
                panel.add([
                    k.text(icon, {{ size: 20 }}),
                    k.pos(-65, 0),
                    k.anchor("center"),
                ]);
                const label = panel.add([
                    k.text(initialText, {{ size: 20, font: "sans-serif"}}),
                    k.pos(15, 0),
                    k.anchor("center"),
                ]);
                return label;
            }}

            const scoreLabel = makeUIPanel(k.vec2(110, 40), "⭐", `Score: ${{score}}`);
            const levelLabel = makeUIPanel(k.vec2(k.width() / 2, 40), "📈", `Level: ${{level}}`);
            const timerLabel = makeUIPanel(k.vec2(k.width() - 110, 40), "⏱️", `Time: ${{timer.toFixed(1)}}`);
            
            k.add([ k.text("Find: " + itemsToFind.join(', '), {{ size: 18, width: k.width() - 40, align: "center" }}), k.pos(k.width()/2, 85), k.anchor("center"), k.layer("ui")]);

            function spawnObject(itemName, itemTag) {{
                const speed = 80 + (level * 15);
                const objectSize = {{ w: 100, h: 100 }};
                
                const parentObj = k.add([
                    k.pos(k.rand(objectSize.w, k.width() - objectSize.w), k.rand(140, k.height() - objectSize.h)),
                    k.rect(objectSize.w, objectSize.h, {{ radius: 12 }}),
                    k.color(40, 45, 55),
                    k.outline(4, k.color(80, 85, 95)),
                    k.area(),
                    k.anchor("center"),
                    k.layer("obj"),
                    "object",
                    itemTag,
                    {{ 
                        name: itemName,
                        vel: k.vec2(k.rand(-1, 1), k.rand(-1, 1)).unit().scale(speed)
                    }}
                ]);

                if (k.getSprite(itemName)) {{
                    parentObj.add([
                        k.sprite(itemName, {{ width: objectSize.w - 20, height: objectSize.h - 20 }}),
                        k.anchor("center")
                    ]);
                }} else {{
                    parentObj.add([
                        k.text(itemName, {{ size: 16, width: objectSize.w - 10, align: "center" }}),
                        k.anchor("center")
                    ]);
                }}
            }}

            itemsToFind.forEach(name => spawnObject(name, "correct"));
            chooseMultiple(incorrectItems, 2 + level).forEach(name => spawnObject(name, "incorrect"));
            
            k.onClick("correct", (item) => {{
                if (itemsToFind.includes(item.name) && !item.isAnimating) {{
                    item.isAnimating = true;
                    k.play("powerUp", {{ volume: 0.5 }});
                    
                    k.add([
                        k.rect(item.width, item.height, {{ radius: 12 }}),
                        k.pos(item.pos),
                        k.anchor("center"),
                        k.color(0, 255, 0),
                        k.opacity(0.8),
                        k.lifespan(0.3, {{ fade: 0.3 }}),
                        k.layer("ui")
                    ]);
                    
                    for (let i = 0; i < 15; i++) {{
                        k.add([
                            k.pos(item.pos),
                            k.rect(k.rand(3, 8), k.rand(3, 8)),
                            k.color(120, 255, 120),
                            k.lifespan(0.4, {{ fade: 0.4 }}),
                            k.move(k.rand(0, 360), k.rand(50, 150)),
                            k.layer("ui")
                        ]);
                    }}

                    k.tween(item.scale, k.vec2(0), 0.3, (s) => item.scale = s).onEnd(() => k.destroy(item));
                    
                    score += 10;
                    correctTaps++;
                    scoreLabel.text = `Score: ${{score}}`;

                    if (correctTaps >= itemsToFind.length) {{
                        k.wait(1, () => k.go("game", {{ level: level + 1, score: score }}));
                    }}
                }}
            }});

            k.onClick("incorrect", (item) => {{
                if (item.isAnimating) return;
                k.play("hit", {{ volume: 0.5 }});
                k.shake(15);
                
                k.add([
                    k.rect(item.width, item.height, {{ radius: 12 }}),
                    k.pos(item.pos),
                    k.anchor("center"),
                    k.color(255, 0, 0),
                    k.opacity(0.7),
                    k.lifespan(0.4, {{ fade: 0.4 }}),
                    k.layer("ui")
                ]);

                score = Math.max(0, score - 5);
                scoreLabel.text = `Score: ${{score}}`;
            }});

            k.onUpdate("object", (item) => {{
                item.move(item.vel);
                if (item.pos.x < item.width / 2 || item.pos.x > k.width() - item.width / 2) {{
                    item.vel.x = -item.vel.x;
                }}
                if (item.pos.y < 120 || item.pos.y > k.height() - item.height / 2) {{
                    item.vel.y = -item.vel.y;
                }}
            }});
            
            k.onUpdate(() => {{
                timer -= k.dt();
                timerLabel.text = `Time: ${{timer.toFixed(1)}}`;
                if (timer <= 0) {{
                    k.go("end", {{ finalScore: score }});
                }}
            }});
        }});

        k.scene("end", ({{ finalScore }}) => {{
            k.add([ k.text("Time's Up!", {{ size: 60 }}), k.pos(k.width()/2, k.height()/2 - 80), k.anchor("center") ]);
            k.add([ k.text(`Final Score: ${{finalScore}}`, {{ size: 40 }}), k.pos(k.width() / 2, k.height() / 2), k.anchor("center"), ]);
            k.add([ k.text("Click to play again", {{ size: 24 }}), k.pos(k.width() / 2, k.height() / 2 + 80), k.anchor("center"), ]);
            k.onClick(() => k.go("start"));
        }});
        
        k.go("start");
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

