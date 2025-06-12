# game_generator.py

import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import logging

# The large prompt template, containing all game variations, is stored here.
PROMPT_TEMPLATE = """
You are an expert educational game designer and developer. Your task is to generate a complete, single-file HTML game for the topic: "TOPIC_PLACEHOLDER" using the Kaboom.js game engine. The game is a fast-paced "Tap the Right Ones" challenge.

---
### **MANDATORY WORKFLOW**
---
1.  **Analyze Topic & Create Item Lists:**
    * Deeply analyze the topic: **"TOPIC_PLACEHOLDER"**.
    * Your primary task is to generate two distinct lists of items based on this topic:
        1.  **`correctItems`**: A JavaScript array of strings that are correct examples of the topic.
        2.  **`incorrectItems`**: A JavaScript array of strings that are plausible but incorrect examples (distractors).
    * These lists should be rich and varied. Aim for at least 5-10 items in each list if the topic allows.
    * **Example for "Herbivores":**
        * `correctItems`: `["Cow", "Goat", "Rabbit", "Deer", "Sheep", "Horse", "Elephant"]`
        * `incorrectItems`: `["Lion", "Tiger", "Shark", "Wolf", "Fox", "Bear"]`
    * **Example for "Metals":**
        * `correctItems`: `["Gold", "Silver", "Iron", "Copper", "Aluminum", "Steel", "Lead"]`
        * `incorrectItems`: `["Wood", "Glass", "Plastic", "Rubber", "Clay", "Stone"]`

2.  **State Your Item Lists:** At the very beginning of your response, you MUST state the lists you have generated.
    * **Example:** "Correct Items: `[\"Cow\", \"Goat\"]`. Incorrect Items: `[\"Lion\", \"Tiger\"]`."

3.  **Copy & Fill Template:** Copy the entire "Tap the Right Ones" game template below. Your only task is to replace the `/* PLACEHOLDER */` sections with the `correctItems` and `incorrectItems` arrays you just created. DO NOT change any other part of the code.

4.  **Final Output:** Your response must be ONLY the completed, clean HTML code.

---
### **THE "TAP THE RIGHT ONES" GAME TEMPLATE (v4 - FINAL)**
---

```html
<!DOCTYPE html>
<html>
<head>
    <title>Tap the Right Ones</title>
    <style>body, html { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background: #000; }</style>
</head>
<body>
    <script src="[https://unpkg.com/kaboom@3000.0.1/dist/kaboom.js](https://unpkg.com/kaboom@3000.0.1/dist/kaboom.js)"></script>
    <script>
        kaboom({ width: 800, height: 600, letterbox: true, background: [20, 20, 30] });

        // --- 1. DEFINE ITEMS ---
        /* PLACEHOLDER: The AI will define these lists based on its analysis. */
        const correctItems = ["Cow", "Goat", "Rabbit", "Deer", "Zebra", "Horse", "Elephant"];
        const incorrectItems = ["Lion", "Tiger", "Shark", "Wolf", "Fox", "Bear", "Crocodile", "Snake"];
        // --- END OF PLACEHOLDER ---

        // --- Helper function to select multiple unique items from an array ---
        function chooseMultiple(arr, num) {
            const shuffled = [...arr].sort(() => 0.5 - Math.random());
            return shuffled.slice(0, num);
        }

        scene("start", () => {
             add([ text("/* PLACEHOLDER: Game Title */", { size: 50, font: "sans-serif", width: width() - 100 }), pos(width() / 2, height() / 2 - 100), anchor("center"), ]);
             add([ text("/* PLACEHOLDER: Game Instructions */", { size: 24, font: "sans-serif", width: width() - 100 }), pos(width() / 2, height() / 2), anchor("center"), ]);
             add([ text("Click to Start", { size: 32, font: "sans-serif" }), pos(width() / 2, height() / 2 + 100), anchor("center"), ]);
            onClick(() => go("game", { level: 1, score: 0 }));
        });

        scene("game", ({ level, score }) => {
            let timer = 15;
            let correctTaps = 0;
            const numCorrectToSpawn = Math.min(2 + level, correctItems.length);
            const numIncorrectToSpawn = 2 + level;

            const scoreLabel = add([ text(`Score: ${score}`), pos(24, 24), { layer: "ui" } ]);
            const timerLabel = add([ text(`Time: ${timer.toFixed(1)}`), pos(width() - 24, 24), anchor("topright"), { layer: "ui" } ]);
            const levelLabel = add([ text(`Level: ${level}`), pos(width() / 2, 24), anchor("top"), { layer: "ui" } ]);

            const speed = 50 + (level * 10);
            const itemColor = color(220, 220, 220); // Uniform color for all items

            // Function to spawn a single item
            function spawnItem(itemName, itemTag) {
                const item = add([
                    rect(120, 50, { radius: 8 }),
                    pos(rand(80, width() - 80), rand(80, height() - 80)),
                    itemColor,
                    area(),
                    anchor("center"),
                    move(choose([LEFT, RIGHT, UP, DOWN]), speed), // Start moving in a random direction
                    "item",
                    itemTag
                ]);
                item.add([ text(itemName, { size: 16, width: 110 }), anchor("center"), color(0,0,0) ]);
            }

            // Spawn Correct Items
            const itemsToFind = chooseMultiple(correctItems, numCorrectToSpawn);
            itemsToFind.forEach(name => spawnItem(name, "correct"));
            
            // Spawn Incorrect Items
            const incorrectToSpawn = chooseMultiple(incorrectItems, numIncorrectToSpawn);
            incorrectToSpawn.forEach(name => spawnItem(name, "incorrect"));
            
            onClick("correct", (item) => {
                destroy(item);
                score += 10;
                correctTaps++;
                scoreLabel.text = `Score: ${score}`;
                addKaboom(item.pos);
                if (correctTaps >= numCorrectToSpawn) {
                    go("game", { level: level + 1, score: score });
                }
            });

            onClick("incorrect", (item) => {
                shake(15);
                score -= 5;
                scoreLabel.text = `Score: ${score}`;
                add([
                    text("-5", { size: 24 }),
                    pos(item.pos),
                    lifespan(1, { fade: 0.5 }),
                    anchor("center"),
                    color(255, 0, 0)
                ]);
            });

            // --- NEW: Rebounding Logic ---
            onUpdate("item", (item) => {
                if (item.pos.x < 0 || item.pos.x > width()) {
                    item.vel = item.vel.scale(-1);
                }
                if (item.pos.y < 80 || item.pos.y > height()) {
                   item.vel = item.vel.scale(-1);
                }
            });
            
            onUpdate(() => {
                timer -= dt();
                timerLabel.text = `Time: ${timer.toFixed(1)}`;
                if (timer <= 0) {
                    go("end", { finalScore: score });
                }
            });
        });

        scene("end", ({ finalScore }) => {
            add([ text("Time's Up!", { size: 60 }), pos(width()/2, height()/2 - 80), anchor("center") ]);
            add([ text(`Final Score: ${finalScore}`, { size: 40 }), pos(width() / 2, height() / 2), anchor("center"), ]);
            add([ text("Click to play again", { size: 24 }), pos(width() / 2, height() / 2 + 80), anchor("center"), ]);
            onClick(() => go("start"));
        });
        
        go("start");
    </script>
</body>
</html>
```
"""

def generate_game_for_topic(topic: str):
    """
    Generates game HTML by calling the Gemini API.

    Args:
        topic: The user-provided topic for the game.

    Returns:
        A tuple containing (reasoning, game_html).
        Returns (None, None) on failure.
    """
    try:
        prompt = PROMPT_TEMPLATE.replace("TOPIC_PLACEHOLDER", topic)

        gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')
        safety_settings = {HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE}
        
        response = gemini_model.generate_content(prompt, safety_settings=safety_settings)
        
        generated_text = response.text.strip()
        
        # Isolate the HTML part from the reasoning part
        html_start_index = generated_text.find('<!DOCTYPE html>')
        if html_start_index == -1:
            html_start_index = generated_text.find('<')

        if html_start_index != -1:
            reasoning = generated_text[:html_start_index].strip()
            generated_html = generated_text[html_start_index:]

            # Clean up markdown fences if they exist
            if generated_html.startswith("```html"):
                generated_html = generated_html[7:].strip()
            if generated_html.endswith("```"):
                generated_html = generated_html[:-3].strip()
            
            return reasoning, generated_html
        else:
            # AI failed to return valid HTML
            logging.error(f"AI failed to generate valid HTML for topic '{topic}'")
            return "HTML Generation Error", f"<p>Error: AI did not generate valid HTML. Full response: {generated_text}</p>"

    except Exception as e:
        logging.error(f"Exception in generate_game_for_topic for topic '{topic}': {e}")
        return "Internal Server Error", f"<p>An exception occurred: {e}</p>"
