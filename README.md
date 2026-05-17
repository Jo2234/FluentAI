# FluentAI

FluentAI is a small agentic language learning demo. A crew of simple agents reads local progress, creates a personalized mini-lesson, quizzes the learner, evaluates answers, updates mastery, and adapts the next cycle.

## MVP Features

- Persistent profile in `data/progress.json`: A1-C2 level, streak, weak topics, goals, skills, topic mastery, and history.
- Autonomous lesson generator: 5-10 minute lesson with vocabulary, grammar, examples, and a micro task.
- Adaptive quiz agent: 5-8 mixed questions across multiple choice, fill-in-the-blank, and open-ended answers.
- Evaluator and feedback agent: grades answers, gives specific encouragement, and updates weak topics.
- Autonomous loop: runs on demand or on an interval with clear named-agent console logs.
- Progress reporter and notification agents: print a ready alert and summary after each cycle.

## OpenAI API Key

Create a private `.env` file:

```bash
OPENAI_API_KEY=sk-your-real-key-here
OPENAI_MODEL=gpt-5.5
```

The app reads `.env` automatically. If the API is unavailable, it falls back to local deterministic agents.

## Run

Lesson Mode:

```bash
python -m fluent_ai.app --duration-minutes 5 --interval-seconds 60 --mode auto
```

Run one on-demand cycle:

```bash
python -m fluent_ai.app --once --mode auto
```

Use `--mode interactive` to answer quizzes yourself in the console.

```bash
python -m fluent_ai.app --once --language Spanish --mode interactive
```

Learner state is stored at `data/progress.json`.

Use `--max-cycles` to keep short demos bounded even with a low interval.

Conversation Mode:

```bash
python -m fluent_ai.app --product-mode conversation --turns 4 --video off --mode auto
```

Video-on object demo:

```bash
python -m fluent_ai.app --product-mode conversation --turns 4 --video on --video-object apple --mode auto
```

Web app:

```bash
python -m fluent_ai.web --port 7860
```

Then open `http://127.0.0.1:7860`.

Standalone Mac app:

```bash
npm install
npm run app
```

This builds and opens `dist/FluentAI.app`. The app launches fullscreen outside the browser, starts with no active conversation, and supports real quiz answers plus turn-by-turn tutor chat.

During development you can also run:

```bash
npm run desktop
```

Run tests:

```bash
python -m unittest discover -s tests -v
```

## Optional UI

Install the optional UI dependency and launch a small Gradio window:

```bash
python -m pip install -e ".[ui]"
python -m fluent_ai.ui
```

If Gradio is not installed, the UI command prints the console fallback. The UI includes Lesson Mode and Conversation Mode tabs.

## Roadmap

- Add OpenAI-backed lesson generation with deterministic fallback.
- Add spaced repetition scheduling.
- Add speaking/listening practice with audio.
