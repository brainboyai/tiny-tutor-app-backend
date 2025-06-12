# game_generator.py

import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import logging

# The large prompt template, containing all game variations, is stored here.
# This keeps the main app.py file clean and focused on routing.
PROMPT_TEMPLATE = """
You are an expert educational game designer and developer. Your task is to generate a complete, single-file HTML game for the topic: "TOPIC_PLACEHOLDER" using the Kaboom.js game engine and a pre-defined library of sprite assets.

---
### **MANDATORY WORKFLOW**
---
1.  **Asset-First Analysis:** Deeply analyze the topic: "TOPIC_PLACEHOLDER". First, identify the key objects and concepts. Then, map these concepts to the most appropriate sprites from the **Asset Library** below. For example, for a game about "Herbivores," the player could be "player_char", good items (plants) could be "item_heart", and bad items (predators) could be "enemy_1".
2.  **Choose ONE Template:** Review the FOUR Kaboom.js game templates below. Choose the single most appropriate template for the topic.
3.  **State Your Choice & Asset Plan:** At the very beginning of your response, you MUST state your template choice and your asset plan. For example: "The topic is 'Herbivores', which involves collecting good items and avoiding bad ones. I will use Template B: The Collector Game. I will map the assets as follows: Player -> 'player_char', Good Items (Plants) -> 'item_heart', Bad Items (Predators) -> 'enemy_2'."
4.  **Copy & Fill:** Copy the entire code for your chosen template. Your only coding task is to replace the `/* PLACEHOLDER */` comments with relevant JavaScript content. This includes defining the game rules and using the asset keys (e.g., "player_char", "item_coin") in your `loadSprite` and `add` calls.
5.  **Add "Juice":** Make the game feel alive. Use effects like `scale()`, `rotate()`, and `opacity()` on interaction. For example, when a player collects an item, make it shrink and fade out.
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
### **TEMPLATE LIBRARY (KABOOM.JS ASSET EDITION v7 - ROBUST)**
---

#### **TEMPLATE A: THE KABOOM QUIZ GAME**
* **Best for:** Math, vocabulary, definitions (e.g., Algebra, Countries).
* **Gameplay:** A question appears. The player clicks one of the answer choices.

```html
<!-- TEMPLATE A: KABOOM QUIZ GAME -->
<!DOCTYPE html>
<html>
<head>
    <title>Quiz</title>
    <style>body, html { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background: #000; }</style>
</head>
<body>
    <script src="[https://unpkg.com/kaboom@3000.0.1/dist/kaboom.js](https://unpkg.com/kaboom@3000.0.1/dist/kaboom.js)"></script>
    <script>
        kaboom({ width: 800, height: 600, letterbox: true, background: [0, 0, 0] });

        // --- 1. DEFINE QUESTIONS & OPTIONS ---
        const questions = [
            /* PLACEHOLDER: Fill with at least 3 question objects.
            {
                question: "What is the capital of France?",
                options: ["Berlin", "Madrid", "Paris", "Rome"],
                answer: "Paris",
            },
            */
        ];
        // --- END OF PLACEHOLDER ---

        scene("start", () => {
             add([
                text("/* PLACEHOLDER: Game Title */", { size: 50, font: "sans-serif", width: width() - 100 }),
                pos(width() / 2, height() / 2 - 100),
                anchor("center"),
            ]);
             add([
                text("/* PLACEHOLDER: Game Instructions */", { size: 24, font: "sans-serif", width: width() - 100 }),
                pos(width() / 2, height() / 2),
                anchor("center"),
            ]);
             add([
                text("Click to Start", { size: 32, font: "sans-serif" }),
                pos(width() / 2, height() / 2 + 100),
                anchor("center"),
            ]);
            onClick(() => go("game", { score: 0, qIndex: 0 }));
        });

        scene("game", ({ score, qIndex }) => {
            const currentQuestion = questions[qIndex];
            
            add([
                text(currentQuestion.question, { size: 32, width: width() - 80, font: "sans-serif" }),
                pos(width() / 2, 120),
                anchor("center"),
            ]);

            add([
                text(`Score: ${score}`, { size: 24, font: "sans-serif" }),
                pos(20, 20),
            ]);

            const optionsYStart = 250;
            currentQuestion.options.forEach((option, i) => {
                const btn = add([
                    rect(width() - 200, 50),
                    radius(8),
                    pos(width() / 2, optionsYStart + i * 70),
                    anchor("center"),
                    area(),
                    color(100, 100, 255),
                    outline(2),
                    "optionBtn"
                ]);
                btn.add([
                    text(option, { size: 28, font: "sans-serif" }),
                    anchor("center"),
                    color(255, 255, 255),
                ]);

                btn.onClick(() => {
                    let newScore = score;
                    if (option === currentQuestion.answer) {
                        btn.color = rgb(0, 255, 0);
                        newScore += 10;
                    } else {
                        btn.color = rgb(255, 0, 0);
                    }
                    wait(1, () => {
                        if (qIndex + 1 < questions.length) {
                            go("game", { score: newScore, qIndex: qIndex + 1 });
                        } else {
                            go("end", { finalScore: newScore });
                        }
                    });
                });
            });
        });

        scene("end", ({ finalScore }) => {
            add([
                text(`Final Score: ${finalScore}`, { size: 50, font: "sans-serif" }),
                pos(width() / 2, height() / 2 - 50),
                anchor("center"),
            ]);
             add([
                text("Click to play again", { size: 24, font: "sans-serif" }),
                pos(width() / 2, height() / 2 + 20),
                anchor("center"),
            ]);
            onClick(() => go("start"));
        });

        go("start");
    </script>
</body>
</html>
```

---
#### **TEMPLATE B: THE KABOOM COLLECTOR GAME (WITH SPRITES)**
* **Best for:** Navigation, collection, simple simulation (e.g., Herbivores, Circulatory System, Pollination).
* **Gameplay:** Player moves a character sprite to collect "good" item sprites and avoid "bad" enemy sprites.

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

        // --- 1. LOAD ASSETS ---
        /* PLACEHOLDER: Load the sprites you need for your game from the Asset Library. */
        loadSprite("player_char", "[https://raw.githack.com/brainboyai/tiny-tutor-assets/main/player.png](https://raw.githack.com/brainboyai/tiny-tutor-assets/main/player.png)");
        loadSprite("good_item", "[https://raw.githack.com/brainboyai/tiny-tutor-assets/main/item_heart.png](https://raw.githack.com/brainboyai/tiny-tutor-assets/main/item_heart.png)");
        loadSprite("bad_item", "[https://raw.githack.com/brainboyai/tiny-tutor-assets/main/enemey1.png](https://raw.githack.com/brainboyai/tiny-tutor-assets/main/enemey1.png)");
        // --- END OF PLACEHOLDER ---

        scene("start", () => {
             add([ text("/* PLACEHOLDER: Game Title */", { size: 50, font: "sans-serif", width: width() - 100 }), pos(width() / 2, height() / 2 - 100), anchor("center"), ]);
             add([ text("/* PLACEHOLDER: Game Instructions */", { size: 24, font: "sans-serif", width: width() - 100 }), pos(width() / 2, height() / 2), anchor("center"), ]);
             add([ text("Click to Start", { size: 32, font: "sans-serif" }), pos(width() / 2, height() / 2 + 100), anchor("center"), ]);
            onClick(() => go("game"));
        });

        scene("game", () => {
            const GAME_DURATION = 30;
            let score = 0;
            
            const scoreLabel = add([ text("Score: 0", { size: 32, font: "sans-serif" }), pos(24, 24) ]);
            const timerLabel = add([ text("Time: " + GAME_DURATION, { size: 32, font: "sans-serif" }), pos(width() - 24, 24), anchor("topright") ]);
            
            const player = add([ sprite("player_char"), pos(width() / 2, height() - 80), area(), anchor("center"), scale(2.5) ]);

            onUpdate(() => { player.pos.x = mousePos().x; });

            loop(0.6, () => {
                const isGood = rand() > 0.3;
                const itemSprite = isGood ? "good_item" : "bad_item";
                const itemTag = isGood ? "good" : "bad";
                add([ sprite(itemSprite), pos(rand(0, width()), -60), move(DOWN, 280), area(), offscreen({ destroy: true }), itemTag, scale(2), "item" ]);
            });

            onCollide(player, "good", (p, good) => {
                destroy(good);
                score += 10;
                scoreLabel.text = `Score: ${score}`;
                addKaboom(good.pos);
            });
            
            onCollide(player, "bad", (p, bad) => {
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
#### **TEMPLATE C: THE KABOOM PROCESS & RECIPE GAME**
* **Best for:** Multi-step processes, cycles (e.g., Photosynthesis, Water Cycle, Digestion).
* **Gameplay:** Player clicks falling sprites to fill meters and create a "product".

```html
<!-- TEMPLATE C: KABOOM PROCESS & RECIPE GAME -->
<!DOCTYPE html>
<html>
<head>
    <title>Recipe</title>
    <style>body, html { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background: #000; }</style>
</head>
<body>
    <script src="[https://unpkg.com/kaboom@3000.0.1/dist/kaboom.js](https://unpkg.com/kaboom@3000.0.1/dist/kaboom.js)"></script>
    <script>
        kaboom({ width: 800, height: 600, letterbox: true, background: [135, 206, 250] });

        // --- 1. DEFINE RECIPE & GOAL & LOAD ASSETS ---
        const RECIPE = {
            /* PLACEHOLDER: Define 2 to 4 ingredients with sprite keys from Asset Library */
            ingredient1: { name: "Sunlight", sprite: "item_diamond", required: 3 },
            ingredient2: { name: "Water", sprite: "item_key", required: 2 },
        };
        const PRODUCT = {
            /* PLACEHOLDER: Define the final product */
            name: "Glucose",
            goal: 5
        };
        // Load all sprites defined in the recipe
        for (const key in RECIPE) {
            loadSprite(RECIPE[key].sprite, `https://raw.githack.com/brainboyai/tiny-tutor-assets/main/${RECIPE[key].sprite}.png`);
        }
        // --- END OF PLACEHOLDER ---
        
        const ingredientKeys = Object.keys(RECIPE);
        
        scene("game", () => {
            let inventory = {};
            ingredientKeys.forEach(key => inventory[key] = 0);
            let productsMade = 0;

            const meterWidth = 150;
            const meterHeight = 16;
            const meterGap = 20;
            const totalMetersWidth = ingredientKeys.length * (meterWidth + meterGap) - meterGap;
            const startX = (width() - totalMetersWidth) / 2;

            ingredientKeys.forEach((key, i) => {
                const ingredient = RECIPE[key];
                const meterX = startX + i * (meterWidth + meterGap);
                add([ text(ingredient.name, { size: 16 }), pos(meterX, 20) ]);
                add([ rect(meterWidth, meterHeight), radius(4), color(80, 80, 80), pos(meterX, 45) ]);
                add([ rect(0, meterHeight), radius(4), color(255, 255, 255), pos(meterX, 45), `meter_${key}` ]);
            });
            const productLabel = add([ text(`${PRODUCT.name}: 0/${PRODUCT.goal}`, { size: 24 }), pos(width() - 40, 40), anchor("topright") ]);

            loop(1, () => {
                const key = choose(ingredientKeys);
                const ing = RECIPE[key];
                add([
                    sprite(ing.sprite), pos(rand(0, width()), 80), move(DOWN, 150), area(), offscreen({ destroy: true }), scale(2), "ingredient", { type: key }
                ]);
            });

            onClick("ingredient", (ing) => {
                if (inventory[ing.type] < RECIPE[ing.type].required) {
                    inventory[ing.type]++;
                    destroy(ing);
                    updateMeters();
                    checkRecipe();
                }
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
                    ingredientKeys.forEach(key => inventory[key] -= RECIPE[key].required);
                    productsMade++;
                    productLabel.text = `${PRODUCT.name}: ${productsMade} / ${PRODUCT.goal}`;
                    updateMeters();
                    if (productsMade >= PRODUCT.goal) {
                        go("end", { success: true });
                    }
                }
            }
        });
        
        scene("end", ({ success }) => {
            add([ text(success ? "Process Complete!" : "Time's Up!", { size: 50 }), pos(center()), anchor("center") ]);
            add([ text("Click to restart", { size: 24 }), pos(width() / 2, height() / 2 + 50), anchor("center") ]);
            onClick(() => go("start"));
        });
        
        scene("start", () => {
             add([ text("/* PLACEHOLDER: Game Title */", { size: 50, width: width() - 100 }), pos(center().x, height() / 2 - 100), anchor("center"), ]);
             add([ text("/* PLACEHOLDER: Game Instructions */", { size: 24, width: width() - 100 }), pos(center().x, height() / 2), anchor("center"), ]);
             add([ text("Click to Start", { size: 32 }), pos(center().x, height() / 2 + 100), anchor("center"), ]);
            onClick(() => go("game"));
        });
        
        go("start");
    </script>
</body>
</html>
```

---
#### **TEMPLATE E: THE KABOOM MATCHING GAME**
* **Best for:** Vocabulary, definitions, matching pairs (e.g., Country & Capital, Animal & Habitat).
* **Gameplay:** A grid of cards is shown. The player clicks two cards to flip them over. If they match, they stay open.

```html
<!-- TEMPLATE E: THE KABOOM MATCHING GAME -->
<!DOCTYPE html>
<html>
<head>
    <title>Matching</title>
    <style>body, html { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background: #000; }</style>
</head>
<body>
    <script src="[https://unpkg.com/kaboom@3000.0.1/dist/kaboom.js](https://unpkg.com/kaboom@3000.0.1/dist/kaboom.js)"></script>
    <script>
        kaboom({ width: 800, height: 600, letterbox: true, background: [45, 45, 70] });

        // --- 1. DEFINE YOUR MATCHING PAIRS ---
        const items = [
            /* PLACEHOLDER: Fill with at least 6 unique string values. */
            "Dog", "Cat", "Bird", "Fish", "Lion", "Tiger",
        ];
        // --- END OF PLACEHOLDER ---
        
        function shuffle(array) {
            let currentIndex = array.length, randomIndex;
            while (currentIndex > 0) {
                randomIndex = Math.floor(Math.random() * currentIndex);
                currentIndex--;
                [array[currentIndex], array[randomIndex]] = [
                array[randomIndex], array[currentIndex]];
            }
            return array;
        }

        scene("game", () => {
            const cardValues = shuffle([...items, ...items]);
            let firstCard = null;
            let lockBoard = false;
            let matchedPairs = 0;
            const gridCols = 4;
            const gridRows = Math.ceil(cardValues.length / gridCols);
            const cardWidth = 120;
            const cardHeight = 160;
            const gap = 15;
            const totalWidth = gridCols * (cardWidth + gap) - gap;
            const startX = (width() - totalWidth) / 2;

            cardValues.forEach((value, i) => {
                const row = Math.floor(i / gridCols);
                const col = i % gridCols;

                const card = add([
                    pos(startX + col * (cardWidth + gap), 50 + row * (cardHeight + gap)),
                    rect(cardWidth, cardHeight),
                    radius(8),
                    color(60, 60, 180), area(), "card",
                    { value: value, isFlipped: false, }
                ]);

                card.onClick(() => {
                    if (lockBoard || card.isFlipped) return;
                    
                    card.isFlipped = true;
                    card.color = rgb(150, 150, 200);
                    const textObj = card.add([ text(card.value, {size: 20}), anchor("center"), "card-text" ]);

                    if (firstCard === null) {
                        firstCard = card;
                    } else {
                        lockBoard = true;
                        if (firstCard.value === card.value) {
                            matchedPairs++;
                            firstCard = null;
                            lockBoard = false;
                            if (matchedPairs === items.length) {
                                wait(1, () => go("end"));
                            }
                        } else {
                            wait(1, () => {
                                card.isFlipped = false;
                                card.color = rgb(60, 60, 180);
                                destroy(textObj);
                                
                                firstCard.isFlipped = false;
                                firstCard.color = rgb(60, 60, 180);
                                firstCard.children.forEach(child => { if(child.is("card-text")) destroy(child); });

                                firstCard = null;
                                lockBoard = false;
                            });
                        }
                    }
                });
            });
        });

        scene("end", () => {
            add([ text("You Win!"), pos(center()), anchor("center") ]);
            add([ text("Click to play again", { size: 24 }), pos(width() / 2, height() / 2 + 50), anchor("center") ]);
            onClick(() => go("start"));
        });
        
        scene("start", () => {
             add([ text("/* PLACEHOLDER: Game Title */", { size: 50, width: width() - 100 }), pos(center().x, height() / 2 - 100), anchor("center"), ]);
             add([ text("/* PLACEHOLDER: Game Instructions */", { size: 24, width: width() - 100 }), pos(center().x, height() / 2), anchor("center"), ]);
             add([ text("Click to Start", { size: 32 }), pos(center().x, height() / 2 + 100), anchor("center"), ]);
            onClick(() => go("game"));
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
