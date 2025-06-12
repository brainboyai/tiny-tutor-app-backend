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
    * Based on the topic, define the key game elements. For example:
        * **For "Herbivores":** The player is a 'player_char'. Good items are plants like `[{ name: "Carrot", sprite: "veg_carrot" }, { name: "Lettuce", sprite: "veg_lettuce" }]`. Bad items are meat like `[{ name: "Steak", sprite: "meat_steak" }, { name: "Fish", sprite: "food_fish" }]`.
        * **For "Photosynthesis":** This is about crafting. The player is a 'plant_tree'. The required ingredients are `[{ name: "Sun", sprite: "env_sun", key: "sun" }, { name: "Water", sprite: "env_water", key: "water" }]`. The player must also avoid pests like `[{ name: "Pest", sprite: "enemy_1" }]`.

2.  **Choose ONE Template:** Review the TWO Kaboom.js game templates below. Choose the single most appropriate template for your gameplay plan.

3.  **State Your Choice & Asset Plan:** At the very beginning of your response, you MUST state your template choice and your detailed asset plan.
    * **Example:** "The topic is 'Herbivores'. This is about collecting good food and avoiding bad things. I will use Template B: The Collector Game. Asset Plan: Player -> 'player_char', Good Items (Veggies) -> `['veg_carrot', 'veg_lettuce', 'veg_cabbage']`, Bad Items (Meat) -> `['meat_steak', 'food_fish']`."

4.  **Copy & Fill:** Copy the entire code for your chosen template. Fill in the `/* PLACEHOLDER */` sections with your game logic, including the specific asset lists you planned.

5.  **Add "Juice" (Effects):** Make the game feel alive. On collection, use `addKaboom(pos)`. On penalty, use `shake()`.

6.  **Final Output:** Your entire response must be ONLY the completed, clean HTML code.

---
### **MASTER ASSET LIBRARY**
---
*You MUST use these asset keys and URLs. Select the most appropriate ones for the game topic.*
-   `player_char`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/player.png"
-   `plant_tree`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/Tree1.png"
-   `plant_palm`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/Palm_tree.png"
-   `env_sun`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/Sun.png"
-   `env_water`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/WaterDroplet.png"
-   `enemy_1`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/enemey1.png"
-   `enemy_2`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/enemey2.png"
-   `veg_advocado_half`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/advocado-half.png"
-   `veg_apple_half`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/apple-half.png"
-   `veg_apple`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/apple.png"
-   `veg_artichoke`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/artichoke.png"
-   `veg_asparagus`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/asparagus.png"
-   `veg_avocado`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/avocado.png"
-   `food_bacon_raw`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/bacon-raw.png"
-   `food_bacon`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/bacon.png"
-   `veg_banana`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/banana.png"
-   `veg_beans`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/beans.png"
-   `veg_beans1`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/beans1.png"
-   `veg_beet`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/beet.png"
-   `veg_beetroot`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/beetroot.png"
-   `food_bread`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/bread.png"
-   `veg_brinjal`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/brinjal.png"
-   `veg_broccoli`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/broccoli.png"
-   `veg_cabbage`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/cabbage.png"
-   `veg_capsicum`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/capsicum.png"
-   `veg_carrot`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/carrot.png"
-   `veg_cauliflower`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/cauliflower.png"
-   `food_cheese_cut`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/cheese-cut.png"
-   `food_cheese`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/cheese.png"
-   `veg_cherry_tomato`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/cherry%20tomato.png"
-   `food_chocolate_wrapper`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/chocolate-wrapper.png"
-   `food_chocolate`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/chocolate.png"
-   `veg_coconut_half`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/coconut-half.png"
-   `food_cookie`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/cookie.png"
-   `veg_corn`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/corn.png"
-   `veg_cucumber`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/cucumber.png"
-   `food_egg_cooked`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/egg-cooked.png"
-   `food_egg_half`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/egg-half.png"
-   `food_egg`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/egg.png"
-   `veg_eggplant`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/eggplant.png"
-   `food_fish`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/fish.png"
-   `veg_garlic`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/garlic.png"
-   `veg_grapes`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/grapes.png"
-   `veg_green_chilli`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/green_chilli.png"
-   `veg_herb1`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/herb1.png"
-   `veg_herb2`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/herb2.png"
-   `veg_herb3`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/herb3.png"
-   `veg_herb4`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/herb4.png"
-   `veg_herb5`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/herb5.png"
-   `food_honey`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/honey.png"
-   `food_hot_dog`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/hot-dog.png"
-   `food_ice_cream`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/ice-cream-scoop-chocolate.png"
-   `veg_kale`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/kale.png"
-   `veg_kale1`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/kale1.png"
-   `veg_lemon_half`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/lemon-half.png"
-   `veg_lemon`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/lemon.png"
-   `veg_lettuce`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/lettuce.png"
-   `food_baguette`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/loaf-baguette.png"
-   `food_loaf_round`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/loaf-round.png"
-   `food_loaf`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/loaf.png"
-   `food_maki_salmon`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/maki-salmon.png"
-   `meat_cooked`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/meat-cooked.png"
-   `meat_raw`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/meat-raw.png"
-   `meat_ribs`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/meat-ribs.png"
-   `meat_sausage`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/meat-sausage.png"
-   `food_mushroom`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/mushroom.png"
-   `food_omlet`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/omlet.png"
-   `veg_onion`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/onion.png"
-   `veg_orange`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/orange.png"
-   `food_pancakes`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/pancakes.png"
-   `veg_paprika_slice`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/paprika-slice.png"
-   `veg_paprika`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/paprika.png"
-   `veg_pomegranate`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/pomogranate.png"
-   `veg_potato`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/potato.png"
-   `veg_pumpkin`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/pumpkin.png"
-   `veg_radish`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/radish.png"
-   `veg_red_chilli`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/red_chilli.png"
-   `meat_chicken`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/roastedchicken.png"
-   `food_salmon`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/salmon.png"
-   `veg_squash`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/squash.png"
-   `veg_squash1`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/squash1.png"
-   `meat_steak`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/steak.png"
-   `veg_strawberry`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/strawberry.png"
-   `food_sushi_salmon`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/sushi-salmon.png"
-   `veg_sweetpotato`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/sweetpotato.png"
-   `veg_tomato_slice`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/tomato-slice.png"
-   `veg_tomato`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/tomato.png"
-   `meat_turkey`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/turkey.png"
-   `veg_turnip`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/turnip.png"
-   `meat_ham`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/whole-ham.png"
-   `veg_yam`: "https://raw.githack.com/brainboyai/tiny-tutor-assets/main/yam.png"

---
### **TEMPLATE LIBRARY (FOCUSED & INTELLIGENT)**
---

#### **TEMPLATE B: THE KABOOM COLLECTOR GAME**
* **Best for:** Topics about collecting good things and avoiding bad things.

```html
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
        const GOOD_ITEMS = [ { name: "Carrot", sprite: "veg_carrot" }, { name: "Lettuce", sprite: "veg_lettuce" } ];
        const BAD_ITEMS = [ { name: "Meat", sprite: "meat_steak" }, { name: "Poison", sprite: "enemy_1" } ];
        const GAME_DURATION = 30;
        
        loadSprite(PLAYER_SPRITE, `https://raw.githack.com/brainboyai/tiny-tutor-assets/main/player.png`);
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
            sun: { name: "Sun", sprite: "env_sun", required: 3 },
            water: { name: "Water", sprite: "env_water", required: 2 },
        };
        const PRODUCT = { name: "Glucose", goal: 5 };
        const ENEMIES = [ { name: "Pest", sprite: "enemy_1" } ];
        const PLAYER_SPRITE = "plant_tree";

        // Auto-load all necessary sprites
        loadSprite(PLAYER_SPRITE, `https://raw.githack.com/brainboyai/tiny-tutor-assets/main/${PLAYER_SPRITE}.png`);
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
            
            const player = add([ sprite(PLAYER_SPRITE), pos(width()/2, height() - 60), area({scale: 0.8}), anchor("center"), scale(0.3), "player" ]);
            
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
                const item = add([ sprite(ing.sprite), pos(rand(0, width()), -60), move(DOWN, 150), area(), offscreen({ destroy: true }), scale(1.5), "ingredient", { type: key } ]);
                item.add([text(ing.name, {size: 10}), color(0,0,0), anchor("center"), pos(0, -25)]);
            });
            loop(2.5, () => { 
                const enemyData = choose(ENEMIES);
                const enemy = add([ sprite(enemyData.sprite), pos(rand(0, width()), -60), move(DOWN, 200), area(), offscreen({ destroy: true }), scale(2.5), "enemy" ]); 
                enemy.add([text(enemyData.name, {size: 10}), color(255,0,0), anchor("center"), pos(0, -25)]);
            });

            onClick("ingredient", (ing) => {
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
