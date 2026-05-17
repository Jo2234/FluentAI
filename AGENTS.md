# FluentAI Agent Instructions

## Product Goal
Build an agentic language learning app with two first-class modes.

Lesson Mode:
- Knows the learner's current level from local files.
- Generates personalized lessons and quizzes on its own.
- Evaluates answers, updates progress, and adapts future lessons.
- Can run visibly for a 5-10 minute judging demo.

Conversation Mode:
- Feels like a FaceTime-style language tutor session, with video optional.
- The AI initiates the conversation and steers it according to the learner's judged ability.
- Beginner learners get simple target-language conversation about names, weather, food, likes, and visible objects.
- Advanced learners get richer topics such as politics, environment, culture, work, and debate.
- When video is on, camera/image context can guide the conversation, such as identifying an apple in Spanish.
- Conversation results update `data/progress.json` so future lessons and conversations adapt.

## Goal Mode Orchestration
- Treat Goal mode as a persistent completion contract: state the outcome, evidence of success, constraints, and stopping conditions before long-running work.
- Follow the Codex Goals pattern from https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex: keep the objective visible, verify progress from artifacts or tests, and choose the next useful action from evidence.
- Keep `plan.md` as the current plan and `notes.md` as the compact memory of actual progress, decisions, user preferences, and important facts to preserve across turns.
- The main goal orchestrator must write actual progress and important things to remember in `notes.md` whenever meaningful work is completed or priorities change.
- If another user or agent modifies `plan.md` midway, stay calm, reread it, adapt Goal mode to the updated plan, and continue from the newest valid intent instead of fighting the change.
- Keep all project documents concise. Prefer short bullets with concrete facts over long narrative.

## Engineering Defaults
- Prefer small, runnable slices over speculative architecture.
- Store learner state locally under `data/`.
- Keep generated lesson, quiz, evaluation, and adaptation logic easy to inspect for demos.
- Keep Conversation Mode runnable without external credentials using deterministic fallbacks; add OpenAI Realtime or vision APIs as an upgrade path, not as a hard dependency for the MVP.
- Make agent decisions visible in console logs so judges can see memory loading, topic choice, video-context handling, feedback, and adaptation.
- Add tests or smoke checks for behavior that changes learner state.
