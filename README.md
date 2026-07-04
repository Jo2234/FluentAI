# FluentAI

FluentAI is an OpenAI-powered agentic language-learning demo. It feels like a compact AI tutor studio: Lesson Mode generates adaptive lessons/quizzes, Conversation Mode starts a FaceTime-style tutor session, and both modes update the same persistent learner memory.

FluentAI now requires `OPENAI_API_KEY` for real lesson and conversation runs. Tests use mocked OpenAI responses so CI never needs secrets.

## What works now

- **Lesson Mode**: personalized mini lesson, vocabulary, grammar, examples, adaptive quiz, grading, XP, weak-topic updates.
- **Conversation Mode**: tutor initiates, adapts to A1-C2 ability, supports text fallback, OpenAI Realtime voice path, and video context.
- **Video-object demo**: `--video on --video-object apple` reliably grounds beginner Spanish conversation around `manzana`.
- **Persistent memory**: `data/progress.json` tracks level, skills, topic mastery, spaced-review queue, streak, history, and speaking memory.
- **Browser UI**: standard-library local web server; no heavy framework required.
- **Desktop UI**: Electron shell with the same Python agent engine.
- **Mocked tests/smoke**: CI validates state updates and UI endpoints without using secrets.

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

## OpenAI setup

Create a private `.env` file before running the app:

```bash
cp .env.example .env
# then edit .env and set OPENAI_API_KEY
```

Required values:

```bash
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5.5
OPENAI_REASONING_EFFORT=low
OPENAI_VERBOSITY=low
```

If the key or SDK call is unavailable, FluentAI stops with a clear setup/error message instead of falling back to deterministic local tutor behavior. It never prints the API key.

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

## Conversation behavior

Voice calls are tuned for natural, dynamic turn-taking:

- the tutor uses dynamic pause windows based on learner level and speaking confidence
- beginners / low-confidence learners get a little more time; confident advanced learners get snappier pacing
- brief thinking pauses, filler words, and self-corrections should not trigger interruptions
- if you are silent for several seconds, it gives a short check-in instead of a monologue
- if you say “what was that?”, “no entiendo”, “what does that mean?”, or fall back to English, it explains briefly in English, gives one simple target-language phrase, then nudges you back into practice

Optional `.env` tuning knobs. Leave them unset for dynamic defaults:

```bash
OPENAI_REALTIME_SILENCE_MS=2500
OPENAI_REALTIME_IDLE_PROMPT_MS=6500
OPENAI_REALTIME_VAD_THRESHOLD=0.65
```

Video context uses `OPENAI_VISION_MODEL`, defaulting to `gpt-4.1-mini` for faster camera-frame descriptions. The app refreshes the camera context roughly every 3.5 seconds while video is on, shows the model/confidence in the UI, and tells the tutor not to guess when the object is unclear.

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
npm run check
```

With `OPENAI_API_KEY` set in `.env`, also run:

```bash
python -m fluent_ai.app --once --mode auto --state-path /tmp/fluentai-lesson.json
python -m fluent_ai.app --product-mode conversation --turns 2 --video on --video-object apple --mode auto --state-path /tmp/fluentai-conversation.json
```

CI runs these Python checks on 3.10, 3.11, and 3.12, plus a desktop file/dependency smoke.

## Demo story

1. Start the web app.
2. Show model status and learner memory.
3. Run Lesson Mode and show the agent chain: Memory → Lesson Generator → Adaptive Quiz → Evaluator → Progress Reporter.
4. Switch to Conversation Mode.
5. Turn video on and set visible object to `apple`.
6. Start the conversation. The tutor initiates and uses `manzana` naturally.
7. Open `data/progress.json` to show XP, history, spaced-review scheduling, speaking memory, turns, sessions, and last video object.

## Project shape

```text
fluent_ai/              core agents, CLI, web server, OpenAI provider, desktop bridge
desktop/electron/       standalone desktop shell
scripts/smoke_demo.py   mocked acceptance smoke
tests/                  unittest suite for core, bridge, and web endpoints
data/progress.json      demo learner memory
```

## Roadmap

- Add spaced repetition scheduling.
- Add richer lesson packs for Hindi and French.
- Add stable browser-based voice regression tests with mocked Realtime events.
- Add camera-frame fixtures for vision-context tests.
