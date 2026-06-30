# FluentAI

FluentAI is a local-first agentic language-learning demo. It feels like a compact AI tutor studio: Lesson Mode generates adaptive lessons/quizzes, Conversation Mode starts a FaceTime-style tutor session, and both modes update the same persistent learner memory.

The project is intentionally demo-safe: it runs without API keys, never prints secrets, and uses deterministic fallback agents when OpenAI is unavailable.

## What works now

- **Lesson Mode**: personalized mini lesson, vocabulary, grammar, examples, adaptive quiz, grading, XP, weak-topic updates.
- **Conversation Mode**: tutor initiates, adapts to A1-C2 ability, supports text fallback, OpenAI Realtime voice path, and video context.
- **Video-object demo**: `--video on --video-object apple` reliably grounds beginner Spanish conversation around `manzana`.
- **Persistent memory**: `data/progress.json` tracks level, skills, topic mastery, streak, history, and speaking memory.
- **Browser UI**: standard-library local web server; no heavy framework required.
- **Desktop UI**: Electron shell with the same Python agent engine.
- **Offline tests/smoke**: no OpenAI, webcam, browser, or IBKR-style external service needed.

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m unittest discover -s tests -q
python scripts/smoke_demo.py
```

If you only want to run it without dev tools:

```bash
python -m pip install -e .
```

## Optional OpenAI setup

Create a private `.env` file:

```bash
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5.5
OPENAI_REASONING_EFFORT=low
OPENAI_VERBOSITY=low
```

If the key or SDK call is unavailable, FluentAI logs a safe fallback reason and continues locally. It never prints the API key.

## CLI demos

One lesson cycle:

```bash
python -m fluent_ai.app --once --mode auto
```

Interactive lesson:

```bash
python -m fluent_ai.app --once --language Spanish --mode interactive
```

Bounded autonomous lesson loop:

```bash
python -m fluent_ai.app --duration-minutes 5 --interval-seconds 60 --max-cycles 5 --mode auto
```

Conversation Mode:

```bash
python -m fluent_ai.app --product-mode conversation --turns 4 --video off --mode auto
```

Video-object conversation demo:

```bash
python -m fluent_ai.app --product-mode conversation --turns 4 --video on --video-object apple --mode auto
```

Use a disposable memory file while testing:

```bash
python -m fluent_ai.app --once --state-path /tmp/fluentai-progress.json
```

## Browser app

```bash
python -m fluent_ai.web --port 7860
```

Open `http://127.0.0.1:7860`. The UI exposes Lesson Mode, Conversation Mode, video on/off, visible object context, live profile state, and agent logs.

## Desktop app

```bash
npm ci
npm run desktop
```

Build a macOS `.app` bundle:

```bash
npm run build:app
open dist/FluentAI.app
```

The desktop app calls the same Python bridge/API as the CLI and web UI, so demo behavior stays consistent.

## Test and smoke commands

```bash
python -m unittest discover -s tests -q
python scripts/smoke_demo.py
python -m fluent_ai.app --once --mode auto --state-path /tmp/fluentai-lesson.json
python -m fluent_ai.app --product-mode conversation --turns 2 --video on --video-object apple --mode auto --state-path /tmp/fluentai-conversation.json
npm run check
```

CI runs these Python checks on 3.10, 3.11, and 3.12, plus a desktop file/dependency smoke.

## Demo story

1. Start the web app.
2. Show model status and learner memory.
3. Run Lesson Mode and show the agent chain: Memory → Lesson Generator → Adaptive Quiz → Evaluator → Progress Reporter.
4. Switch to Conversation Mode.
5. Turn video on and set visible object to `apple`.
6. Start the conversation. The tutor initiates and uses `manzana` naturally.
7. Open `data/progress.json` to show XP, history, speaking memory, turns, sessions, and last video object.

## Project shape

```text
fluent_ai/              core agents, CLI, web server, OpenAI provider, desktop bridge
desktop/electron/       standalone desktop shell
scripts/smoke_demo.py   offline acceptance smoke
tests/                  unittest suite for core, bridge, and web endpoints
data/progress.json      demo learner memory
```

## Roadmap

- Add spaced repetition scheduling.
- Add richer lesson packs for Hindi and French.
- Add stable browser-based voice regression tests with mocked Realtime events.
- Add camera-frame fixtures for vision-context tests.
