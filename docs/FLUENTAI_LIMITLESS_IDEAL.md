# FluentAI product direction and limitations

FluentAI connects adaptive lessons and tutor conversations through inspectable local learner memory. It is a language-learning demo, with OpenAI required for real lessons, conversations, voice, vision, and phrase audio. Mocked providers support repeatable tests.

## Current experience

- Onboarding records goals, preferences, and a self-reported level; optional placement seeds the first practice plan.
- Home recommends practice from review due dates, mistakes, weak topics, and conversation goals.
- Lessons explain their selection, generate quizzes, grade answers, and update XP, skill evidence, review scheduling, and conversation goals.
- Text and Realtime conversations use the selected language and feed corrections back into lessons. Voice supports English help, adaptive pauses, and optional camera context.
- Desktop and browser share a renderer and Python bridge. Memory inspection, export, reset, and session recovery are implemented.

## Product decisions

Memory should explain why the tutor chose an activity. Lesson and conversation progress must reinforce each other. Keep generated teaching content separate from deterministic progress accounting, and make model failures visible. Use camera context only when enabled; express uncertainty rather than inventing objects.

## Known limitations

- CEFR labels and skill scores are app estimates, not validated proficiency assessments. Pronunciation practice notes and phrase playback are not a phonetic scoring system.
- Curriculum depth is uneven across levels and languages; advanced topic availability does not establish full course coverage.
- Local learner storage does not mean offline inference. Relevant prompts, learner text, voice audio, and enabled camera frames go to OpenAI. See [privacy boundaries](ONBOARDING_HOME_DESIGN.md).
- Automated tests use mocked providers and simulated renderer events. They do not establish microphone/camera permission behavior, natural live turn-taking, or successful launch on a clean macOS account.
- The packaged app uses local/ad-hoc signing and is not a notarized public release. See [packaging](PACKAGING_DESIGN.md).

## Remaining roadmap

1. Add browser-level voice regressions with mocked Realtime events, including interruption, reconnect, and finalization.
2. Add camera-frame fixtures and complete physical camera/window-lifecycle acceptance.
3. Deepen and review Hindi/French lessons and advanced content, preserving native script, romanization, and answer-key quality.
4. Complete clean-account packaged-app acceptance; add Developer ID signing and notarization before public distribution.

Spaced repetition, state-v2 migration, home/privacy controls, and durable session completion are implemented; they are not pending roadmap items.

See [architecture and memory decisions](GAP_AND_DESIGN.md), [curriculum](CURRICULUM_DESIGN.md), and [historical evidence](../notes.md).
