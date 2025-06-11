import os
from flask import Blueprint, jsonify, request, current_app
import google.generativeai as genai
from firebase_admin import firestore
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# NOTE: In a larger application, the 'db' client, 'limiter', and the 'token_required' decorator
# would typically be initialized in the main app.py and imported here from a shared context
# to avoid re-initialization. For this self-contained blueprint, we assume they are accessible.

# Create a Blueprint for game-related routes
game_bp = Blueprint('game_bp', __name__)


# This is the master prompt containing the entire library of game templates.
# It represents the core "intelligence" of our game generation agent.
prompt_template = """
You are an expert educational game designer and developer. Your task is to generate a complete, single-file HTML game for the topic: "TOPIC_PLACEHOLDER".

---
### **MANDATORY WORKFLOW**
---
1.  **Analyze Topic:** Deeply analyze the core learning objective of "TOPIC_PLACEHOLDER". Is it about definitions, a process, a sequence, a journey, or identification?
2.  **Choose ONE Template:** Review the SIX game templates below. You **MUST** choose the single most appropriate template for the topic.
3.  **State Your Choice:** At the very beginning of your response, you MUST state which template you are choosing and why. For example: "The topic is 'Algebra', which involves solving problems with correct answers. Therefore, I will use Template A: The Quiz Game."
4.  **Copy & Fill:** Copy the entire code for your chosen template. Your only coding task is to replace the `<!-- PLACEHOLDER -->` comments with relevant content for the topic. Do not change the core logic.
5.  **Final Output:** Your entire response must be ONLY the completed, clean HTML code, with no extra notes or comments outside the code.

---
### **TEMPLATE LIBRARY**
---
#### **TEMPLATE A: THE QUIZ GAME (REPAIRED)**
* **Best for:** Math, vocabulary, definitions (e.g., Algebra, Countries).
* **Gameplay:** A question appears. Player clicks a floating bubble. The bubble briefly flashes green/red AFTER being clicked.

```html
<!-- TEMPLATE A: QUIZ GAME -->
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title><!-- 1. TOPIC --> Quiz</title>
    <style>
        body, html { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; font-family: sans-serif; background-color: #f0f0f0; }
        #game-container { width: 100%; height: 100%; position: relative; }
        #question-bar { position: absolute; top: 0; left: 0; width: 100%; box-sizing: border-box; background: rgba(0,0,0,0.7); color: white; text-align: center; padding: 15px; font-size: 1.2em; }
        #score-bar { position: absolute; top: 65px; right: 10px; background: rgba(0,0,0,0.7); color: white; padding: 8px 12px; border-radius: 5px; font-size: 1.1em;}
        .overlay { position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.8); display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center; color: white; z-index: 10; }
        .overlay h1 { font-size: 2.5em; } .overlay p { font-size: 1.2em; max-width: 80%; } .overlay button { font-size: 1.5em; padding: 0.5em 1.5em; border: none; border-radius: 8px; background: #28a745; color: white; cursor: pointer; margin-top: 20px; }
    </style>
</head>
<body>
    <div id="game-container">
        <canvas id="gameCanvas"></canvas>
        <div id="question-bar"></div>
        <div id="score-bar">Score: 0</div>
        <div id="start-screen" class="overlay">
            <h1><!-- 2. GAME_TITLE --></h1>
            <p><!-- 3. GAME_INSTRUCTIONS --></p>
            <button id="start-button">Start</button>
        </div>
        <div id="end-screen" class="overlay" style="display: none;">
            <h1 id="end-message"></h1>
            <button id="restart-button">Play Again</button>
        </div>
    </div>
    <script>
        const canvas = document.getElementById('gameCanvas');
        const ctx = canvas.getContext('2d');
        const questionBar = document.getElementById('question-bar');
        const scoreBar = document.getElementById('score-bar');
        let score, questions, currentQuestionIndex, answerBubbles = [], gameLoopId, lockBoard = false;

        // <!-- 4. DEFINE QUESTIONS & OPTIONS -->
        const topicQuestions = [
            { question: "Which is a primary color?", options: ["Green", "Blue", "Orange", "Purple"], answer: "Blue" },
            { question: "What is 12 / 3?", options: [3, 5, 4, 6], answer: 4 },
        ];

        function resizeCanvas() { canvas.width = window.innerWidth; canvas.height = window.innerHeight; }

        function AnswerBubble(value) {
            this.value = value;
            this.radius = Math.max(45, String(this.value).length * 8);
            this.x = Math.random() * (canvas.width - this.radius * 2) + this.radius;
            this.y = canvas.height + this.radius;
            this.speed = Math.random() * 1 + 0.5;
            this.color = '#3498db';
            this.draw = function() {
                ctx.beginPath();
                ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
                ctx.fillStyle = this.color;
                ctx.fill();
                ctx.fillStyle = 'white'; ctx.font = 'bold 16px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
                ctx.fillText(this.value, this.x, this.y);
            };
            this.update = function() { this.y -= this.speed; };
        }

        function setupQuestion() {
            lockBoard = false;
            if (currentQuestionIndex >= questions.length) {
                endGame(true);
                return;
            }
            const q = questions[currentQuestionIndex];
            questionBar.textContent = q.question;
            answerBubbles = q.options.map(opt => new AnswerBubble(opt));
        }

        function handleInteraction(event) {
            if (lockBoard) return;
            event.preventDefault();
            const rect = canvas.getBoundingClientRect();
            const x = (event.clientX || event.touches[0].clientX) - rect.left;
            const y = (event.clientY || event.touches[0].clientY) - rect.top;
            for (let i = answerBubbles.length - 1; i >= 0; i--) {
                const bubble = answerBubbles[i];
                if (Math.sqrt((x - bubble.x)**2 + (y - bubble.y)**2) < bubble.radius) {
                    lockBoard = true;
                    if (bubble.value === questions[currentQuestionIndex].answer) {
                        score += 10;
                        bubble.color = '#2ecc71';
                        setTimeout(() => { currentQuestionIndex++; setupQuestion(); }, 1000);
                    } else {
                        score -= 5;
                        bubble.color = '#e74c3c';
                        setTimeout(() => { answerBubbles.splice(i, 1); lockBoard = false; }, 1000);
                    }
                    scoreBar.textContent = `Score: ${score}`;
                    return;
                }
            }
        }
        
        function draw(){
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            answerBubbles.forEach(bubble => bubble.draw());
        }

        function gameLoop() {
            if (!lockBoard) {
                answerBubbles.forEach((bubble, i) => {
                    bubble.update();
                    if (bubble.y < -bubble.radius * 2) answerBubbles.splice(i, 1);
                });
                if (answerBubbles.length === 0 && currentQuestionIndex < questions.length) setupQuestion();
            }
            draw();
            gameLoopId = requestAnimationFrame(gameLoop);
        }


        function startGame() {
            document.getElementById('start-screen').style.display = 'none';
            document.getElementById('end-screen').style.display = 'none';
            resetGame();
            gameLoopId = requestAnimationFrame(gameLoop);
        }

        function resetGame() {
            score = 0;
            scoreBar.textContent = `Score: ${score}`;
            currentQuestionIndex = 0;
            questions = topicQuestions.sort(() => 0.5 - Math.random());
            setupQuestion();
        }

        function endGame(isWin) {
            cancelAnimationFrame(gameLoopId);
            document.getElementById('end-message').textContent = isWin ? `You Win! Final Score: ${score}` : 'Game Over!';
            document.getElementById('end-screen').style.display = 'flex';
        }

        window.addEventListener('resize', resizeCanvas);
        canvas.addEventListener('click', handleInteraction);
        canvas.addEventListener('touchstart', handleInteraction);
        document.getElementById('start-button').addEventListener('click', startGame);
        document.getElementById('restart-button').addEventListener('click', startGame);
        
        resizeCanvas();
    </script>
</body>
</html>
```

---
### **TEMPLATE B: THE PLAYER MOVER GAME**
---
* **Best for:** Navigation, collection, simple simulation (e.g., Herbivores, Circulatory System, Pollination).
* **Gameplay:** Player moves a character to collect "good" items and avoid "bad" ones.

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>Adventure</title>
    <style>
        body, html { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; font-family: sans-serif; }
        #game-container { width: 100%; height: 100%; position: relative; background: #2c3e50; }
        canvas { display: block; }
        #ui-bar { position: absolute; top: 10px; left: 10px; color: white; font-size: 1.5em; }
        .overlay { position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.8); display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center; color: white; z-index: 10; }
        .overlay h1 { font-size: 3em; } .overlay p { font-size: 1.2em; max-width: 80%; } .overlay button { font-size: 1.5em; padding: 0.5em 1.5em; border: none; border-radius: 8px; background: #28a745; color: white; cursor: pointer; margin-top: 20px; }
    </style>
</head>
<body>
    <div id="game-container">
        <div id="ui-bar">Score: <span id="score">0</span> | Lives: <span id="lives">3</span></div>
        <canvas id="gameCanvas"></canvas>
        <div id="start-screen" class="overlay">
            <h1></h1>
            <p></p>
            <button id="start-button">Start</button>
        </div>
        <div id="end-screen" class="overlay" style="display: none;">
            <h1 id="end-message"></h1>
            <button id="restart-button">Play Again</button>
        </div>
    </div>
    <script>
        const canvas = document.getElementById('gameCanvas');
        const ctx = canvas.getContext('2d');
        let scoreEl = document.getElementById('score');
        let livesEl = document.getElementById('lives');
        
        let player, gameObjects = [], score, lives, gameLoopId, spawnInterval;

        const playerProps = { x: 100, y: 100, radius: 15, color: '' };

        function resizeCanvas() { canvas.width = window.innerWidth; canvas.height = window.innerHeight; }

        function GameObject(type) {
            const typeMap = {
                // good: { radius: 10, color: 'lightgreen', label: 'Plant', points: 10 },
                bad: { radius: 15, color: 'grey', label: 'Rock', points: -1 } // points = lives lost
            };
            const props = typeMap[type];
            this.x = Math.random() * canvas.width;
            this.y = 0 - props.radius;
            this.radius = props.radius;
            this.speed = Math.random() * 2 + 1;
            this.type = type;
            this.draw = function() {
                ctx.beginPath();
                ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
                ctx.fillStyle = props.color;
                ctx.fill();
                ctx.fillStyle = 'black'; ctx.font = '10px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
                ctx.fillText(props.label, this.x, this.y);
            };
            this.update = function() { this.y += this.speed; };
        }

        function drawPlayer() {
            ctx.beginPath();
            ctx.arc(player.x, player.y, player.radius, 0, Math.PI * 2);
            ctx.fillStyle = player.color;
            ctx.fill();
        }

        function checkCollisions() {
            for (let i = gameObjects.length - 1; i >= 0; i--) {
                const obj = gameObjects[i];
                if (Math.sqrt((player.x - obj.x)**2 + (player.y - obj.y)**2) < player.radius + obj.radius) {
                    if (obj.type === 'good') {
                        score += 10;
                    } else {
                        lives--;
                        if (lives <= 0) endGame(false);
                    }
                    gameObjects.splice(i, 1);
                    updateUI();
                }
            }
        }
        
        function updateUI() { scoreEl.textContent = score; livesEl.textContent = lives; }

        function gameLoop() {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            drawPlayer();
            gameObjects.forEach((obj, index) => {
                obj.update();
                obj.draw();
                if (obj.y > canvas.height + obj.radius) gameObjects.splice(index, 1);
            });
            checkCollisions();
            gameLoopId = requestAnimationFrame(gameLoop);
        }

        function spawnObject() {
            const type = Math.random() > 0.3 ? 'good' : 'bad';
            gameObjects.push(new GameObject(type));
        }

        function movePlayer(event) {
            const rect = canvas.getBoundingClientRect();
            player.x = (event.clientX || event.touches[0].clientX) - rect.left;
            player.y = (event.clientY || event.touches[0].clientY) - rect.top;
        }

        function startGame() {
            document.getElementById('start-screen').style.display = 'none';
            document.getElementById('end-screen').style.display = 'none';
            resetGame();
            spawnInterval = setInterval(spawnObject, 1000);
            gameLoopId = requestAnimationFrame(gameLoop);
            canvas.addEventListener('mousemove', movePlayer);
            canvas.addEventListener('touchmove', (e) => { e.preventDefault(); movePlayer(e); }, { passive: false });
        }
        
        function resetGame() {
            score = 0;
            lives = 3;
            player = { x: canvas.width / 2, y: canvas.height / 2, radius: playerProps.radius, color: playerProps.color };
            gameObjects = [];
            updateUI();
        }

        function endGame(isWin) {
            cancelAnimationFrame(gameLoopId);
            clearInterval(spawnInterval);
            canvas.removeEventListener('mousemove', movePlayer);
            canvas.removeEventListener('touchmove', movePlayer);
            document.getElementById('end-message').textContent = isWin ? 'You Win!' : `Game Over! Score: ${score}`;
            document.getElementById('end-screen').style.display = 'flex';
        }

        window.addEventListener('resize', resizeCanvas);
        document.getElementById('start-button').addEventListener('click', startGame);
        document.getElementById('restart-button').addEventListener('click', startGame);
        resizeCanvas();
    </script>
</body>
</html>
```

---
### **TEMPLATE C: THE PROCESS & RECIPE GAME**
---
* **Best for:** Multi-step processes, cycles (e.g., Photosynthesis, Water Cycle, Digestion).
* **Gameplay:** Player clicks to collect different "ingredients" to fill progress bars and create a "product".

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>Game</title>
    <style>
        body { margin: 0; background-color: #f0f0f0; font-family: sans-serif; display: flex; flex-direction: column; justify-content: center; align-items: center; height: 100vh; overflow: hidden; }
        #game-container { width: 100%; max-width: 800px; height: 90%; display: flex; flex-direction: column; }
        #ui-container { flex-shrink: 0; background: rgba(0,0,0,0.6); padding: 8px; border-radius: 8px; color: white; display: flex; justify-content: space-around; flex-wrap: wrap; gap: 10px; margin-bottom: 5px; }
        .progress-bar-container { flex: 1; min-width: 80px; text-align: center; font-size: 0.8em;}
        .progress-bar { width: 100%; background-color: #555; border-radius: 5px; overflow: hidden; height: 15px; }
        .progress-fill { height: 100%; background-color: #4CAF50; width: 0%; transition: width 0.2s; }
        #product-counter { font-size: 1.1em; font-weight: bold; padding: 0 10px; }
        #canvas-container { flex-grow: 1; position: relative; width: 100%; height: 100%; }
        canvas { display: block; width: 100%; height: 100%; background-color: #87CEEB; border-radius: 8px; }
        .overlay { position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); display: flex; justify-content: center; align-items: center; text-align: center; color: white; z-index: 10; }
        .overlay-content { background: white; color: black; padding: 2em; border-radius: 10px; max-width: 90%; }
        .overlay-content h1 { font-size: 2em; } .overlay-content button { font-size: 1.2em; padding: 0.5em 1em; margin-top: 1em; border-radius: 5px; border: none; background: #28a745; color: white; cursor: pointer; }
    </style>
</head>
<body>
    <div id="game-container">
        <div id="ui-container">
            <div class="progress-bar-container">Sunlight <div class="progress-bar"><div id="ingredient1-progress" class="progress-fill" style="background-color: #f1c40f;"></div></div></div>
            <div class="progress-bar-container">CO₂ <div class="progress-bar"><div id="ingredient2-progress" class="progress-fill" style="background-color: #95a5a6;"></div></div></div>
            <div class="progress-bar-container">H₂O <div class="progress-bar"><div id="ingredient3-progress" class="progress-fill" style="background-color: #3498db;"></div></div></div>
            <div id="product-counter">: 0 / 5</div>
        </div>
        <div id="canvas-container">
            <canvas id="gameCanvas"></canvas>
            <div id="start-screen" class="overlay">
                <div class="overlay-content">
                    <h1></h1>
                    <p></p>
                    <button id="start-button">Start Game</button>
                </div>
            </div>
            <div id="end-screen" class="overlay" style="display: none;">
                <div class="overlay-content">
                    <h1 id="end-message"></h1>
                    <button id="restart-button">Play Again</button>
                </div>
            </div>
        </div>
    </div>
    <script>
        const canvas = document.getElementById('gameCanvas');
        const ctx = canvas.getContext('2d');
        let gameObjects = [], ingredients = {}, productCount = 0;
        let gameLoopId, spawnInterval;
        
        // const recipe = {
            ingredients: {
                ingredient1: { id: 'ingredient1', name: 'Sunlight', color: '#f1c40f', required: 3 },
                ingredient2: { id: 'ingredient2', name: 'CO₂', color: '#95a5a6', required: 3 },
                ingredient3: { id: 'ingredient3', name: 'H₂O', color: '#3498db', required: 3 }
            },
            product: { name: 'Starch', goal: 5 }
        };

        const ingredientTypes = Object.keys(recipe.ingredients);

        function resizeCanvas() {
            const container = document.getElementById('canvas-container');
            canvas.width = container.clientWidth;
            canvas.height = container.clientHeight;
        }

        function drawCentralObject() {
            ctx.fillStyle = '#654321'; // Trunk
            ctx.fillRect(canvas.width / 2 - 10, canvas.height - 60, 20, 60);
            const plantHeight = 40 + (productCount * 10);
            ctx.fillStyle = '#27ae60'; // Plant color
            ctx.beginPath();
            ctx.arc(canvas.width / 2, canvas.height - 60 - (plantHeight/2), plantHeight/2, 0, Math.PI * 2);
            ctx.fill();
        }

        function GameObject(type) {
            const props = recipe.ingredients[type];
            this.radius = 20;
            this.x = Math.random() * (canvas.width - this.radius * 2) + this.radius;
            this.y = -this.radius;
            this.speed = Math.random() * 1.5 + 1;
            this.type = type;
            this.draw = function() {
                ctx.beginPath();
                ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
                ctx.fillStyle = props.color;
                ctx.fill();
                ctx.fillStyle = 'black'; ctx.font = '12px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
                ctx.fillText(props.name, this.x, this.y);
            };
            this.update = function() { this.y += this.speed; };
        }

        function updateUI() {
            for (const type in recipe.ingredients) {
                const props = recipe.ingredients[type];
                document.getElementById(`${props.id}-progress`).style.width = `${(ingredients[type] / props.required) * 100}%`;
            }
            document.getElementById('product-counter').textContent = `${recipe.product.name}: ${productCount} / ${recipe.product.goal}`;
        }
        
        function checkRecipe() {
            const recipeComplete = ingredientTypes.every(type => ingredients[type] >= recipe.ingredients[type].required);
            if (recipeComplete) {
                ingredientTypes.forEach(type => { ingredients[type] -= recipe.ingredients[type].required; });
                productCount++;
                updateUI();
                if (productCount >= recipe.product.goal) endGame(true);
            }
        }
        
        function handleInteraction(event) {
            event.preventDefault();
            const rect = canvas.getBoundingClientRect();
            const x = (event.clientX || event.touches[0].clientX) - rect.left;
            const y = (event.clientY || event.touches[0].clientY) - rect.top;

            for (let i = gameObjects.length - 1; i >= 0; i--) {
                const obj = gameObjects[i];
                if (Math.sqrt((x - obj.x)**2 + (y - obj.y)**2) < obj.radius) {
                    if (ingredients[obj.type] < recipe.ingredients[obj.type].required) {
                        ingredients[obj.type]++;
                        gameObjects.splice(i, 1);
                        updateUI();
                        checkRecipe();
                        return;
                    }
                }
            }
        }

        function gameLoop() {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            drawCentralObject();
            gameObjects.forEach((obj, index) => {
                obj.update();
                obj.draw();
                if (obj.y > canvas.height + obj.radius) gameObjects.splice(index, 1);
            });
            gameLoopId = requestAnimationFrame(gameLoop);
        }

        function spawnObject() {
            const type = ingredientTypes[Math.floor(Math.random() * ingredientTypes.length)];
            gameObjects.push(new GameObject(type));
        }

        function startGame() {
            document.getElementById('start-screen').style.display = 'none';
            document.getElementById('end-screen').style.display = 'none';
            resetGame();
            spawnInterval = setInterval(spawnObject, 1200);
            gameLoopId = requestAnimationFrame(gameLoop);
        }
        
        function resetGame() {
            productCount = 0;
            ingredientTypes.forEach(type => { ingredients[type] = 0; });
            gameObjects = [];
            updateUI();
        }

        function endGame(isWin) {
            cancelAnimationFrame(gameLoopId);
            clearInterval(spawnInterval);
            document.getElementById('end-message').textContent = isWin ? `You Win! You made ${recipe.product.goal} ${recipe.product.name}!` : 'Game Over!';
            document.getElementById('end-screen').style.display = 'flex';
        }

        window.addEventListener('resize', resizeCanvas);
        canvas.addEventListener('click', handleInteraction);
        canvas.addEventListener('touchstart', handleInteraction);
        document.getElementById('start-button').addEventListener('click', startGame);
        document.getElementById('restart-button').addEventListener('click', startGame);

        resizeCanvas();
    </script>
</body>
</html>
```

#### **TEMPLATE D: THE DYNAMIC STACKING GAME**
* **Best for:** Hierarchy, structure, sequence (e.g., Food Pyramid, Layers of the Earth, Taxonomy).
* **Gameplay:** Player moves a platform to catch randomly falling blocks in the correct order.

```html
<!-- TEMPLATE D: DYNAMIC STACKING GAME -->
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title><!-- 1. TOPIC --> Stacker</title>
    <style>
        body, html { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; font-family: sans-serif; }
        #game-container { width: 100%; height: 100%; position: relative; background-color: #d0e7f9; }
        canvas { display: block; }
        #ui-bar { position: absolute; top: 10px; width: 100%; text-align: center; color: #333; font-size: 1.5em; font-weight: bold; }
        .overlay { position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center; color: white; z-index: 10; }
        .overlay h1 { font-size: 3em; } .overlay p { font-size: 1.2em; max-width: 80%; } .overlay button { font-size: 1.5em; padding: 0.5em 1.5em; border: none; border-radius: 8px; background: #28a745; color: white; cursor: pointer; margin-top: 20px; }
    </style>
</head>
<body>
    <div id="game-container">
        <canvas id="gameCanvas"></canvas>
        <div id="ui-bar">Catch This: <span id="next-block"></span></div>
        <div id="start-screen" class="overlay">
            <h1><!-- 2. GAME_TITLE --></h1>
            <p><!-- 3. GAME_INSTRUCTIONS --></p>
            <button id="start-button">Start</button>
        </div>
        <div id="end-screen" class="overlay" style="display: none;">
            <h1 id="end-message"></h1>
            <button id="restart-button">Play Again</button>
        </div>
    </div>
    <script>
        const canvas = document.getElementById('gameCanvas');
        const ctx = canvas.getContext('2d');
        const nextBlockEl = document.getElementById('next-block');
        let platform, fallingObjects, stackedBlocks, currentBlockIndex, gameLoopId, spawnInterval;
        
        // <!-- 4. DEFINE THE ORDERED BLOCKS TO STACK -->
        const buildOrder = [
            { name: 'Grains', color: '#f39c12'},
            { name: 'Vegetables', color: '#2ecc71'},
            { name: 'Fruits', color: '#e74c3c'},
            { name: 'Protein', color: '#9b59b6'}
        ];

        function resizeCanvas() { canvas.width = window.innerWidth; canvas.height = window.innerHeight; }

        function init() {
            platform = { x: canvas.width / 2 - 75, y: canvas.height - 50, width: 150, height: 20 };
            stackedBlocks = [];
            fallingObjects = [];
            currentBlockIndex = 0;
            updateNextBlockUI();
        }
        
        function updateNextBlockUI(){
            if (currentBlockIndex < buildOrder.length) {
                nextBlockEl.textContent = buildOrder[currentBlockIndex].name;
            } else {
                nextBlockEl.textContent = 'Done!';
            }
        }

        function spawnObject() {
            const shouldSpawnCorrect = Math.random() > 0.4; // 60% chance to spawn the needed block
            let blockToSpawn;
            if (shouldSpawnCorrect && currentBlockIndex < buildOrder.length) {
                blockToSpawn = buildOrder[currentBlockIndex];
            } else {
                const incorrectOptions = buildOrder.filter((_, index) => index !== currentBlockIndex);
                if (incorrectOptions.length > 0) {
                   blockToSpawn = incorrectOptions[Math.floor(Math.random() * incorrectOptions.length)];
                } else {
                   return;
                }
            }
            fallingObjects.push({ x: Math.random() * (canvas.width - 100), y: -30, width: 100, height: 30, color: blockToSpawn.color, name: blockToSpawn.name, vy: 2 + (currentBlockIndex * 0.5) });
        }
        
        function gameLoop() {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.fillStyle = '#34495e';
            ctx.fillRect(platform.x, platform.y, platform.width, platform.height);

            for (let i = fallingObjects.length - 1; i >= 0; i--) {
                const block = fallingObjects[i];
                block.y += block.vy;

                if (block.y + block.height >= platform.y && block.x < platform.x + platform.width && block.x + block.width > platform.x) {
                    if (block.name === buildOrder[currentBlockIndex].name) {
                        block.y = platform.y - (stackedBlocks.length + 1) * block.height;
                        block.x = platform.x + (platform.width - block.width)/2;
                        stackedBlocks.push(block);
                        currentBlockIndex++;
                        updateNextBlockUI();
                        if (currentBlockIndex >= buildOrder.length) endGame(true);
                    } else {
                        endGame(false);
                    }
                    fallingObjects.splice(i, 1);
                } else if (block.y > canvas.height) {
                    fallingObjects.splice(i, 1);
                }
            }
            
            [...stackedBlocks, ...fallingObjects].forEach(block => {
                ctx.fillStyle = block.color;
                ctx.fillRect(block.x, block.y, block.width, block.height);
                ctx.fillStyle = 'white'; ctx.font = 'bold 14px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
                ctx.fillText(block.name, block.x + block.width / 2, block.y + block.height / 2);
            });
            gameLoopId = requestAnimationFrame(gameLoop);
        }

        function movePlatform(event) {
            const rect = canvas.getBoundingClientRect();
            platform.x = (event.clientX || event.touches[0].clientX) - rect.left - platform.width / 2;
        }

        function startGame() {
            document.getElementById('start-screen').style.display = 'none';
            document.getElementById('end-screen').style.display = 'none';
            init();
            spawnInterval = setInterval(spawnObject, 1800);
            gameLoopId = requestAnimationFrame(gameLoop);
        }

        function endGame(isWin) {
            cancelAnimationFrame(gameLoopId);
            clearInterval(spawnInterval);
            document.getElementById('end-message').textContent = isWin ? 'Pyramid Complete!' : 'Wrong Block! Tower Collapsed!';
            document.getElementById('end-screen').style.display = 'flex';
        }
        
        document.getElementById('start-button').addEventListener('click', startGame);
        document.getElementById('restart-button').addEventListener('click', startGame);
        canvas.addEventListener('mousemove', movePlatform);
        canvas.addEventListener('touchmove', (e) => { e.preventDefault(); movePlatform(e); }, { passive: false });
        window.addEventListener('resize', resizeCanvas);
        resizeCanvas();
    </script>
</body>
</html>
```

---
#### **TEMPLATE E: THE MATCHING GAME (NEW!)**
* **Best for:** Vocabulary, definitions, matching pairs (e.g., Country & Capital, Animal & Habitat).
* **Gameplay:** A grid of cards is shown. The player clicks two cards to flip them over. If they match, they stay open. Match all pairs to win.

```html
<!-- TEMPLATE E: MATCHING GAME -->
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title><!-- 1. TOPIC --> Match</title>
    <style>
        body { font-family: sans-serif; text-align: center; background: #f0f3f4; }
        #game-board { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; max-width: 600px; margin: 20px auto; }
        .card { width: 100%; aspect-ratio: 1 / 1; background: #3498db; border-radius: 8px; cursor: pointer; display: flex; justify-content: center; align-items: center; font-size: 1.2em; color: white; transition: transform 0.5s; transform-style: preserve-3d; }
        .card.flipped, .card.matched { transform: rotateY(180deg); background: #9b59b6; }
        .card-content { backface-visibility: hidden; position: absolute; }
        .card-back { transform: rotateY(180deg); }
        #ui-bar { font-size: 1.5em; margin: 10px; }
    </style>
</head>
<body>
    <h1><!-- 2. GAME_TITLE --></h1>
    <div id="ui-bar">Moves: <span id="moves">0</span></div>
    <div id="game-board"></div>
    <script>
        const gameBoard = document.getElementById('game-board');
        const movesSpan = document.getElementById('moves');
        let moves = 0, firstCard = null, secondCard = null, lockBoard = false, matchedPairs = 0;

        // <!-- 3. DEFINE YOUR MATCHING PAIRS. Must be an even number of items. -->
        const items = ['Dog', 'Cat', 'Bird', 'Fish', 'Lion', 'Tiger', 'Bear', 'Wolf'];
        const cardValues = [...items, ...items].sort(() => 0.5 - Math.random());
        
        function createBoard() {
            gameBoard.innerHTML = '';
            cardValues.forEach(value => {
                const card = document.createElement('div');
                card.classList.add('card');
                card.dataset.value = value;
                card.innerHTML = `
                    <div class="card-content card-front"></div>
                    <div class="card-content card-back">${value}</div>
                `;
                gameBoard.appendChild(card);
                card.addEventListener('click', flipCard);
            });
        }

        function flipCard() {
            if (lockBoard || this === firstCard) return;
            this.classList.add('flipped');

            if (!firstCard) {
                firstCard = this;
                return;
            }
            secondCard = this;
            lockBoard = true;
            moves++;
            movesSpan.textContent = moves;
            checkForMatch();
        }

        function checkForMatch() {
            const isMatch = firstCard.dataset.value === secondCard.dataset.value;
            isMatch ? disableCards() : unflipCards();
        }

        function disableCards() {
            firstCard.classList.add('matched');
            secondCard.classList.add('matched');
            matchedPairs++;
            if (matchedPairs === items.length) {
                setTimeout(() => alert(`You win! Total moves: ${moves}`), 500);
            }
            resetBoard();
        }

        function unflipCards() {
            setTimeout(() => {
                firstCard.classList.remove('flipped');
                secondCard.classList.remove('flipped');
                resetBoard();
            }, 1000);
        }

        function resetBoard() {
            [firstCard, secondCard, lockBoard] = [null, null, false];
        }

        createBoard();
    </script>
</body>
</html>
```

---
#### **TEMPLATE F: THE MAZE RUNNER GAME (NEW!)**
* **Best for:** Journeys, paths, avoiding obstacles (e.g., Blood Circulation, Digestive Tract, A-maze-ing Facts).
* **Gameplay:** Player uses arrow keys or clicks/drags to navigate a character from a start point to an end point through a maze.

```html
<!-- TEMPLATE F: MAZE RUNNER GAME -->
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title><!-- 1. TOPIC --> Maze</title>
    <style>
        body { font-family: sans-serif; text-align: center; background: #2c3e50; color: white; }
        canvas { background: #ecf0f1; border-radius: 8px; }
        h1 { margin-top: 10px; }
        p { font-size: 1.2em; }
    </style>
</head>
<body>
    <h1><!-- 2. GAME_TITLE --></h1>
    <p><!-- 3. GAME_INSTRUCTIONS --></p>
    <canvas id="mazeCanvas" width="500" height="500"></canvas>
    <script>
        const canvas = document.getElementById('mazeCanvas');
        const ctx = canvas.getContext('2d');
        
        // <!-- 4. DEFINE THE MAZE. 0 = path, 1 = wall, 2 = start, 3 = end. -->
        const maze = [
            [2, 0, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 0, 0, 0, 0, 0, 0, 0, 0, 1],
            [1, 1, 1, 0, 1, 1, 1, 1, 0, 1],
            [1, 0, 0, 0, 1, 0, 0, 0, 0, 1],
            [1, 0, 1, 1, 1, 0, 1, 1, 1, 1],
            [1, 0, 0, 1, 0, 0, 0, 0, 0, 1],
            [1, 1, 0, 1, 0, 1, 1, 1, 0, 1],
            [1, 0, 0, 0, 0, 1, 0, 0, 0, 1],
            [1, 1, 1, 1, 1, 1, 0, 1, 0, 3],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
        ];

        const cellSize = canvas.width / maze[0].length;
        let playerPos = { x: 0, y: 0 };

        function findStart() {
            for (let y = 0; y < maze.length; y++) {
                for (let x = 0; x < maze[y].length; x++) {
                    if (maze[y][x] === 2) {
                        playerPos = { x, y };
                        return;
                    }
                }
            }
        }

        function drawMaze() {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            for (let y = 0; y < maze.length; y++) {
                for (let x = 0; x < maze[y].length; x++) {
                    if (maze[y][x] === 1) ctx.fillStyle = '#34495e'; // Wall
                    else if (maze[y][x] === 3) ctx.fillStyle = '#2ecc71'; // End
                    else ctx.fillStyle = '#ecf0f1'; // Path
                    ctx.fillRect(x * cellSize, y * cellSize, cellSize, cellSize);
                }
            }
            // Draw Player
            ctx.fillStyle = '#e74c3c';
            ctx.beginPath();
            ctx.arc(playerPos.x * cellSize + cellSize / 2, playerPos.y * cellSize + cellSize / 2, cellSize / 3, 0, Math.PI * 2);
            ctx.fill();
        }

        function movePlayer(dx, dy) {
            const newX = playerPos.x + dx;
            const newY = playerPos.y + dy;
            if (newX >= 0 && newX < maze[0].length && newY >= 0 && newY < maze.length && maze[newY][newX] !== 1) {
                playerPos.x = newX;
                playerPos.y = newY;
                drawMaze();
                if (maze[newY][newX] === 3) {
                    setTimeout(() => {
                        alert('You reached the end!');
                        findStart();
                        drawMaze();
                    }, 100);
                }
            }
        }

        window.addEventListener('keydown', (e) => {
            switch(e.key) {
                case 'ArrowUp': movePlayer(0, -1); break;
                case 'ArrowDown': movePlayer(0, 1); break;
                case 'ArrowLeft': movePlayer(-1, 0); break;
                case 'ArrowRight': movePlayer(1, 0); break;
            }
        });

        findStart();
        drawMaze();
    </script>
</body>
</html>
```
---
#### **TEMPLATE G: THE SORTING GAME (NEW!)**
---
* **Best for:** Classification, grouping (e.g., States of Matter, Animal Classes, Food Groups).
* **Gameplay:** Items fall from the top. The player clicks an item to "pick it up," then clicks the correct category box at the bottom to score.

```html
<!-- TEMPLATE G: SORTING GAME -->
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title><!-- 1. TOPIC --> Sorter</title>
    <style>
        body, html { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; font-family: sans-serif; }
        #game-container { width: 100%; height: 100%; position: relative; background-color: #ecf0f1; }
        canvas { display: block; }
        #score-bar { position: absolute; top: 10px; right: 10px; font-size: 1.5em; font-weight: bold; }
        .overlay { position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center; color: white; z-index: 10; }
        .overlay h1 { font-size: 3em; } .overlay p { font-size: 1.2em; max-width: 80%; } .overlay button { font-size: 1.5em; padding: 0.5em 1.5em; border: none; border-radius: 8px; background: #28a745; color: white; cursor: pointer; margin-top: 20px; }
    </style>
</head>
<body>
    <div id="game-container">
        <canvas id="gameCanvas"></canvas>
        <div id="score-bar">Score: 0</div>
        <div id="start-screen" class="overlay">
            <h1><!-- 2. GAME_TITLE --></h1>
            <p><!-- 3. GAME_INSTRUCTIONS --></p>
            <button id="start-button">Start</button>
        </div>
        <div id="end-screen" class="overlay" style="display: none;">
            <h1 id="end-message"></h1>
            <button id="restart-button">Play Again</button>
        </div>
    </div>
    <script>
        const canvas = document.getElementById('gameCanvas');
        const ctx = canvas.getContext('2d');
        const scoreEl = document.getElementById('score-bar');
        let score, fallingObjects, categories, selectedObject, gameLoopId, spawnInterval;

        // <!-- 4. DEFINE CATEGORIES AND ITEMS -->
        const gameConfig = {
            categories: [
                { name: 'Solid', color: '#3498db' },
                { name: 'Liquid', color: '#2ecc71' },
                { name: 'Gas', color: '#9b59b6' }
            ],
            items: [
                { name: 'Ice', category: 'Solid' },
                { name: 'Water', category: 'Liquid' },
                { name: 'Steam', category: 'Gas' },
                { name: 'Rock', category: 'Solid' },
                { name: 'Milk', category: 'Liquid' },
                { name: 'Air', category: 'Gas' }
            ]
        };

        function resizeCanvas() { canvas.width = window.innerWidth; canvas.height = window.innerHeight; setupCategories(); }

        function setupCategories() {
            const catWidth = canvas.width / gameConfig.categories.length;
            categories = gameConfig.categories.map((cat, i) => ({
                ...cat,
                x: i * catWidth, y: canvas.height - 100, width: catWidth, height: 100
            }));
        }

        function FallingObject() {
            const item = gameConfig.items[Math.floor(Math.random() * gameConfig.items.length)];
            this.name = item.name;
            this.category = item.category;
            this.radius = 30;
            this.x = Math.random() * (canvas.width - this.radius * 2) + this.radius;
            this.y = -this.radius;
            this.vy = Math.random() * 1 + 1;
            this.draw = function(isSelected) {
                ctx.beginPath();
                ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
                ctx.fillStyle = isSelected ? '#f1c40f' : '#7f8c8d';
                ctx.fill();
                if(isSelected) {
                    ctx.strokeStyle = '#f39c12';
                    ctx.lineWidth = 5;
                    ctx.stroke();
                }
                ctx.fillStyle = 'white'; ctx.font = '14px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
                ctx.fillText(this.name, this.x, this.y);
            };
        }

        function handleInteraction(event) {
            event.preventDefault();
            const rect = canvas.getBoundingClientRect();
            const x = (event.clientX || event.touches[0].clientX) - rect.left;
            const y = (event.clientY || event.touches[0].clientY) - rect.top;

            if (selectedObject) {
                // Try to drop the object in a category
                for (const cat of categories) {
                    if (x > cat.x && x < cat.x + cat.width && y > cat.y && y < cat.y + cat.height) {
                        if (selectedObject.category === cat.name) {
                            score += 10;
                        } else {
                            score -= 5;
                        }
                        scoreEl.textContent = `Score: ${score}`;
                        fallingObjects.splice(fallingObjects.indexOf(selectedObject), 1);
                        selectedObject = null;
                        return;
                    }
                }
            } else {
                // Try to select an object
                for (let i = fallingObjects.length - 1; i >= 0; i--) {
                    const obj = fallingObjects[i];
                    if (Math.sqrt((x - obj.x)**2 + (y - obj.y)**2) < obj.radius) {
                        selectedObject = obj;
                        return;
                    }
                }
            }
        }
        
        function gameLoop() {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            // Draw categories
            categories.forEach(cat => {
                ctx.fillStyle = cat.color;
                ctx.fillRect(cat.x, cat.y, cat.width, cat.height);
                ctx.fillStyle = 'white'; ctx.font = 'bold 20px sans-serif'; ctx.textAlign = 'center';
                ctx.fillText(cat.name, cat.x + cat.width / 2, cat.y + 50);
            });
            // Draw falling objects
            fallingObjects.forEach((obj, i) => {
                if (obj !== selectedObject) obj.y += obj.vy;
                obj.draw(obj === selectedObject);
                if (obj.y > canvas.height + obj.radius) fallingObjects.splice(i, 1);
            });
            gameLoopId = requestAnimationFrame(gameLoop);
        }

        function spawnObject() {
            if(fallingObjects.length < 10) fallingObjects.push(new FallingObject());
        }

        function startGame() {
            // ... standard start game logic
        }

        function endGame(isWin) {
            // ... standard end game logic
        }
        
        // ... standard event listeners
        
        resizeCanvas();
    </script>
</body>
</html>
```

Now, your task is to call this API with "TOPIC_PLACEHOLDER" replaced by the user's desired topic.
"""


# NOTE: This assumes you have a decorator named @token_required in your project.
# You will need to import it into this file, e.g., from my_app.decorators import token_required
@game_bp.route('/generate_game', methods=['POST', 'OPTIONS'])
def generate_game_route():
    
    # --- START OF THE FIX ---
    # This is the crucial part. We immediately handle the preflight OPTIONS request
    # by returning a successful response before any other code runs.
    if request.method == 'OPTIONS':
        # You can create a more sophisticated response, but a simple 200 is often enough
        # The CORS headers are handled by your Flask-CORS extension.
        return jsonify({'status': 'ok'}), 200
    # --- END OF THE FIX ---
    
    # In a real app, you'd get the current_user_id from the decorator
    # For now, we'll simulate it for structure.
    # current_user_id = g.user_id 

    # NOTE: The 'db' object and 'genai' should be initialized in your main app.py
    # and accessed here, perhaps via current_app.
    db = firestore.client()
    gemini_api_key = os.getenv('GEMINI_API_KEY')
    if not gemini_api_key:
        return jsonify({"error": "AI service not configured"}), 500
    genai.configure(api_key=gemini_api_key)
    
    data = request.get_json()
    if not data or not data.get('topic'):
        return jsonify({"error": "Topic is required to generate a game"}), 400

    topic = data.get('topic').strip()
    # This is a placeholder user ID. In your real app, this would come from the auth token.
    current_user_id = "placeholder_user_id_for_testing"
    
    # Simple function to create a firestore-safe ID
    def sanitize_word_for_id(word):
        return "".join(c for c in word if c.isalnum()).lower()

    sanitized_topic_id = sanitize_word_for_id(topic)
    user_word_history_ref = db.collection('users').document(current_user_id).collection('word_history').document(sanitized_topic_id)

    try:
        word_doc = user_word_history_ref.get()
        if word_doc.exists and 'game_html' in word_doc.to_dict().get('generated_content_cache', {}):
            current_app.logger.info(f"Serving cached game for topic '{topic}' to user {current_user_id}.")
            cached_html = word_doc.to_dict()['generated_content_cache']['game_html']
            return jsonify({"topic": topic, "game_html": cached_html, "source": "cache"})
        
        else:
            current_app.logger.info(f"Generating new game for topic '{topic}' for user {current_user_id}.")
            
            prompt = PROMPT_TEMPLATE.replace("TOPIC_PLACEHOLDER", topic)
            
            gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')
            safety_settings = {HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE}
            
            response = gemini_model.generate_content(prompt, safety_settings=safety_settings)
            
            generated_text = response.text.strip()
            
            html_start_index = generated_text.find('<!DOCTYPE html>')
            if html_start_index == -1:
                html_start_index = generated_text.find('<')

            if html_start_index != -1:
                reasoning = generated_text[:html_start_index].strip()
                generated_html = generated_text[html_start_index:]
                current_app.logger.info(f"AI reasoning for topic '{topic}': {reasoning}")

                if generated_html.startswith("```html"):
                    generated_html = generated_html[7:].strip()
                if generated_html.endswith("```"):
                    generated_html = generated_html[:-3].strip()
            else:
                generated_html = f"<p>Error: AI did not generate valid HTML. Full response: {generated_text}</p>"
                current_app.logger.error(f"AI failed to generate valid HTML for topic '{topic}'")

            update_payload = {
                'word': topic,
                'last_explored_at': firestore.SERVER_TIMESTAMP,
                'generated_content_cache': {'game_html': generated_html}
            }
            user_word_history_ref.set(update_payload, merge=True)
            
            return jsonify({"topic": topic, "game_html": generated_html, "source": "generated"})

    except Exception as e:
        current_app.logger.error(f"Error in /generate_game for user {current_user_id}, topic '{topic}': {e}")
        return jsonify({"error": f"An internal error occurred while trying to build the game: {e}"}), 500
