# game_generator.py

import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import logging

# The large prompt template, containing all game variations, is stored here.
PROMPT_TEMPLATE = """
You are an expert educational game designer and developer. Your task is to generate a complete, single-file HTML game for the topic: "TOPIC_PLACEHOLDER" using the Kaboom.js game engine and the MASTER ASSET LIBRARY provided below.

---
### **MANDATORY WORKFLOW**
---
1.  **Analyze Topic & Create Asset Plan:**
    * Deeply analyze the topic: **"TOPIC_PLACEHOLDER"**.
    * This game is an endless "Swerve Runner". You must define three categories of objects:
        1.  **Player:** The character the user controls. Select the most thematic sprite.
        2.  **Good Items:** Things the player should collect. These increase the score. Select a variety of logical items from the library.
        3.  **Bad Items:** Things the player must avoid. These decrease lives. Select a variety of logical items from the library.
    * Create a detailed "Asset Plan" by selecting the most appropriate sprite keys from the MASTER ASSET LIBRARY.
    * **Example Asset Plan for "Herbivores":**
        * **Player Sprite Key:** `player_char`
        * **Good Item Keys:** `["veg_carrot", "veg_lettuce", "veg_broccoli", "veg_apple"]`
        * **Bad Item Keys:** `["meat_steak", "food_fish", "meat_chicken", "food_egg"]`

2.  **State Your Asset Plan:** At the very beginning of your response, you MUST state your complete Asset Plan.
    * **Example:** "Asset Plan: Player -> 'player_char'. Good Items -> `['veg_carrot', 'veg_lettuce']`. Bad Items -> `['meat_steak', 'meat_chicken']`."

3.  **Copy & Fill Template:** Copy the entire Swerve Runner template below. Fill in the `/* PLACEHOLDER */` sections using ONLY the asset keys from your plan. DO NOT change any other part of the code.

4.  **Final Output:** Your response must be ONLY the completed, clean HTML code.

---
### **MASTER ASSET LIBRARY**
---
*This is the definitive library of assets. The keys map to the direct URLs of the images in the GitHub repository. You must use these exact keys.*
-   `player_char`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/player.png"
-   `plant_tree`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/Tree1.png"
-   `plant_palm`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/Palm_tree.png"
-   `env_sun`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/Sun.png"
-   `env_water`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/WaterDroplet.png"
-   `veg_apple`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/apple.png"
-   `veg_apple_half`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/apple-half.png"
-   `veg_artichoke`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/artichoke.png"
-   `veg_asparagus`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/asparagus.png"
-   `veg_avocado`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/avocado.png"
-   `veg_avocado_half`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/advocado-half.png"
-   `meat_bacon`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/bacon.png"
-   `veg_banana`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/banana.png"
-   `veg_beans`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/beans.png"
-   `veg_beet`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/beet.png"
-   `veg_beetroot`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/beetroot.png"
-   `food_bread`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/bread.png"
-   `veg_broccoli`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/broccoli.png"
-   `veg_brinjal`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/brinjal.png"
-   `veg_cabbage`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/cabbage.png"
-   `veg_capsicum`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/capsicum.png"
-   `veg_carrot`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/carrot.png"
-   `veg_cauliflower`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/cauliflower.png"
-   `food_cheese`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/cheese.png"
-   `food_chocolate`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/chocolate.png"
-   `food_cookie`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/cookie.png"
-   `veg_corn`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/corn.png"
-   `veg_cucumber`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/cucumber.png"
-   `food_egg`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/egg.png"
-   `veg_eggplant`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/eggplant.png"
-   `food_fish`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/fish.png"
-   `veg_garlic`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/garlic.png"
-   `veg_grapes`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/grapes.png"
-   `veg_lettuce`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/lettuce.png"
-   `meat_steak`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/steak.png"
-   `veg_tomato`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/tomato.png"
-   `meat_chicken`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/roastedchicken.png"
-   `food_omlet`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/omlet.png"
-   `veg_onion`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/onion.png"
-   `veg_orange`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/orange.png"
-   `veg_potato`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/potato.png"
-   `veg_pumpkin`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/pumpkin.png"
-   `veg_radish`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/radish.png"
-   `veg_strawberry`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/strawberry.png"
-   `veg_sweetpotato`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/sweetpotato.png"
-   `meat_turkey`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/turkey.png"
-   `veg_turnip`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/turnip.png"
-   `meat_ham`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/whole-ham.png"

---
### **THE "SWERVE RUNNER" GAME TEMPLATE**
---

```html
<!DOCTYPE html>
<html>
<head>
    <title>Swerve Runner</title>
    <style>body, html { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background: #000; }</style>
</head>
<body>
    <script src="[https://unpkg.com/kaboom@3000.0.1/dist/kaboom.js](https://unpkg.com/kaboom@3000.0.1/dist/kaboom.js)"></script>
    <script>
        kaboom({ width: 800, height: 600, letterbox: true, background: [135, 206, 235] });

        // --- 1. DEFINE & LOAD ASSETS ---
        /* This is the master library of all available assets. Do not change this. */
        const MASTER_ASSETS = {
            "player_char": "[https://raw.githack.com/brainboyai/tiny-tutor-assets/main/player.png](https://raw.githack.com/brainboyai/tiny-tutor-assets/main/player.png)",
            "plant_tree": "[https://raw.githack.com/brainboyai/tiny-tutor-assets/main/Tree1.png](https://raw.githack.com/brainboyai/tiny-tutor-assets/main/Tree1.png)",
            "env_sun": "[https://raw.githack.com/brainboyai/tiny-tutor-assets/main/Sun.png](https://raw.githack.com/brainboyai/tiny-tutor-assets/main/Sun.png)",
            "env_water": "[https://raw.githack.com/brainboyai/tiny-tutor-assets/main/WaterDroplet.png](https://raw.githack.com/brainboyai/tiny-tutor-assets/main/WaterDroplet.png)",
            "veg_apple": "[https://raw.githack.com/brainboyai/tiny-tutor-assets/main/apple.png](https://raw.githack.com/brainboyai/tiny-tutor-assets/main/apple.png)",
            "veg_carrot": "[https://raw.githack.com/brainboyai/tiny-tutor-assets/main/carrot.png](https://raw.githack.com/brainboyai/tiny-tutor-assets/main/carrot.png)",
            "veg_broccoli": "[https://raw.githack.com/brainboyai/tiny-tutor-assets/main/broccoli.png](https://raw.githack.com/brainboyai/tiny-tutor-assets/main/broccoli.png)",
            "veg_lettuce": "[https://raw.githack.com/brainboyai/tiny-tutor-assets/main/lettuce.png](https://raw.githack.com/brainboyai/tiny-tutor-assets/main/lettuce.png)",
            "meat_steak": "[https://raw.githack.com/brainboyai/tiny-tutor-assets/main/steak.png](https://raw.githack.com/brainboyai/tiny-tutor-assets/main/steak.png)",
            "meat_chicken": "[https://raw.githack.com/brainboyai/tiny-tutor-assets/main/roastedchicken.png](https://raw.githack.com/brainboyai/tiny-tutor-assets/main/roastedchicken.png)",
            "food_fish": "[https://raw.githack.com/brainboyai/tiny-tutor-assets/main/fish.png](https://raw.githack.com/brainboyai/tiny-tutor-assets/main/fish.png)",
            "food_egg": "[https://raw.githack.com/brainboyai/tiny-tutor-assets/main/egg.png](https://raw.githack.com/brainboyai/tiny-tutor-assets/main/egg.png)",
        };

        /* PLACEHOLDER: The AI will define these lists of sprite keys based on its Asset Plan. */
        const PLAYER_SPRITE_KEY = "player_char";
        const GOOD_ITEM_KEYS = ["veg_carrot", "veg_apple", "veg_lettuce"];
        const BAD_ITEM_KEYS = ["meat_steak", "meat_chicken"];
        
        // Load all needed assets from the master library
        const assetPromises = [];
        assetPromises.push(loadSprite(PLAYER_SPRITE_KEY, MASTER_ASSETS[PLAYER_SPRITE_KEY]));
        GOOD_ITEM_KEYS.forEach(key => assetPromises.push(loadSprite(key, MASTER_ASSETS[key])));
        BAD_ITEM_KEYS.forEach(key => assetPromises.push(loadSprite(key, MASTER_ASSETS[key])));
        // --- END OF PLACEHOLDER ---

        scene("start", async () => {
            // Wait for all assets to load before showing the start screen
            await Promise.all(assetPromises);

            add([ text("/* PLACEHOLDER: Game Title */", { size: 50, font: "sans-serif", width: width() - 100 }), pos(width() / 2, 80), anchor("center"), ]);
            
            // On-screen debug info
            add([ text("AI Asset Plan:", { size: 18 }), pos(20, 180) ]);
            add([ text("Good Items:", { size: 16 }), pos(20, 210) ]);
            add([ text(GOOD_ITEM_KEYS.join(", "), { size: 14, width: width() - 40 }), pos(20, 230) ]);
            add([ text("Bad Items:", { size: 16 }), pos(20, 280) ]);
            add([ text(BAD_ITEM_KEYS.join(", "), { size: 14, width: width() - 40 }), pos(20, 300) ]);

            add([ text("Click to Start", { size: 32, font: "sans-serif" }), pos(width() / 2, height() - 80), anchor("center"), ]);

            onClick(() => go("game"));
        });

        scene("game", () => {
            let score = 0;
            let lives = 3;
            let speed = 120;

            const scoreLabel = add([ text("Score: 0", { size: 32 }), pos(24, 24) ]);
            const livesLabel = add([ text("Lives: 3", { size: 32 }), pos(width() - 24, 24), anchor("topright") ]);
            
            const player = add([ sprite(PLAYER_SPRITE_KEY), pos(width() / 2, height() - 80), area(), anchor("center"), scale(1.5), "player" ]);

            onUpdate(() => {
                player.pos.x = lerp(player.pos.x, mousePos().x, 0.1);
            });

            loop(1, () => {
                speed = 120 + (score * 2); // Progressive difficulty
                const isGood = rand() > 0.4;
                const itemKey = isGood ? choose(GOOD_ITEM_KEYS) : choose(BAD_ITEM_KEYS);
                const itemTag = isGood ? "good" : "bad";
                
                add([
                    sprite(itemKey),
                    pos(rand(0, width()), -60),
                    move(DOWN, speed),
                    area(),
                    offscreen({ destroy: true }),
                    itemTag,
                    scale(1.5),
                    "item"
                ]);
            });

            onCollide("player", "good", (p, good) => {
                destroy(good);
                score += 10;
                scoreLabel.text = `Score: ${score}`;
                addKaboom(good.pos);
            });
            
            onCollide("player", "bad", (p, bad) => {
                destroy(bad);
                lives--;
                livesLabel.text = `Lives: ${lives}`;
                shake(20);
                if (lives <= 0) {
                    go("end", { finalScore: score });
                }
            });
        });

        scene("end", ({ finalScore }) => {
            add([ text("Game Over", { size: 60 }), pos(width()/2, height()/2 - 80), anchor("center") ]);
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
