# FluentAI Gap Analysis and Implementation Design

Scope: compare `docs/FLUENTAI_LIMITLESS_IDEAL.md` with the current implementation and design the next two workstreams: Memory Model v2 (WS1) and Core Adaptive Loop (WS2). Current-code citations use `path:function` or `path:function-name`.

## Part 1: Gap Inventory

| Capability | Status | Current behavior and grounding |
|---|---:|---|
| Memory model depth | PARTIAL | Flat single learner dict with scores, topics, review queue, history, and conversation memory in `fluent_ai/state.py:default_state`, migrated by `fluent_ai/state.py:migrate_state`. No skill evidence, mistake objects, privacy metadata, or event-sourced raw signals. |
| Per-language state | PARTIAL | Language switch mutates `learner.target_language` in `fluent_ai/desktop_bridge.py:_load`; lessons use generic content for non-Spanish in `fluent_ai/agent.py:_generic_lesson_bank`; no separate memory per language. |
| Event history | PARTIAL | `state["history"]` stores last 25 lesson/conversation summary dicts in `fluent_ai/agent.py:update_progress`, `fluent_ai/conversation.py:update_conversation_progress`, and `fluent_ai/desktop_bridge.py:apply_conversation_turn_progress`; not typed, not auditable event records. |
| Mistake memory | PARTIAL | Conversation corrections are appended as strings to `conversation_memory.missed_phrases` in `fluent_ai/conversation.py:update_conversation_progress` and `fluent_ai/desktop_bridge.py:apply_conversation_turn_progress`; quiz misses only reorder `weak_topics` in `fluent_ai/agent.py:update_progress`. |
| Spaced review | PARTIAL | Topic-level review scheduling exists in `fluent_ai/agent.py:update_review_schedule` and due-topic selection in `fluent_ai/agent.py:due_review_items` / `next_due_review_topic`; no item-level words, phrases, mistakes, modality, or confidence adjustment. |
| Lesson reason | MISSING | `fluent_ai/agent.py:choose_topic` selects a topic but returns no reason; `fluent_ai/agent.py:generate_lesson`, `fluent_ai/desktop_bridge.py:lesson_start`, and `desktop/electron/renderer.html:lessonHero` do not surface why the lesson was chosen. |
| Adaptive quiz and error categorization | PARTIAL | Mixed quiz types and adaptive count exist in `fluent_ai/agent.py:generate_quiz`; correctness and feedback exist in `fluent_ai/agent.py:evaluate_answers`, `is_correct`, and `feedback_for`; no error category, severity, corrected form, or OpenAI-backed grading. |
| Lesson-to-conversation goal feed | PARTIAL | `conversation_memory.next_speaking_goal` changes after conversation in `fluent_ai/conversation.py:next_speaking_goal` and bridge turn updates, but lesson outcomes do not explicitly set the next conversation goal in `fluent_ai/agent.py:update_progress`. |
| Conversation-to-lesson mistake feed | PARTIAL | Conversation corrections affect `missed_phrases`, `skills`, `topic_mastery`, and `weak_topics` in `fluent_ai/conversation.py:update_conversation_progress` and `fluent_ai/desktop_bridge.py:apply_conversation_turn_progress`; `fluent_ai/agent.py:choose_topic` does not read conversation mistakes directly. |
| Post-call summary | MISSING | Text fallback returns turn feedback in `fluent_ai/desktop_bridge.py:conversation_reply` and renderer chat bubbles in `desktop/electron/renderer.html:sendConversationReply`; no end-of-call summary object or rendering. Voice calls end client-side in `desktop/electron/renderer.html:endRealtimeCall` without persisting call outcomes. |
| Onboarding and placement | MISSING | State defaults to "Demo Learner" A1 in `fluent_ai/state.py:default_state`; renderer starts status and auto lesson in `desktop/electron/renderer.html:refreshStatus` / `ensureLessonStarted`; no placement flow. |
| Home workspace | PARTIAL | Electron renderer has profile, mode buttons, lesson, call stage, review counts, and agent logs in `desktop/electron/renderer.html:renderProfile`, `renderLesson`, and `renderChat`; no true home dashboard, memory inspector, or recommended action model. |
| Memory inspector | MISSING | `/api/progress` returns raw state in `fluent_ai/web.py:FluentAIHandler.do_GET`, but no UI inspector, filtered memory view, or export affordance. |
| Privacy export/delete/reset | MISSING | No privacy fields in `fluent_ai/state.py:default_state`; no export/delete/reset commands in `fluent_ai/desktop_bridge.py:COMMANDS`, `fluent_ai/web.py:FluentAIHandler`, or `desktop/electron/preload.js`. |
| Reliability handling | PARTIAL | API-key errors, bridge process errors, media permission errors, model failures, and JSON bounds exist in `fluent_ai/desktop_bridge.py:_openai_required`, `desktop/electron/main.js:runBridge`, `desktop/electron/main.js:media:request_access`, `desktop/electron/renderer.html:mediaErrorMessage`, and `fluent_ai/web.py:_read_json`; invalid/corrupt progress files and interrupted sessions are not recovered. |
| Mac app packaging | PARTIAL | Electron `.app` packaging exists in `scripts/build_mac_app.sh`; Electron shell in `desktop/electron/main.js`; Python Tk fallback in `macos/desktop_app.py:FluentAIDesktop`. No signing/notarization/update pipeline. |
| Pronunciation feedback | MISSING | Realtime voice session and turn detection exist in `fluent_ai/openai_provider.py:realtime_client_secret` and `_realtime_turn_detection`; no pronunciation scoring, replay, phoneme/stress feedback, or persisted pronunciation memory. |

## Part 2: Memory Model v2 (WS1)

### Proposed `data/progress.json` Shape

Use plain dicts, JSON-serializable values, and `fluent_ai/state.py:migrate_state`. Add helper functions instead of new dependencies.

```json
{
  "schema_version": 2,
  "learner": {
    "id": "local-demo-learner",
    "display_name": "Demo Learner",
    "native_language": null,
    "motivation": "",
    "active_goals": ["Hold a simple 5-minute conversation", "Build useful daily vocabulary", "Improve conjugation accuracy"],
    "preferred_session_length_minutes": 10,
    "preferred_correction_style": "gentle",
    "preferred_tutor_tone": "encouraging and specific",
    "accessibility": {"transliteration": false, "larger_text": false, "reduced_motion": false},
    "created_at": "2026-07-08T00:00:00+00:00"
  },
  "active_language": "Spanish",
  "languages": {
    "Spanish": {
      "profile": {
        "target_language": "Spanish",
        "current_level": "A1",
        "level_confidence": 0.45,
        "xp": 0,
        "streak_days": 1,
        "learning_goals": ["Hold a simple 5-minute conversation", "Build useful daily vocabulary", "Improve conjugation accuracy"],
        "last_session_at": null
      },
      "skills": {
        "vocabulary": {"score": 0.34, "trend": "flat", "last_practiced": null, "evidence": []},
        "grammar": {"score": 0.28, "trend": "flat", "last_practiced": null, "evidence": []},
        "conjugations": {"score": 0.26, "trend": "flat", "last_practiced": null, "evidence": []},
        "listening": {"score": 0.30, "trend": "flat", "last_practiced": null, "evidence": []},
        "speaking": {"score": 0.30, "trend": "flat", "last_practiced": null, "evidence": []},
        "pronunciation": {"score": 0.30, "trend": "flat", "last_practiced": null, "evidence": []},
        "reading": {"score": 0.32, "trend": "flat", "last_practiced": null, "evidence": []},
        "writing": {"score": 0.30, "trend": "flat", "last_practiced": null, "evidence": []},
        "translation": {"score": 0.30, "trend": "flat", "last_practiced": null, "evidence": []},
        "fluency": {"score": 0.30, "trend": "flat", "last_practiced": null, "evidence": []}
      },
      "topic_mastery": {
        "cafe orders": {"recognition": 0.34, "recall": 0.30, "spoken_use": 0.30, "written_use": 0.30, "listening": 0.30, "review_interval_days": 1, "last_success": null, "last_failure": null, "evidence": []},
        "introductions": {"recognition": 0.36, "recall": 0.30, "spoken_use": 0.30, "written_use": 0.30, "listening": 0.30, "review_interval_days": 1, "last_success": null, "last_failure": null, "evidence": []}
      },
      "weak_topics": ["past tense", "conjugations", "vocabulary"],
      "recent_topics": [],
      "review_queue": {
        "review_topic_past_tense": {
          "id": "review_topic_past_tense",
          "item_type": "topic",
          "target": "past tense",
          "skill": "conjugations",
          "topic": "past tense",
          "source": "lesson",
          "due_at": "2026-07-09T00:00:00+00:00",
          "interval_days": 1,
          "missed_count": 0,
          "success_count": 0,
          "last_score": "0/0",
          "created_at": "2026-07-08T00:00:00+00:00",
          "updated_at": "2026-07-08T00:00:00+00:00"
        }
      },
      "conversation_memory": {
        "sessions_completed": 0,
        "total_turns": 0,
        "fluency_score": 0.30,
        "speaking_confidence": 0.30,
        "recent_topics": [],
        "missed_phrases": [],
        "last_video_context": {"summary": null, "primary_object": null, "confidence": null, "used_at": null},
        "next_speaking_goal": "Answer simple questions in full Spanish sentences.",
        "next_conversation_goal": null,
        "post_call_summaries": []
      },
      "mistake_memory": {
        "mistake_yo_hablar_hablo": {
          "id": "mistake_yo_hablar_hablo",
          "incorrect_form": "yo hablar",
          "corrected_form": "yo hablo",
          "context": "Learner used infinitive for first-person present tense.",
          "skill": "conjugations",
          "topic": "daily routines",
          "error_category": "wrong_conjugation",
          "first_seen": "2026-07-08T00:00:00+00:00",
          "last_seen": "2026-07-08T00:00:00+00:00",
          "frequency": 1,
          "severity": "medium",
          "blocked_meaning": false,
          "speech_recurrence": false,
          "next_review": "2026-07-09T00:00:00+00:00"
        }
      },
      "history": [],
      "daily_summary": {"last_sent_at": null, "lessons_completed": 0},
      "updated_at": "2026-07-08T00:00:00+00:00"
    }
  },
  "preferences": {"lesson_minutes": 10, "daily_quiz_questions": 6, "tone": "encouraging and specific", "voice": "alloy", "video_default": "off"},
  "privacy": {
    "local_only": true,
    "store_raw_audio": false,
    "store_raw_video": false,
    "store_camera_summaries": true,
    "allow_export": true,
    "allow_delete": true,
    "allow_language_reset": true,
    "last_exported_at": null
  },
  "events": [],
  "updated_at": "2026-07-08T00:00:00+00:00"
}
```

### Event History Design

Event record:

```json
{
  "id": "evt_20260708_000001",
  "type": "quiz_answered",
  "occurred_at": "2026-07-08T00:00:00+00:00",
  "language": "Spanish",
  "session_id": "lesson_20260708_000001",
  "source": "lesson_mode",
  "summary": "Answered fill_blank for conjugations on daily routines.",
  "payload": {
    "topic": "daily routines",
    "skill": "conjugations",
    "question_type": "fill_blank",
    "prompt": "Fill in the blank: Yo ___ espanol.",
    "answer": "hablar"
  }
}
```

Required event types: `lesson_started`, `lesson_completed`, `quiz_answered`, `answer_evaluated`, `review_scheduled`, `conversation_started`, `learner_replied`, `video_context_used`, `progress_updated`.

Policy:
- Append via `fluent_ai/state.py:add_event(state, event)`.
- Store language-scoped events in `languages[active_language].history` and top-level audit events in `events`.
- Cap `languages[language].history` to last 300 events per language.
- Cap top-level `events` to last 1000 events.
- Keep `payload` concise: no raw audio, raw video, full image data URLs, API keys, or full prompts. Store summaries and learning signals.
- Rotation happens inside `save_state` or `add_event`, never at arbitrary call sites.

### Mistake Memory Record

Fields:
- `id`: stable deterministic slug from normalized `incorrect_form`, `corrected_form`, `skill`, and `topic`.
- `incorrect_form`: learner text or shortest incorrect phrase.
- `corrected_form`: model/correct phrase.
- `context`: one sentence explaining where it happened.
- `skill`: one of vocabulary, grammar, conjugations, listening, speaking, pronunciation, reading, writing, translation, fluency.
- `topic`: lesson or conversation topic.
- `error_category`: vocabulary_missing, wrong_conjugation, wrong_tense, word_order, comprehension, too_short, unnatural, pronunciation_issue, other.
- `first_seen`, `last_seen`: ISO UTC strings.
- `frequency`: incremented on repeats.
- `severity`: low, medium, high.
- `blocked_meaning`: boolean.
- `speech_recurrence`: boolean.
- `next_review`: ISO UTC string or null.

### Skill Score Records

Each skill becomes a record:
- `score`: bounded float 0.05 to 0.99.
- `trend`: `up`, `down`, or `flat`, based on latest score delta.
- `last_practiced`: ISO UTC string.
- `evidence`: bounded list of last 8 evidence records: `{ "event_id": "...", "mode": "lesson|conversation", "topic": "...", "delta": 0.045, "note": "..." }`.

### Exact v1-to-v2 Migration Plan

Migration is idempotent: if `schema_version == 2` and `languages` exists, normalize missing defaults only; do not remap again. For v1, create v2 and preserve every current value.

| Current v1 field | New v2 mapping |
|---|---|
| `learner.name` | `learner.display_name` |
| `learner.target_language` | `active_language` and `languages[language].profile.target_language` |
| `learner.current_level` | `languages[language].profile.current_level` |
| `learner.level` | fallback for `languages[language].profile.current_level`; do not keep duplicate except in compatibility helper output |
| `learner.xp` | `languages[language].profile.xp` |
| `learner.streak_days` | `languages[language].profile.streak_days` |
| `learner.learning_goals` | `learner.active_goals` and `languages[language].profile.learning_goals` |
| `skills.{skill}: float` | `languages[language].skills.{skill}.score`; add `trend`, `last_practiced`, bounded `evidence` |
| `skills.conjugation` | normalize to `skills.conjugations` as current `fluent_ai/state.py:migrate_state` already does |
| `topic_mastery.{topic}: float` | `languages[language].topic_mastery.{topic}.recognition`; initialize recall/spoken/written/listening from same score unless evidence says otherwise |
| `weak_topics` | `languages[language].weak_topics` |
| `preferences.lesson_minutes` | top-level `preferences.lesson_minutes` and `learner.preferred_session_length_minutes` |
| `preferences.daily_quiz_questions` | top-level `preferences.daily_quiz_questions` |
| `preferences.tone` | top-level `preferences.tone` and `learner.preferred_tutor_tone` |
| `recent_topics` | `languages[language].recent_topics` |
| `review_queue.{topic}` | `languages[language].review_queue.review_topic_{slug(topic)}`; preserve all nested keys in the new record plus `id`, `item_type`, `source` |
| `history[]` lesson dicts | convert to `languages[language].history[]` typed `lesson_completed` or `progress_updated` events with original dict under `payload.legacy` |
| `history[]` where `mode == conversation` or `conversation_turn` | convert to typed `conversation_started`, `learner_replied`, or `progress_updated` events with original dict under `payload.legacy` |
| `daily_summary` | `languages[language].daily_summary` |
| `conversation_memory.sessions_completed` | `languages[language].conversation_memory.sessions_completed` |
| `conversation_memory.total_turns` | `languages[language].conversation_memory.total_turns` |
| `conversation_memory.fluency_score` | `languages[language].conversation_memory.fluency_score` and `languages[language].skills.fluency.score` if no stronger skill score exists |
| `conversation_memory.speaking_confidence` | `languages[language].conversation_memory.speaking_confidence` |
| `conversation_memory.recent_topics` | `languages[language].conversation_memory.recent_topics` |
| `conversation_memory.missed_phrases[]` | keep as `conversation_memory.missed_phrases[]`; also create best-effort `mistake_memory` records with `incorrect_form: ""`, `corrected_form: phrase`, `source: legacy_missed_phrase` |
| `conversation_memory.last_video_object` | `languages[language].conversation_memory.last_video_context.primary_object` |
| `conversation_memory.next_speaking_goal` | `languages[language].conversation_memory.next_speaking_goal` |
| `conversation_memory.last_session_at` | `languages[language].profile.last_session_at` and `conversation_memory.last_session_at` if kept for compatibility |
| `updated_at` | top-level `updated_at` and `languages[language].updated_at` |

Lossless rule: preserve unrecognized v1 keys under `languages[language]["legacy_extra"]` and preserve original history dicts inside event payloads. Do not delete data during migration.

### State Access Helpers

Add to `fluent_ai/state.py`:
- `active_language(state) -> str`
- `language_state(state, language=None) -> dict`
- `profile_state(state, language=None) -> dict`
- `skill_scores(state, language=None) -> dict[str, float]`
- `set_skill_score(state, skill, score, language=None, evidence=None) -> None`
- `topic_scores(state, language=None) -> dict[str, float]`
- `set_topic_score(state, topic, score, language=None, modality="recognition", evidence=None) -> None`
- `conversation_memory(state, language=None) -> dict`
- `review_queue(state, language=None) -> dict`
- `append_history_event(state, event, language=None) -> None`
- `record_mistake(state, mistake, language=None) -> dict`

During WS1, keep temporary compatibility helpers that can read either v1 or v2. By the end of WS1, `load_state` should always return v2.

### Moving Call Sites

| Current site | Reads/writes moving fields | Change |
|---|---|---|
| `fluent_ai/agent.py:snapshot_progress` | `skills`, `topic_mastery`, `learner.xp`, level | Use `skill_scores`, `topic_scores`, `profile_state`, `current_level`. |
| `fluent_ai/agent.py:current_level` | `learner.current_level`, `learner.level` | Read `profile_state(state).current_level`; keep v1 fallback during migration. |
| `fluent_ai/agent.py:weakest_skill` | `state["skills"]` | Use `skill_scores(state)`. |
| `fluent_ai/agent.py:performance_band` | `history[-3:]` | Use typed `languages[language].history` lesson_completed / answer_evaluated events. |
| `fluent_ai/agent.py:due_review_items` | `review_queue` | Use `review_queue(state)`; support new item ids and old topic keys during migration. |
| `fluent_ai/agent.py:choose_topic` | `weak_topics`, `recent_topics`, due review | Use `language_state`; also consider mistake memory due items in WS2. |
| `fluent_ai/agent.py:generate_lesson` | `learner.target_language`, `learner.learning_goals`, `preferences.lesson_minutes` | Use `active_language`, `profile_state.learning_goals`, top-level preferences; add `reason`. |
| `fluent_ai/agent.py:answer_quiz` | average of `skills` | Use `skill_scores`. |
| `fluent_ai/agent.py:update_progress` | writes skills, topic_mastery, learner xp/level, weak_topics, recent_topics, daily_summary, history | Use setter helpers, per-language profile, typed events, and bounded evidence. |
| `fluent_ai/agent.py:update_review_schedule` | writes `review_queue` | Write per-language review records and `review_scheduled` event. |
| `fluent_ai/agent.py:recommendation` | `weak_topics`, `weakest_skill` | Use `language_state.weak_topics`. |
| `fluent_ai/agent.py:progress_report` | skills, `learner.streak_days`, `daily_summary` | Use per-language profile and daily summary. |
| `fluent_ai/conversation.py:choose_conversation_topic` | target language and `conversation_memory.recent_topics` | Use `active_language`, `conversation_memory`. |
| `fluent_ai/conversation.py:conversation_topics_for` | `learner.target_language` | Use `active_language`. |
| `fluent_ai/conversation.py:visual_reply_options` | target language | Use `active_language`. |
| `fluent_ai/conversation.py:evaluate_reply` | level | Uses migrated `current_level`. |
| `fluent_ai/conversation.py:build_follow_up` | level, target language | Use `current_level` and `active_language`. |
| `fluent_ai/conversation.py:update_conversation_progress` | conversation memory, skills, topic_mastery, weak_topics, history | Use helpers, record mistakes, append typed events. |
| `fluent_ai/conversation.py:next_speaking_goal` | level | Uses migrated `current_level`; may read `next_conversation_goal`. |
| `fluent_ai/desktop_bridge.py:lesson_start` | level, weak_topics, lesson payload | Use helper-backed functions; return `lesson.reason`. |
| `fluent_ai/desktop_bridge.py:lesson_submit` | snapshot/update/save/profile | Helper-backed update plus event writes. |
| `fluent_ai/desktop_bridge.py:conversation_start` | topic selection and session | Helper-backed topic selection; append `conversation_started`. |
| `fluent_ai/desktop_bridge.py:conversation_reply` | turn progress | Use shared conversation progress helper, not bridge-only duplicate logic. |
| `fluent_ai/desktop_bridge.py:apply_conversation_turn_progress` | duplicate writes to conversation memory, skills, topic_mastery, history | Replace with shared `fluent_ai/conversation.py:apply_conversation_turn` or move helper to state/agent module. |
| `fluent_ai/desktop_bridge.py:profile_for` | learner/profile/review/conversation fields | Build stable renderer profile from v2. Keep existing keys; add optional `lesson_reason`, `next_conversation_goal`, `memory_counts`. |
| `fluent_ai/desktop_bridge.py:_load` | mutates `learner.target_language` | Set `active_language`; create `languages[language]` via migration defaults without overwriting other languages. |
| `fluent_ai/web.py:FluentAIHandler.do_GET` | status reads `learner.current_level`, weak topics; `/api/progress` returns raw state | Use `profile_for` for status; optionally return v2 raw progress unchanged for inspector/export. |
| `fluent_ai/web.py:run_lesson_cycle` | lesson update path | Helper-backed update and lesson reason output. |
| `fluent_ai/web.py:run_conversation_cycle` | next speaking goal | Read via `conversation_memory(state)`. |
| `fluent_ai/app.py:run_loop` | weak topics, goals, streak, update progress | Use helpers and print lesson reason. |
| `fluent_ai/app.py:run_conversation_loop` | weak topics, next speaking goal | Use helpers. |
| `desktop/electron/renderer.html:renderProfile` | profile fields from bridge | No raw state read; keep keys stable and render added memory counts/reasons when present. |
| `desktop/electron/renderer.html:refreshStatus` | may persist language | Continue passing `language`; backend sets `active_language`, not `learner.target_language`. |
| `desktop/electron/renderer.html:startLesson` / `lessonHero` | lesson payload | Render `lesson.reason`. |
| `desktop/electron/renderer.html:submitQuiz` / `renderQuizResults` | result payload | Render `error_category` and corrected form if present. |
| `desktop/electron/renderer.html:startConversation` / `sendConversationReply` | session, turn, profile | Render post-call summary when bridge returns it. |
| `desktop/electron/renderer.html:startRealtimeCall` / `endRealtimeCall` | voice call has no state update path | WS2 should add a backend summary/update endpoint for voice transcripts or explicitly mark voice persistence as not implemented. |

### Backward Compatibility Strategy

- `load_state` always calls `migrate_state` and returns v2.
- Helpers accept old v1 dicts in tests until fixtures are updated.
- Keep `profile_for` response keys stable: `name`, `language`, `level`, `xp`, `streak_days`, `weak_topics`, `learning_goals`, `fluency_score`, `speaking_confidence`, `next_speaking_goal`, review counts.
- Update tests coherently by changing assertions to v2 paths or helper output:
  - `tests/test_agent.py`: default state shape, progress update, review queue, conversation memory.
  - `tests/test_conversation_naturalness.py`: confidence under v2 conversation memory.
  - `tests/test_web.py`: status and smoke endpoints should not assume flat state.
  - `tests/test_renderer_ui.py`: add string checks for lesson reason and error category rendering.
  - `tests/test_vision_context.py`: unchanged except active-language helper in prompts if needed.
- No new pip dependencies. Use plain dict helpers and small dataclasses only for local result records.

## Part 3: Core Adaptive Loop (WS2)

### Lesson Reason

Generate in `fluent_ai/agent.py:generate_lesson` after `choose_topic` by adding `lesson_reason_for(state, topic, source_signal)`.

Reason priority:
1. Due review: "This is due for review because the last score was X and the interval is Y day(s)."
2. Mistake memory: "You missed `incorrect_form` -> `corrected_form` in conversation, so this lesson practices `topic`."
3. Weak topic: "Your weakest current topic is `topic` based on recent lesson and conversation evidence."
4. Rotation: "This avoids repeating recent topics while staying at level `current_level`."

Surface path:
- Add `lesson["reason"]`.
- Include `reason` in `fluent_ai/desktop_bridge.py:lesson_start` response and logs.
- Include `reason` in `fluent_ai/web.py:run_lesson_cycle` and `fluent_ai/app.py:print_lesson`.
- Render it in `desktop/electron/renderer.html:lessonHero` under the title.

### Quiz Evaluation Error Categories

Add fields to `QuizResult`: `error_category: str | None`, `corrected_form: str | None`, `severity: str`, `confidence: float`.

Required categories:
- `vocabulary_missing`
- `wrong_conjugation`
- `wrong_tense`
- `word_order`
- `comprehension`
- `too_short`
- `unnatural`

Local/mock assignment:
- Empty answer or fewer than 2 tokens for open-ended prompts: `too_short`.
- Multiple choice vocabulary miss: `vocabulary_missing`.
- Fill blank with focus skill `conjugations`: `wrong_conjugation`.
- Prompt/topic includes "past tense" and answer lacks expected past-tense marker: `wrong_tense`.
- Normalized token set overlaps expected answer but order differs materially: `word_order`.
- Open-ended answer has no expected keywords: `comprehension`.
- Correct by keyword but not exact/natural enough: `unnatural`.

OpenAI-backed grading:
- Add `OpenAIProvider.evaluate_quiz_answer(state, question, answer, lesson) -> dict`.
- Prompt returns strict JSON: `correct`, `error_category`, `feedback`, `corrected_form`, `severity`, `confidence`.
- `fluent_ai/desktop_bridge.py:lesson_submit` uses provider grading when available; tests patch provider with deterministic category outputs.
- `fluent_ai/agent.py:evaluate_answers` remains local deterministic fallback for unit tests and smoke mode.

### Lesson Outcome to Conversation Goal

In `fluent_ai/agent.py:update_progress`:
- Identify weakest missed category/topic from results.
- Write `languages[language].conversation_memory.next_conversation_goal`.
- Update `next_speaking_goal` if lesson misses are speaking-relevant.
- Add `progress_updated` event with `next_conversation_goal`.

Example:
- Missed `wrong_conjugation` on daily routines -> `next_conversation_goal = "Ask simple daily-routine questions that force first-person present tense."`
- Missed `vocabulary_missing` on cafe orders -> `next_conversation_goal = "Use cafe-order phrases in a short role-play."`

In `fluent_ai/conversation.py:choose_conversation_topic`:
- Check `next_conversation_goal` before random ladder selection.
- Prefer matching topic/scenario unless video context is active and useful.

### Conversation Mistake to Next Lesson

In `fluent_ai/conversation.py:evaluate_reply` and bridge/OpenAI grading:
- Return correction metadata, not only correction text: `incorrect_form`, `corrected_form`, `error_category`, `skill`, `topic`, `blocked_meaning`.
- `update_conversation_progress` and bridge turn updates call `record_mistake`.
- `record_mistake` increments frequency, updates `last_seen`, schedules `next_review`, and appends review queue item.
- `fluent_ai/agent.py:choose_topic` considers due mistake reviews before generic weak topics.
- `generate_lesson` includes the top relevant mistake as a lesson input and reason source.

### Post-call Summary

Summary content:
- `session_id`
- `topic`
- `turn_count`
- `average_score`
- `did_well`
- `correction_to_remember`
- `phrase_to_review`
- `next_speaking_goal`
- `confidence_change`
- `next_conversation_should_practice`

Where it renders:
- Text fallback: when `fluent_ai/desktop_bridge.py:conversation_reply` returns `done: true`, include `post_call_summary`; render via `desktop/electron/renderer.html:sendConversationReply` in the chat log and a compact summary panel.
- CLI/web: append summary in `fluent_ai/app.py:run_conversation_loop` and `fluent_ai/web.py:run_conversation_cycle`.
- Voice: add a later `conversation:end` bridge endpoint that accepts sanitized transcript snippets from realtime events, computes a summary, and writes state. Until then, voice call summaries are UI-only and should not claim persistent memory updates.

## Part 4: Sequenced Implementation Plan

### WP1: State v2 Skeleton and Migration

Files touched:
- `fluent_ai/state.py`
- `tests/test_agent.py`

Work:
- Add v2 defaults, helper accessors, migration, event append/rotation.
- Preserve v1 migration idempotently and losslessly.

Tests:
- New tests for v1-to-v2 mapping, idempotent migration, default v2 shape, and event cap.

Acceptance:
- `python -m unittest tests.test_agent -q`
- `npm run check`

### WP2: Update Core Lesson State Call Sites

Files touched:
- `fluent_ai/agent.py`
- `fluent_ai/app.py`
- `fluent_ai/web.py`
- `tests/test_agent.py`
- `tests/test_web.py`

Work:
- Replace flat state reads/writes with helpers.
- Keep public lesson/quiz behavior stable.
- Write typed lesson/quiz/review/progress events.

Tests:
- Progress updates mutate v2 skill records, topic records, review queue, daily summary, and typed history.
- Web smoke still passes.

Acceptance:
- `python -m unittest tests.test_agent tests.test_web -q`
- `npm run check`

### WP3: Update Conversation State Call Sites

Files touched:
- `fluent_ai/conversation.py`
- `fluent_ai/desktop_bridge.py`
- `fluent_ai/app.py`
- `fluent_ai/web.py`
- `tests/test_agent.py`
- `tests/test_conversation_naturalness.py`

Work:
- Use v2 helpers for active language, conversation memory, skills, topic mastery, weak topics, and history.
- Remove or delegate duplicate bridge conversation progress logic.
- Set `active_language` without overwriting other language memory.

Tests:
- Conversation updates per-language memory.
- Switching Hindi/French/Spanish preserves separate profiles.
- Realtime turn detection reads v2 confidence.

Acceptance:
- `python -m unittest tests.test_agent tests.test_conversation_naturalness -q`
- `npm run check`

### WP4: Lesson Reason and Renderer Surface

Files touched:
- `fluent_ai/agent.py`
- `fluent_ai/desktop_bridge.py`
- `fluent_ai/web.py`
- `fluent_ai/app.py`
- `desktop/electron/renderer.html`
- `tests/test_agent.py`
- `tests/test_renderer_ui.py`

Work:
- Add `lesson.reason`.
- Include reason in logs and bridge payload.
- Render reason in lesson hero.

Tests:
- Due review, mistake memory, weak topic, and rotation each produce a reason.
- Renderer contains reason rendering path.

Acceptance:
- `python -m unittest tests.test_agent tests.test_renderer_ui -q`
- `npm run check`

### WP5: Error Categories and Mistake Memory

Files touched:
- `fluent_ai/agent.py`
- `fluent_ai/openai_provider.py`
- `fluent_ai/desktop_bridge.py`
- `fluent_ai/state.py`
- `desktop/electron/renderer.html`
- `tests/test_agent.py`
- `tests/test_renderer_ui.py`

Work:
- Extend `QuizResult`.
- Add local category heuristics.
- Add optional OpenAI grading through mocked provider in bridge submit path.
- Record mistakes and review items from lesson misses.
- Render category/corrected form in quiz feedback.

Tests:
- Each required category has a deterministic local test.
- Mocked OpenAI grader category overrides local category.
- Mistake memory increments on repeated miss.

Acceptance:
- `python -m unittest tests.test_agent tests.test_renderer_ui -q`
- `npm run check`

### WP6: Lesson and Conversation Feedback Loop

Files touched:
- `fluent_ai/agent.py`
- `fluent_ai/conversation.py`
- `fluent_ai/desktop_bridge.py`
- `tests/test_agent.py`

Work:
- Lesson outcomes set `next_conversation_goal`.
- Conversation topic selection consumes that goal.
- Conversation corrections write mistake memory and influence next lesson choice.

Tests:
- Missed conjugation lesson leads to daily-routine/present-tense conversation goal.
- Conversation correction creates mistake record and next lesson reason references it.

Acceptance:
- `python -m unittest tests.test_agent -q`
- `npm run check`

### WP7: Post-call Summary

Files touched:
- `fluent_ai/conversation.py`
- `fluent_ai/desktop_bridge.py`
- `fluent_ai/app.py`
- `fluent_ai/web.py`
- `desktop/electron/renderer.html`
- `tests/test_agent.py`
- `tests/test_renderer_ui.py`
- `tests/test_web.py`

Work:
- Generate summary after text/CLI/web conversation completion.
- Persist summary in `conversation_memory.post_call_summaries`.
- Render summary when text fallback reaches turn target.
- Document voice persistence gap in logs until `conversation:end` exists.

Tests:
- Summary contains required fields.
- Renderer has post-call summary rendering.
- Web conversation output includes summary.

Acceptance:
- `python -m unittest tests.test_agent tests.test_renderer_ui tests.test_web -q`
- `npm run check`

### WP8: Privacy and Inspector Foundation

Files touched:
- `fluent_ai/state.py`
- `fluent_ai/desktop_bridge.py`
- `fluent_ai/web.py`
- `desktop/electron/preload.js`
- `desktop/electron/main.js`
- `desktop/electron/renderer.html`
- `tests/test_agent.py`
- `tests/test_web.py`
- `tests/test_renderer_ui.py`

Work:
- Add bridge commands for export, delete all memory, and reset active language.
- Add safe memory-inspector payload that excludes raw image/audio and secrets.
- Render a compact memory inspector.

Tests:
- Export returns v2 state.
- Reset removes one language only.
- Delete resets to default v2.
- Renderer exposes inspector controls.

Acceptance:
- `python -m unittest tests.test_agent tests.test_web tests.test_renderer_ui -q`
- `npm run check`
