# FluentAI architecture and memory decisions

## Runtime

| Component | Responsibility |
| --- | --- |
| `fluent_ai/app.py` | CLI lesson and conversation orchestration |
| `fluent_ai/agent.py`, `conversation.py` | Topic selection, quizzes, scoring, review scheduling, and conversation progress |
| `fluent_ai/openai_provider.py` | OpenAI lesson generation, grading, tutor responses, Realtime, vision, and phrase audio |
| `fluent_ai/desktop_bridge.py` | Shared commands for interactive sessions, onboarding, memory controls, and checkpoints |
| `fluent_ai/web.py` | Local HTTP server exposing the bridge and shared renderer |
| `desktop/electron/` | Electron main/preload processes and shared browser/desktop renderer |
| `fluent_ai/state.py` | Versioned local JSON state, migrations, transactions, and reset boundaries |

Electron invokes a Python bridge process per command in development and a bundled bridge executable when packaged. The web UI uses HTTP bridge endpoints. The CLI uses the same core lesson, conversation, provider, and state modules. The obsolete Tk launcher has been retired.

## State schema v2

`data/progress.json` is the development default. Packaged desktop storage is described in [packaging](PACKAGING_DESIGN.md). The top-level structure is:

```text
schema_version: 2
memory_generation, storage_revision, completed_sessions
learner, active_language, preferences, privacy
languages[language]:
  profile, skills, topic_mastery, weak_topics, recent_topics
  review_queue, mistake_memory, conversation_memory
  history, daily_summary, updated_at
events, event_counter, updated_at
```

Per-language blocks prevent one language's progress from overwriting another. Skill/topic records retain evidence and confidence alongside scores. Mistake records retain corrected forms and scheduling information. V1 migration preserves legacy profile, scores, review queue, history, and conversation memory; normalization is idempotent and removes obsolete compatibility mirrors.

Histories retain the latest 300 events per language and 1,000 globally. A persistent event counter keeps event IDs unique after truncation. This bounded history is an audit aid, not a complete event-sourced database.

## Adaptive loop

Lesson selection prioritizes due review, due mistake memory, weak topics, then rotation. The lesson carries a selection reason. Misses update mistake memory and review dates; lesson outcomes supply a next-conversation goal. Conversation corrections map back to teachable topics and become immediately due practice. Successful mistake practice reschedules the topic to avoid a perpetual due loop.

OpenAI can grade free answers and conversation turns; malformed grading output falls back to local scoring. This grading fallback does not provide an offline user-facing tutor: real generation still requires OpenAI.

## Durability

State updates use cross-process locks, short reload/apply transactions, and atomic file replacement. Revisions reject stale snapshots. Memory generations invalidate sessions after delete-all. Lesson submission and voice completion carry stable session IDs so retries reuse committed results rather than award progress twice.

Lesson and call checkpoints live beside progress under `sessions/`. The renderer captures a call's language and uses a shared retryable finalizer for navigation, language changes, and window close. Failed saves remain available for retry. Corrupt progress is backed up before recovery; [delete-all](ONBOARDING_HOME_DESIGN.md) also clears managed recovery artifacts.

## Verification

Run the README's Python suite, mocked smoke, and `npm run check`. State migration, language isolation, concurrent writes, stale sessions, memory deletion, and renderer finalization have regression coverage in `tests/`. Use temporary state paths for any manual experiment; do not overwrite the checked-in demo profile.

See [limitations and remaining work](FLUENTAI_LIMITLESS_IDEAL.md).
