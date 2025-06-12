# game_generator.py

import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import logging

# The large prompt template, containing all game variations, is stored here.
PROMPT_TEMPLATE = """
You are an expert educational game designer and developer. Your task is to generate a complete, single-file HTML game for the topic: "TOPIC_PLACEHOLDER" using the Kaboom.js game engine and a pre-defined library of sprite assets. Your primary goal is to master dynamic asset loading and create engaging gameplay with effects.

---
### **MANDATORY WORKFLOW**
---
1.  **Analyze Topic & Plan Gameplay:**
    * Deeply analyze the topic: **"TOPIC_PLACEHOLDER"**.
    * Is the core mechanic about **collecting/avoiding** (suitable for the Collector Game) or **gathering ingredients to craft something** (suitable for the Crafting Game)?
    * Based on the topic, define a list of specific, named items. For example:
        * **For "Herbivores" (Collector Game):** The player is a 'player_char'. Good items are plants like `[{ name: "Carrot", sprite: "item_heart" }, { name: "Lettuce", sprite: "item_key" }]`. Bad items are meat like `[{ name: "Steak", sprite: "enemy_1" }, { name: "Drumstick", sprite: "enemy_2" }]`.
        * **For "Photosynthesis" (Crafting Game):** This is about crafting Glucose. The required ingredients are `[{ name: "Sunlight", sprite: "item_diamond", key: "sun" }, { name: "Water", sprite: "item_key", key: "water" }]`. The player must also avoid pests like `[{ name: "Pest", sprite: "enemy_1" }]`.

2.  **Choose ONE Template:** Review the TWO Kaboom.js game templates below. Choose the single most appropriate template for your gameplay plan.

3.  **State Your Choice & Asset Plan:** At the very beginning of your response, you MUST state your template choice and your detailed asset plan.
    * **Example:** "The topic is 'Herbivores', which is about collecting good food and avoiding bad things. I will use Template B: The Collector Game. Assets: Player -> 'player_char', Good Items -> `[{ name: "Carrot", sprite: "item_heart" }]`, Bad Items -> `[{ name: "Steak", sprite: "enemy_1" }]`."

4.  **Copy & Fill:** Copy the entire code for your chosen template. Fill in the `/* PLACEHOLDER */` sections with your game logic, including the specific item lists you planned.

5.  **Add "Juice" (Effects):** Make the game feel alive. Use effects on interaction. On collection, use `addKaboom(pos)`. On penalty, use `shake()`.

6.  **Final Output:** Your entire response must be ONLY the completed, clean HTML code.

---
### **ASSET LIBRARY (Using your GitHub URLs)**
---
*You MUST use these asset keys and URLs. Do not invent new ones.*
-   `player_char`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/player.png"
-   `enemy_1`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/enemey1.png"
-   `enemy_2`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/enemey2.png"
-   `item_coin`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/coin.png"
-   `item_diamond`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/diamond.png"
-   `item_key`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/key.png"
-   `item_heart`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/heart.png"

---
### **TEMPLATE LIBRARY (DEBUG LABELS & SPECIFIC ITEMS EDITION)**
---

#### **TEMPLATE B: THE KABOOM COLLECTOR GAME (WITH SPRITES)**
* **Best for:** Topics about collecting good things and avoiding bad things.

```html
<!-- TEMPLATE B: KABOOM COLLECTOR GAME (WITH SPRITES)-->
<!DOCTYPE html>
<html>
<head>
    <title>Collector</title>
    <style>body, html { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background: #000; }</style>
</head>
<body>
    <script src="[https://unpkg.com/kaboom@3000.0.1/dist/kaboom.js](https://unpkg.com/kaboom@3000.0.1/dist/kaboom.js)"></script>
    <script>
        kaboom({ width: 800, height: 600, letterbox: true, background: [135, 206, 235] });

        // --- 1. DEFINE ASSETS & RULES ---
        /* PLACEHOLDER: Define your assets and game rules based on the topic. */
        const PLAYER_SPRITE = "player_char";
        const GOOD_ITEMS = [ { name: "Carrot", sprite: "item_heart" }, { name: "Salad", sprite: "item_key" } ];
        const BAD_ITEMS = [ { name: "Meat", sprite: "enemy_1" }, { name: "Poison", sprite: "enemy_2" } ];
        const GAME_DURATION = 30;
        
        loadSprite(PLAYER_SPRITE, `https://raw.githack.com/brainboyai/tiny-tutor-assets/main/${PLAYER_SPRITE}.png`);
        GOOD_ITEMS.forEach(item => loadSprite(item.sprite, `https://raw.githack.com/brainboyai/tiny-tutor-assets/main/${item.sprite}.png`));
        BAD_ITEMS.forEach(item => loadSprite(item.sprite, `https://raw.githack.com/brainboyai/tiny-tutor-assets/main/${item.sprite}.png`));
        // --- END OF PLACEHOLDER ---

        scene("start", () => {
             add([ text("/* PLACEHOLDER: Game Title */", { size: 50, font: "sans-serif", width: width() - 100 }), pos(width() / 2, height() / 2 - 100), anchor("center"), ]);
             add([ text("/* PLACEHOLDER: Game Instructions */", { size: 24, font: "sans-serif", width: width() - 100 }), pos(width() / 2, height() / 2), anchor("center"), ]);
             add([ text("Click to Start", { size: 32, font: "sans-serif" }), pos(width() / 2, height() / 2 + 100), anchor("center"), ]);
            onClick(() => go("game"));
        });

        scene("game", () => {
            let score = 0;
            const scoreLabel = add([ text("Score: 0", { size: 32, font: "sans-serif" }), pos(24, 24) ]);
            const timerLabel = add([ text("Time: " + GAME_DURATION, { size: 32, font: "sans-serif" }), pos(width() - 24, 24), anchor("topright") ]);
            
            const player = add([ sprite(PLAYER_SPRITE), pos(width() / 2, height() - 80), area(), anchor("center"), scale(2.5), "player" ]);

            onUpdate(() => { player.pos.x = mousePos().x; });

            loop(0.8, () => {
                const isGood = rand() > 0.3;
                const itemData = isGood ? choose(GOOD_ITEMS) : choose(BAD_ITEMS);
                const itemTag = isGood ? "good" : "bad";
                
                const item = add([ sprite(itemData.sprite), pos(rand(0, width()), -60), move(DOWN, 280), area(), offscreen({ destroy: true }), itemTag, scale(2), "item" ]);
                item.add([ text(itemData.name, { size: 12 }), color(0,0,0), anchor("center"), pos(0, -25) ]);
            });

            onCollide("player", "good", (p, good) => {
                destroy(good);
                score += 10;
                scoreLabel.text = `Score: ${score}`;
                addKaboom(good.pos);
            });
            
            onCollide("player", "bad", (p, bad) => {
                destroy(bad);
                score -= 5;
                scoreLabel.text = `Score: ${score}`;
                shake(12);
            });
            
            let time = GAME_DURATION;
            onUpdate(() => {
                time -= dt();
                timerLabel.text = `Time: ${time.toFixed(0)}`;
                if (time <= 0) { go("end", { finalScore: score }); }
            });
        });

        scene("end", ({ finalScore }) => {
            add([ text(`Final Score: ${finalScore}`, { size: 50, font: "sans-serif" }), pos(width() / 2, height() / 2 - 50), anchor("center"), ]);
            add([ text("Click to play again", { size: 24, font: "sans-serif" }), pos(width() / 2, height() / 2 + 20), anchor("center"), ]);
            onClick(() => go("start"));
        });
        
        go("start");
    </script>
</body>
</html>
```
---
#### **TEMPLATE C: THE KABOOM CRAFTING GAME**
* **Best for:** Multi-step processes, cycles (e.g., Photosynthesis, Digestion).
* **Gameplay:** Player (bottom of screen) moves to collect falling ingredient sprites to craft a product, while avoiding enemies.

```html
<!DOCTYPE html>
<html>
<head>
    <title>Crafting</title>
    <style>body, html { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background: #000; }</style>
</head>
<body>
    <script src="[https://unpkg.com/kaboom@3000.0.1/dist/kaboom.js](https://unpkg.com/kaboom@3000.0.1/dist/kaboom.js)"></script>
    <script>
        kaboom({ width: 800, height: 600, letterbox: true, background: [135, 206, 250] });

        // --- 1. DEFINE RECIPE, GOAL, & ASSETS ---
        /* PLACEHOLDER: Define your recipe, product, and enemies based on the topic. */
        const RECIPE = {
            sun: { name: "Sunlight", sprite: "item_diamond", required: 3 },
            water: { name: "Water", sprite: "item_key", required: 2 },
        };
        const PRODUCT = { name: "Glucose", goal: 5 };
        const ENEMIES = [ { name: "Pest", sprite: "enemy_1" } ];

        // Auto-load all necessary sprites
        loadSprite("player_char", "[https://raw.githack.com/brainboyai/tiny-tutor-assets/main/player.png](https://raw.githack.com/brainboyai/tiny-tutor-assets/main/player.png)");
        ENEMIES.forEach(item => loadSprite(item.sprite, `https://raw.githack.com/brainboyai/tiny-tutor-assets/main/${item.sprite}.png`));
        for (const key in RECIPE) {
            loadSprite(RECIPE[key].sprite, `https://raw.githack.com/brainboyai/tiny-tutor-assets/main/${RECIPE[key].sprite}.png`);
        }
        // --- END OF PLACEHOLDER ---
        
        const ingredientKeys = Object.keys(RECIPE);
        
        scene("start", () => {
             add([ text("/* PLACEHOLDER: Game Title */", { size: 50, width: width() - 100 }), pos(center().x, height() / 2 - 100), anchor("center"), ]);
             add([ text("/* PLACEHOLDER: Game Instructions */", { size: 24, width: width() - 100 }), pos(center().x, height() / 2), anchor("center"), ]);
             add([ text("Click to Start", { size: 32 }), pos(center().x, height() / 2 + 100), anchor("center"), ]);
            onClick(() => go("game"));
        });

        scene("game", () => {
            let inventory = {};
            ingredientKeys.forEach(key => inventory[key] = 0);
            let productsMade = 0;
            
            const player = add([ sprite("player_char"), pos(width()/2, height() - 60), area(), anchor("center"), scale(2.5), "player" ]);
            player.add([ text("Plant", { size: 10 }), pos(0, -30), anchor("center"), color(0,0,0) ]);
            onUpdate(() => { player.pos.x = mousePos().x; });

            const meterWidth = 150, meterHeight = 16, meterGap = 20;
            const totalMetersWidth = ingredientKeys.length * (meterWidth + meterGap) - meterGap;
            const startX = (width() - totalMetersWidth) / 2;
            ingredientKeys.forEach((key, i) => {
                const ing = RECIPE[key];
                const meterX = startX + i * (meterWidth + meterGap);
                add([ text(ing.name, { size: 16 }), pos(meterX, 20) ]);
                add([ rect(meterWidth, meterHeight, { radius: 4 }), color(80, 80, 80), pos(meterX, 45) ]);
                add([ rect(0, meterHeight, { radius: 4 }), color(255, 255, 255), pos(meterX, 45), `meter_${key}` ]);
            });
            const productLabel = add([ text(`${PRODUCT.name}: 0/${PRODUCT.goal}`, { size: 24 }), pos(width() - 40, 40), anchor("topright") ]);

            // Game Loops
            loop(1.2, () => {
                const key = choose(ingredientKeys);
                const ing = RECIPE[key];
                const item = add([ sprite(ing.sprite), pos(rand(0, width()), -60), move(DOWN, 150), area(), offscreen({ destroy: true }), scale(2), "ingredient", { type: key } ]);
                item.add([text(ing.name, {size: 10}), color(0,0,0), anchor("center"), pos(0, -25)]);
            });
            loop(2.5, () => { 
                const enemyData = choose(ENEMIES);
                const enemy = add([ sprite(enemyData.sprite), pos(rand(0, width()), -60), move(DOWN, 200), area(), offscreen({ destroy: true }), scale(2.5), "enemy" ]); 
                enemy.add([text(enemyData.name, {size: 10}), color(255,0,0), anchor("center"), pos(0, -25)]);
            });

            onCollide("player", "ingredient", (p, ing) => {
                const key = ing.type;
                if (inventory[key] < RECIPE[key].required) {
                    inventory[key]++;
                    updateMeters();
                    checkRecipe();
                }
                destroy(ing);
                addKaboom(ing.pos);
            });

            onCollide("player", "enemy", (p, enemy) => {
                go("end", { success: false, finalScore: productsMade });
            });

            function updateMeters() {
                 ingredientKeys.forEach((key) => {
                    const meter = get(`meter_${key}`)[0];
                    meter.width = (inventory[key] / RECIPE[key].required) * meterWidth;
                 });
            }

            function checkRecipe() {
                const canMake = ingredientKeys.every(key => inventory[key] >= RECIPE[key].required);
                if (canMake) {
                    ingredientKeys.forEach(key => inventory[key] = 0);
                    productsMade++;
                    productLabel.text = `${PRODUCT.name}: ${productsMade} / ${PRODUCT.goal}`;
                    updateMeters();
                    if (productsMade >= PRODUCT.goal) {
                        go("end", { success: true, finalScore: productsMade });
                    }
                }
            }
        });
        
        scene("end", ({ success, finalScore }) => {
            add([ text(success ? "Process Complete!" : "Game Over!", { size: 50 }), pos(center()), anchor("center") ]);
            add([ text(`You made ${finalScore} ${PRODUCT.name}(s)!`, { size: 24 }), pos(width() / 2, height() / 2 + 50), anchor("center") ]);
            add([ text("Click to restart", { size: 20 }), pos(width() / 2, height() / 2 + 100), anchor("center") ]);
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
