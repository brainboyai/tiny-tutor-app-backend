# game_generator.py

import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import logging

# The large prompt template, containing all game variations, is stored here.
# This keeps the main app.py file clean and focused on routing.
PROMPT_TEMPLATE = """
You are an expert educational game designer and developer. Your task is to generate a complete, single-file HTML game for the topic: "TOPIC_PLACEHOLDER" using the Kaboom.js game engine.

---
### **MANDATORY WORKFLOW**
---
1.  **Analyze Topic:** Deeply analyze the core learning objective of "TOPIC_PLACEHOLDER". Is it about definitions, a process, a sequence, a journey, or identification?
2.  **Choose ONE Template:** Review the FIVE Kaboom.js game templates below. You **MUST** choose the single most appropriate template for the topic.
3.  **State Your Choice:** At the very beginning of your response, you MUST state which template you are choosing and why. For example: "The topic is 'Photosynthesis', which involves a multi-step process. Therefore, I will use Template C: The Process & Recipe Game."
4.  **Copy & Fill:** Copy the entire code for your chosen template. Your only coding task is to replace the `/* PLACEHOLDER */` comments with relevant JavaScript content for the topic. Do not change the core logic, HTML, or Kaboom.js setup.
5.  **Final Output:** Your entire response must be ONLY the completed, clean HTML code, with no extra notes or comments outside the code.

---
### **TEMPLATE LIBRARY (KABOOM.JS EDITION v6 - STABLE & ROBUST)**
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
                    rect(width() - 200, 50, { radius: 8 }),
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
#### **TEMPLATE B: THE KABOOM COLLECTOR GAME**
* **Best for:** Navigation, collection, simple simulation (e.g., Herbivores, Circulatory System, Pollination).
* **Gameplay:** Player moves a character to collect "good" items and avoid "bad" ones.

```html
<!-- TEMPLATE B: KABOOM COLLECTOR GAME -->
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

        // --- 1. DEFINE GAME ENTITIES & RULES ---
        const PLAYER_COLOR = [255, 182, 193];
        const GOOD_ITEM = { tag: "good", color: [0, 255, 0], score: 10 };
        const BAD_ITEM = { tag: "bad", color: [255, 0, 0], score: -5 };
        const GAME_DURATION = 30;
        /* PLACEHOLDER: You can adjust the colors and scores above if needed. */
        // --- END OF PLACEHOLDER ---

        scene("game", () => {
            let score = 0;
            const scoreLabel = add([ text("Score: 0", { size: 32, font: "sans-serif" }), pos(24, 24) ]);
            const timerLabel = add([ text("Time: " + GAME_DURATION, { size: 32, font: "sans-serif" }), pos(width() - 24, 24), anchor("topright") ]);
            
            const player = add([ rect(40, 40), pos(width() / 2, height() - 60), color(...PLAYER_COLOR), area(), anchor("center") ]);

            onUpdate(() => { player.pos.x = mousePos().x; });

            loop(0.8, () => {
                const itemConfig = rand() > 0.4 ? GOOD_ITEM : BAD_ITEM;
                add([ rect(30, 30), pos(rand(0, width()), 0), color(...itemConfig.color), move(DOWN, 240), area(), offscreen({ destroy: true }), itemConfig.tag, ]);
            });

            onCollide(player, "good", (p, good) => {
                destroy(good);
                score += GOOD_ITEM.score;
                scoreLabel.text = `Score: ${score}`;
            });
            
            onCollide(player, "bad", (p, bad) => {
                destroy(bad);
                score += BAD_ITEM.score;
                scoreLabel.text = `Score: ${score}`;
                shake(10);
            });
            
            let time = GAME_DURATION;
            loop(1, () => {
                time--;
                timerLabel.text = `Time: ${time}`;
                if (time <= 0) { go("end", { finalScore: score }); }
            });
        });

        scene("end", ({ finalScore }) => {
            add([ text(`Final Score: ${finalScore}`, { size: 50, font: "sans-serif" }), pos(width() / 2, height() / 2 - 50), anchor("center"), ]);
            add([ text("Click to play again", { size: 24, font: "sans-serif" }), pos(width() / 2, height() / 2 + 20), anchor("center"), ]);
            onClick(() => go("start"));
        });
        
        scene("start", () => {
             add([ text("/* PLACEHOLDER: Game Title */", { size: 50, font: "sans-serif", width: width() - 100 }), pos(width() / 2, height() / 2 - 100), anchor("center"), ]);
             add([ text("/* PLACEHOLDER: Game Instructions */", { size: 24, font: "sans-serif", width: width() - 100 }), pos(width() / 2, height() / 2), anchor("center"), ]);
             add([ text("Click to Start", { size: 32, font: "sans-serif" }), pos(width() / 2, height() / 2 + 100), anchor("center"), ]);
            onClick(() => go("game"));
        });

        go("start");
    </script>
</body>
</html>
```

---
#### **TEMPLATE C: THE KABOOM PROCESS & RECIPE GAME**
* **Best for:** Multi-step processes, cycles (e.g., Photosynthesis, Water Cycle, Digestion).
* **Gameplay:** Player clicks falling "ingredients" to fill meters and create a "product".

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

        // --- 1. DEFINE RECIPE & GOAL ---
        const RECIPE = {
            /* PLACEHOLDER: Define 2 to 4 ingredients */
            ingredient1: { name: "Sunlight", color: [255, 255, 0], required: 3 },
            ingredient2: { name: "Water", color: [0, 0, 255], required: 2 },
            ingredient3: { name: "CO2", color: [100, 100, 100], required: 4 },
        };
        const PRODUCT = {
            /* PLACEHOLDER: Define the final product */
            name: "Glucose",
            goal: 5
        };
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
                add([ rect(meterWidth, meterHeight), color(80, 80, 80), pos(meterX, 45), { radius: 4 } ]);
                add([ rect(0, meterHeight), color(ingredient.color), pos(meterX, 45), { radius: 4 }, `meter_${key}` ]);
            });
            const productLabel = add([ text(`${PRODUCT.name}: 0/${PRODUCT.goal}`, { size: 24 }), pos(width() - 40, 40), anchor("topright") ]);

            loop(1, () => {
                const key = choose(ingredientKeys);
                const ing = RECIPE[key];
                add([
                    rect(40, 40), pos(rand(0, width()), 80), color(ing.color), move(DOWN, 150), area(), offscreen({ destroy: true }), "ingredient", { type: key }
                ]).add([ text(ing.name.substring(0,3), { size: 12 }), color(0,0,0), anchor("center") ]);
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
#### **TEMPLATE D: THE KABOOM STACKING GAME**
* **Best for:** Hierarchy, structure, sequence (e.g., Food Pyramid, Layers of the Earth, Taxonomy).
* **Gameplay:** Player moves a platform to catch falling blocks in the correct order.

```html
<!-- TEMPLATE D: THE KABOOM STACKING GAME -->
<!DOCTYPE html>
<html>
<head>
    <title>Stacker</title>
    <style>body, html { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background: #000; }</style>
</head>
<body>
    <script src="[https://unpkg.com/kaboom@3000.0.1/dist/kaboom.js](https://unpkg.com/kaboom@3000.0.1/dist/kaboom.js)"></script>
    <script>
        kaboom({ width: 800, height: 600, letterbox: true, background: [208, 240, 255] });

        // --- 1. DEFINE THE ORDERED BLOCKS TO STACK ---
        const BUILD_ORDER = [
            /* PLACEHOLDER: Fill with at least 4 objects to stack in order. */
            { name: "Producers", color: [0, 255, 0] },
            { name: "Primary Consumers", color: [0, 150, 255] },
            { name: "Secondary Consumers", color: [255, 150, 0] },
            { name: "Apex Predators", color: [255, 0, 0] },
        ];
        // --- END OF PLACEHOLDER ---

        scene("game", () => {
            let currentBlockIndex = 0;
            const stack = [];

            const platform = add([ rect(160, 20), pos(width() / 2, height() - 40), color(50, 50, 50), area(), anchor("center"), ]);
            onUpdate(() => { platform.pos.x = mousePos().x; });
            
            const nextBlockLabel = add([ text(`Next: ${BUILD_ORDER[0].name}`), pos(20, 20), { value: 0 } ]);

            loop(1.5, () => {
                const blockIndex = rand() > 0.4 ? currentBlockIndex : randi(0, BUILD_ORDER.length);
                const blockData = BUILD_ORDER[blockIndex];
                add([
                    rect(120, 30, { radius: 4 }), pos(rand(60, width() - 60), 0), color(blockData.color), move(DOWN, 200), area(), offscreen({ destroy: true }), "block", { data: blockData }
                ]).add([ text(blockData.name, { size: 16 }), anchor("center"), color(0,0,0) ]);
            });

            platform.onCollide("block", (block) => {
                if (block.data.name === BUILD_ORDER[currentBlockIndex].name) {
                    destroy(block);
                    const newY = platform.pos.y - (stack.length + 1) * 32;
                    const newBlock = add([ rect(120, 30, { radius: 4 }), pos(platform.pos.x, newY), color(block.data.color), anchor("center") ]);
                    newBlock.add([ text(block.data.name, { size: 16 }), anchor("center"), color(0,0,0) ]);
                    stack.push(newBlock);
                    
                    currentBlockIndex++;
                    if (currentBlockIndex >= BUILD_ORDER.length) {
                        go("end", { success: true });
                    } else {
                        nextBlockLabel.text = `Next: ${BUILD_ORDER[currentBlockIndex].name}`;
                    }
                } else {
                    go("end", { success: false });
                }
            });
        });

        scene("end", ({ success }) => {
            add([ text(success ? "Tower Complete!" : "Wrong Block!", { size: 50 }), pos(center()), anchor("center") ]);
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
                    rect(cardWidth, cardHeight, { radius: 8 }),
                    color(60, 60, 180), area(), "card",
                    { value: value, isFlipped: false, }
                ]);

                card.onClick(() => {
                    if (lockBoard || card.isFlipped) return;
                    
                    card.isFlipped = true;
                    card.color = rgb(150, 150, 200);
                    card.add([ text(card.value, {size: 20}), anchor("center"), "card-text" ]);

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
                                card.get("card-text").forEach(destroy);
                                
                                firstCard.isFlipped = false;
                                firstCard.color = rgb(60, 60, 180);
                                firstCard.get("card-text").forEach(destroy);

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
