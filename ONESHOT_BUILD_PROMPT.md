# One-Shot Build Prompt For FluentAI

You are a senior full-stack AI product engineer. Build a working MVP called FluentAI, an agentic language learning app with two first-class modes: Lesson Mode and Conversation Mode. The app must be runnable locally, persist learner memory between runs, use OpenAI models when an API key is available, and fall back to deterministic local behavior when no API key is available. The finished product must feel like a real demo for judges, not a stub.

## Core Product Vision

FluentAI teaches a target language, default Spanish, through an always-on agent crew.

The product has two modes:

1. Lesson Mode
   - The app remembers the learner's current level and progress.
   - It autonomously generates daily personalized lessons.
   - It generates adaptive quizzes.
   - It evaluates answers.
   - It updates the learner profile.
   - It prints clear agent logs so judges can see what each agent is doing.

2. Conversation Mode
   - The app feels like a FaceTime-style AI tutor session.
   - The AI initiates the conversation instead of waiting for the learner.
   - The AI steers the conversation based on the learner's judged ability so far.
   - Beginner learners get simple prompts about names, weather, food, likes, and visible objects.
   - Advanced learners get richer topics such as politics, the environment, culture, work, and debate.
   - The learner can turn video on or off.
   - With video off, the conversation works as normal voice/text chat.
   - With video on, the app can use visible object context such as "apple" to continue the target-language conversation.
   - Example: if the learner shows or labels an apple, the tutor should say something like "Esto es una manzana. ¿Te gusta la manzana?"
   - Conversation results update the same persistent profile used by Lesson Mode.

## Recommended Tech Stack

Build a simple Python project that runs locally.

Use:
- Python 3.10+
- Standard library for the default local web UI so the app does not require a heavy framework.
- Optional Gradio UI if available, but do not make it required.
- OpenAI Python SDK for model calls.
- JSON file storage for persistent memory.
- `unittest` for tests.

Avoid:
- Requiring a database for the MVP.
- Requiring paid external services besides optional OpenAI API usage.
- Requiring live webcam APIs for the first MVP. Simulate video context with a visible object label or uploaded frame placeholder. Structure the code so real webcam/vision can be added later.

## OpenAI Models And API Use

Use OpenAI only when `OPENAI_API_KEY` is set.

Environment variables:

```bash
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5.5
OPENAI_REASONING_EFFORT=low
OPENAI_VERBOSITY=low
```

Defaults:
- `OPENAI_MODEL`: `gpt-5.5`
- `OPENAI_REASONING_EFFORT`: `low`
- `OPENAI_VERBOSITY`: `low`

Use the OpenAI Responses API for:
- Lesson enhancement.
- Conversation tutor utterances.
- Future vision/image understanding.

For future live voice:
- Use OpenAI Realtime voice-agent sessions with `gpt-realtime-2`.
- Browser audio should use WebRTC.
- Keep this as an upgrade path, not a hard dependency for the MVP.

For future image/video:
- Use Responses API image input with `input_image`.
- For the MVP, support `--video on --video-object apple` as deterministic visible-object context.

The app must never print the API key.

If the OpenAI call fails, show a clear non-secret log such as:

```text
[OpenAI Model Agent] Using local fallback after API issue: RateLimitError
```

The app must still work without OpenAI.

## Required Files

Create this structure:

```text
.
├── .env.example
├── .gitignore
├── AGENTS.md
├── README.md
├── ONESHOT_BUILD_PROMPT.md
├── data/
│   └── progress.json
├── fluent_ai/
│   ├── __init__.py
│   ├── agent.py
│   ├── app.py
│   ├── config.py
│   ├── conversation.py
│   ├── openai_provider.py
│   ├── state.py
│   ├── ui.py
│   └── web.py
├── macos/
│   └── desktop_app.py
├── notes.md
├── plan.md
├── pyproject.toml
├── scripts/
│   └── build_mac_app.sh
└── tests/
    └── test_agent.py
```

## Persistent Memory Schema

Store learner memory in:

```text
data/progress.json
```

The file must be human-readable JSON.

Include:

```json
{
  "learner": {
    "name": "Demo Learner",
    "target_language": "Spanish",
    "current_level": "A1",
    "level": "A1",
    "xp": 0,
    "streak_days": 1,
    "learning_goals": [
      "Hold a simple 5-minute conversation",
      "Build useful daily vocabulary",
      "Improve conjugation accuracy"
    ]
  },
  "weak_topics": ["past tense", "conjugations", "vocabulary"],
  "skills": {
    "vocabulary": 0.34,
    "grammar": 0.28,
    "conjugations": 0.26,
    "reading": 0.32,
    "translation": 0.30
  },
  "topic_mastery": {
    "cafe orders": 0.34,
    "introductions": 0.36,
    "daily routines": 0.32,
    "past tense": 0.24,
    "conjugations": 0.25,
    "vocabulary": 0.34
  },
  "preferences": {
    "lesson_minutes": 10,
    "daily_quiz_questions": 6,
    "tone": "encouraging and specific"
  },
  "recent_topics": [],
  "history": [],
  "daily_summary": {
    "last_sent_at": null,
    "lessons_completed": 0
  },
  "conversation_memory": {
    "sessions_completed": 0,
    "total_turns": 0,
    "fluency_score": 0.3,
    "speaking_confidence": 0.3,
    "recent_topics": [],
    "missed_phrases": [],
    "last_video_object": null,
    "next_speaking_goal": "Answer simple questions in full Spanish sentences."
  },
  "updated_at": "..."
}
```

Levels must support:

```text
A1, A2, B1, B2, C1, C2
```

## Agents To Implement

Implement these as clear modules/functions. They can be simple classes or functions but their logs must make them feel like a crew.

### Memory Agent

Responsibilities:
- Load `data/progress.json`.
- Migrate older schemas safely.
- Save updates after lessons and conversations.
- Track current level, weak topics, goals, streak, XP, skills, topic mastery, and conversation memory.

Console log examples:

```text
[Memory Agent] Loaded level A1 with weak topics: past tense, conjugations, vocabulary.
[Memory Agent] Next speaking goal: Add one extra detail after each basic answer.
```

### Lesson Generator Agent

Responsibilities:
- Create a 5-10 minute lesson.
- Use current level and weak topics.
- Include vocabulary, grammar explanation, examples, and a micro task.
- Use OpenAI Responses API if available.
- Fall back to deterministic lesson bank if OpenAI is unavailable.

Lesson output shape:

```python
{
  "language": "Spanish",
  "level": "A1",
  "topic": "past tense",
  "focus_skill": "conjugations",
  "difficulty": "steady",
  "minutes": 10,
  "vocabulary": [["ayer", "yesterday"], ...],
  "grammar_explanation": "...",
  "examples": [["Ayer fui al mercado.", "Yesterday I went to the market."], ...],
  "micro_task": "Use one Spanish sentence about past tense before the next cycle."
}
```

### Adaptive Quiz Agent

Responsibilities:
- Generate 5-8 questions.
- Include multiple choice, fill-in-the-blank, and open-ended questions.
- Make questions easier if past performance is low.
- Make questions harder if past performance is high.
- Use the lesson topic and current weaknesses.

Question output shape:

```python
{
  "type": "fill_blank",
  "skill": "conjugations",
  "topic": "past tense",
  "prompt": "Fill in the blank: Ayer ___ al mercado.",
  "answer": "fui",
  "acceptable_answers": ["fui"]
}
```

### Evaluator And Feedback Agent

Responsibilities:
- Grade quiz answers.
- Grade conversation turns.
- Give encouraging, specific feedback.
- Update skills and topic mastery.
- Update weak topics.
- Add history entries.

Feedback examples:

```text
Good retrieval. Keep using 'fui' in short personal sentences.
Nice attempt. Include one lesson keyword or model phrase, such as 'Ayer fui al mercado.'
```

### Conversation Orchestrator

Responsibilities:
- Start Conversation Mode.
- Load memory.
- Decide video on/off.
- Pick a topic based on learner level and recent conversation.
- Make the AI initiate the conversation.
- Run a configurable number of turns.
- Save conversation memory.

CLI command:

```bash
python -m fluent_ai.app --product-mode conversation --turns 4 --video off --mode auto
```

Video-object command:

```bash
python -m fluent_ai.app --product-mode conversation --turns 4 --video on --video-object apple --mode auto
```

### Speaking Tutor Agent

Responsibilities:
- Produce the next tutor utterance.
- Speak mostly in the target language.
- For A1/A2, use short simple language and a model phrase.
- For B1/B2, ask for reasons, examples, and opinions.
- For C1/C2, discuss nuanced topics.
- If video context exists, use it naturally.

Beginner examples:

```text
Hola, yo empiezo. ¿Como te llamas? (Model answer: Me llamo Ana.)
Hola. ¿Que tiempo hace hoy? (Model answer: Hace sol.)
Veo una manzana. Esto es una manzana. ¿Te gusta la manzana?
```

Advanced examples:

```text
Quiero debatir contigo: ¿cual es el problema ambiental mas importante en tu ciudad?
Analicemos una idea: ¿deberian los gobiernos regular mas la inteligencia artificial?
Defiende una postura matizada: ¿como equilibrarias crecimiento economico y proteccion ambiental?
```

### Vision Context Agent

MVP responsibilities:
- Support video on/off.
- When video is off, run normal text/voice conversation.
- When video is on, use a provided visible object label such as `apple`.
- Map common objects to Spanish:
  - apple -> manzana
  - banana -> platano
  - book -> libro
  - cup -> taza

Future responsibilities:
- Accept camera frames.
- Send frames to Responses API as `input_image`.
- Convert visual observations into conversation context.

### Progress Reporter Agent

Responsibilities:
- Print a progress summary after each lesson.
- Include streak, lessons completed, and improvement.

Example:

```text
You improved 9% in vocabulary this cycle. Streak: 1 days. Lessons completed: 1.
```

## CLI Requirements

Implement a CLI in `fluent_ai/app.py`.

Lesson Mode:

```bash
python -m fluent_ai.app --duration-minutes 5 --interval-seconds 60 --mode auto
```

One lesson:

```bash
python -m fluent_ai.app --once --mode auto
```

Interactive lesson:

```bash
python -m fluent_ai.app --once --mode interactive
```

Conversation Mode:

```bash
python -m fluent_ai.app --product-mode conversation --turns 4 --video off --mode auto
```

Video object demo:

```bash
python -m fluent_ai.app --product-mode conversation --turns 4 --video on --video-object apple --mode auto
```

The CLI must print named agent logs.

## Web UI Requirements

Implement a no-dependency local web app in `fluent_ai/web.py`.

Command:

```bash
python -m fluent_ai.web --port 7860
```

The UI must have:
- Header with product name and OpenAI/model status.
- Lesson Mode button.
- Conversation Mode button.
- Conversation turns input.
- Video on/off selector.
- Visible object input.
- A video-call-like preview panel.
- Agent output panel.

The web UI must call local endpoints:
- `GET /`
- `GET /api/status`
- `GET /api/progress`
- `POST /api/lesson`
- `POST /api/conversation`

The UI must work without Gradio.

Also implement optional Gradio UI in `fluent_ai/ui.py` if Gradio is installed, but the no-dependency web app is the primary MVP UI.

## Standalone Mac App Requirements

Implement a standalone macOS app bundle so the product can run without the browser.

Command:

```bash
./scripts/build_mac_app.sh
open dist/FluentAI.app
```

The Mac app must:
- Launch as `dist/FluentAI.app`.
- Open fullscreen by default.
- Be usable without visiting a browser URL.
- Show a compact native desktop UI with:
  - product header
  - OpenAI/model status
  - video-call-like preview area
  - conversation turns input
  - video on/off selector
  - visible object input
  - Run Lesson button
  - Start Conversation button
  - scrollable agent output transcript
- Call the same Python agent engine used by CLI/web.
- Read the same `.env` and `data/progress.json`.
- Keep Escape as a way to leave fullscreen.
- Keep Command-Q as a way to quit.

If Swift/AppKit compilation is unavailable, use a reliable fallback such as a Tk-based native window launched from a `.app` bundle. The app does not need live webcam capture for the MVP; video-on context can be simulated with a visible object label.

## Styling Requirements

Make the UI feel like a compact learning tool, not a marketing page.

Use:
- Dense but readable layout.
- Two-column desktop layout.
- Single-column mobile layout.
- Clear controls.
- A video-call style preview area.
- A large output panel showing agent logs/transcripts.

Avoid:
- A landing page.
- Huge hero sections.
- Decorative blobs/orbs.
- Overly purple or one-note color palettes.

## OpenAI Provider Requirements

Implement `fluent_ai/openai_provider.py`.

It must:
- Load `.env`.
- Read `OPENAI_API_KEY`.
- Read optional `OPENAI_MODEL`.
- Read optional `OPENAI_REASONING_EFFORT`.
- Read optional `OPENAI_VERBOSITY`.
- Use `OpenAI().responses.create(...)`.
- Never print the API key.
- Expose `status()`.
- Expose `health_check()`.
- Expose `enhance_lesson(...)`.
- Expose `conversation_tutor_reply(...)`.
- Return fallback-compatible values if model calls fail.

The lesson enhancement prompt must ask for JSON only with:

```json
{
  "vocabulary": [["target-language phrase", "English meaning"]],
  "grammar_explanation": "string",
  "examples": [["target-language sentence", "English meaning"]],
  "micro_task": "string"
}
```

The conversation tutor prompt must return only the next tutor utterance.

## Deterministic Fallback Requirements

The app must have a local lesson bank for Spanish.

Minimum topics:
- introductions
- cafe orders
- daily routines
- past tense
- conjugations
- vocabulary

Conversation topics by level:

A1:
- introductions
- weather
- likes and food

A2:
- daily routines
- past weekend

B1:
- opinions
- work and goals

B2:
- environment
- culture

C1:
- politics and civic life

C2:
- environmental policy

Fallback behavior must be good enough for a demo even without OpenAI.

## Tests

Use `unittest`.

Tests must verify:
- A lesson quiz updates XP/history/recent topics.
- Quiz has 5-8 questions.
- Quiz includes multiple choice, fill-in-the-blank, and open-ended questions.
- Conversation Mode initiates with tutor text.
- Conversation Mode updates `conversation_memory`.
- Video object `apple` steers the conversation toward `manzana`.
- Advanced level C1/C2 selects advanced or near-native topics.

Command:

```bash
python -m unittest discover -s tests -q
```

## README Requirements

README must include:
- Product summary.
- MVP features.
- API key setup with `.env`.
- Lesson Mode commands.
- Conversation Mode commands.
- Web app command.
- Optional UI command.
- Demo story.
- Roadmap.

## AGENTS.md Requirements

Create `AGENTS.md` with:
- Product goal.
- Lesson Mode behavior.
- Conversation Mode behavior.
- Goal-mode orchestration instructions.
- Instruction to keep `plan.md` current.
- Instruction to keep `notes.md` concise and update it with real progress.
- Instruction to adapt calmly if `plan.md` changes midway.

## Acceptance Criteria

The app is done when all are true:

- `python -m unittest discover -s tests -q` passes.
- `python -m fluent_ai.app --once --mode auto` runs a Lesson Mode cycle.
- `python -m fluent_ai.app --product-mode conversation --turns 4 --video off --mode auto` runs a text-only conversation.
- `python -m fluent_ai.app --product-mode conversation --turns 4 --video on --video-object apple --mode auto` starts a beginner object-grounded conversation using `manzana`.
- `python -m fluent_ai.web --port 7860` starts a local browser-testable app.
- `./scripts/build_mac_app.sh` creates `dist/FluentAI.app`.
- `open dist/FluentAI.app` launches a fullscreen standalone Mac app.
- The app reads `.env` and reports OpenAI enabled when `OPENAI_API_KEY` is present.
- The app never prints the API key.
- The app still works if OpenAI is unavailable.
- `data/progress.json` changes after lesson and conversation cycles.
- The UI clearly shows Lesson Mode, Conversation Mode, video on/off, visible object input, and agent output.

## Demo Script

1. Start the web app:

```bash
python -m fluent_ai.web --port 7860
```

2. Open:

```text
http://127.0.0.1:7860
```

3. Show model status in the header.

4. Click Run Lesson.

5. Show:
   - lesson topic
   - vocabulary
   - grammar
   - examples
   - quiz feedback
   - progress update

6. Set:
   - video: on
   - visible object: apple
   - turns: 4

7. Click Start Conversation.

8. Show:
   - AI initiates conversation.
   - Tutor says something about `manzana`.
   - Feedback is conversational.
   - Next speaking goal is saved.

9. Open `data/progress.json` and show:
   - `conversation_memory.sessions_completed`
   - `conversation_memory.total_turns`
   - `conversation_memory.last_video_object`
   - `history`

## Quality Bar

Build the simplest thing that fully demonstrates the product vision. Do not stop at architecture notes. Implement runnable code, tests, docs, and a browser-testable UI. Keep the code small, readable, and easy to extend into real voice/video later.
