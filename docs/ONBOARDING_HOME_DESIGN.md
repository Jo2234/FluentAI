# FluentAI Onboarding, Home Workspace, and Memory Inspector Design

Scope: WS3 onboarding/placement and WS4 home tutor workspace. This is a design-only handoff. Do not introduce a frontend framework; keep the shared single-file renderer used by Electron and `fluent_ai/web.py`.

Current anchors:
- State v2 is implemented in `fluent_ai/state.py`: `load_state`, `migrate_state`, `active_language`, `language_state`, `profile_state`, `skill_scores`, `set_skill_score`, `topic_scores`, `set_topic_score`, `conversation_memory`, `review_queue`, `record_mistake`, `add_event`, `save_state`.
- Lesson evaluation exists in `fluent_ai/agent.py`: `LESSON_BANK`, `generate_lesson`, `generate_quiz`, `evaluate_answers`, `update_progress`, `due_review_items`, `due_mistake_items`, `choose_topic_with_reason`.
- Conversation evaluation exists in `fluent_ai/conversation.py`: `choose_conversation_topic`, `evaluate_reply_with_metadata`, `apply_turn_progress`, `persist_post_call_summary`.
- Bridge surface is `fluent_ai/desktop_bridge.py:COMMANDS`; current commands are `status`, `realtime_client_secret`, `vision_analyze_frame`, `lesson_start`, `lesson_submit`, `conversation_start`, `conversation_reply`, `conversation_end`.
- Web bridge proxy is `fluent_ai/web.py:FluentAIHandler._run_bridge_command` via `POST /api/bridge/<command>`. `/api/progress` currently returns raw v2 state.
- Electron exposes bridge calls in `desktop/electron/preload.js`; `desktop/electron/main.js:runBridge` maps IPC handlers to Python bridge commands.
- Renderer structure is `desktop/electron/renderer.html`: header (`headerMeta`, `headerPills`, `languageSelect`, mode tabs), workspace (`workspace`), launch controls (`startLessonBtn`, `startConversationBtn`), lesson pane (`lessonPane`, `lessonContent`), conversation pane (`conversationPane`, `callStage`, `chatLog`), and agent rail (`agentLogPanel`, `agentLogs`). The file already has the 2026-07-08 aurora studio CSS override and post-call summary rendering.

## Part 1: WS3 Onboarding and Placement

### Trigger and Lifecycle

First launch means either:
- the selected `state_path` file is absent before `load_state` creates it, or
- the loaded v2 state lacks `learner.onboarded_at`.

`onboarding_status` must check `Path.exists()` before `load_state` so the UI can distinguish "brand new file" from "existing profile missing onboarding metadata". Re-run onboarding from the home workspace through a "Meet your tutor again" affordance. Re-running must preserve learning memory by default and only update onboarding fields unless the user chooses placement again.

Stop conditions:
- Onboarding is complete when `learner.onboarded_at` is set and `onboarding_status.requires_onboarding == false`.
- Placement is complete when `languages[lang].profile.placement_completed_at` is set and a `placement_completed` event exists for that language.
- Skipping placement writes an explicit `placement_completed` event with `payload.method == "skip_beginner"` so later logic can explain why the learner starts at A1.

### Onboarding Steps and State Mapping

Use one full-screen overlay stage before the normal workspace. Keep copy short, like a tutor intake, not a settings wizard.

| Step | Answer | Existing state writes | Additions needed |
|---|---|---|---|
| Name or nickname | free text | `learner.display_name` | none |
| Target language | `Hindi`, `Spanish`, `French` | `active_language`; create `languages[lang]` through `language_state`; `languages[lang].profile.target_language` | none |
| Why / goal | short free text plus optional chips | `learner.motivation`; `learner.active_goals`; `languages[lang].profile.learning_goals` | none |
| Self-estimated level | `new`, `A1`, `A2`, `B1+`, `not sure` | if placement skipped, seed `languages[lang].profile.current_level`; otherwise do not trust it as final | `languages[lang].profile.self_reported_level` |
| Speaking comfort | `quiet`, `some`, `comfortable` | seed `languages[lang].conversation_memory.speaking_confidence` conservatively (`0.22`, `0.35`, `0.50`) | `languages[lang].profile.speaking_comfort` |
| Session length | `5`, `10`, `15` minutes | `learner.preferred_session_length_minutes`; `preferences.lesson_minutes` | none |
| Voice/video expectations | voice on/off preference, video default off/on | `preferences.voice`; `preferences.video_default`; do not request mic/camera yet | optional `preferences.voice_default` if voice availability should be separate from selected voice name |
| Privacy note | local memory acknowledgement | `privacy.local_only = true`; `privacy.store_raw_audio = false`; `privacy.store_raw_video = false`; `privacy.store_camera_summaries = true` | `learner.onboarded_at`; optional `privacy.local_memory_notice_seen_at` |

Recommended additions normalized by `fluent_ai/state.py:_normalize_v2_state` / `_normalize_language_state`:
- `learner.onboarded_at: str | null`
- `learner.last_onboarding_at: str | null` for reruns
- `privacy.local_memory_notice_seen_at: str | null`
- `languages[lang].profile.self_reported_level: str | null`
- `languages[lang].profile.speaking_comfort: "quiet" | "some" | "comfortable" | null`
- `languages[lang].profile.placement_completed_at: str | null`
- `languages[lang].profile.placement_method: "adaptive" | "skip_beginner" | null`
- `languages[lang].profile.first_practice_goal: str | null`
- `languages[lang].profile.judged_strengths: list[str]`
- `languages[lang].profile.judged_weaknesses: list[str]`

### Placement Flow

Placement is short and adaptive, not a separate test product.

Default flow:
1. `placement_start` builds 3-5 comprehension/recall items from existing lesson bank material. Use `fluent_ai/agent.py:LESSON_BANK` for Spanish and `_generic_lesson_bank` via a generated lesson for non-Spanish. Prefer mixed `multiple_choice`, `fill_blank`, and reading comprehension questions from `generate_quiz`.
2. Optional written prompt: one `open_ended` item evaluated through `evaluate_answers`. If OpenAI grading is available, reuse `_apply_openai_quiz_grading` exactly as `lesson_submit` does; otherwise local evaluator still works.
3. Optional typed/spoken prompt: use `conversation.py:evaluate_reply_with_metadata` against a topic from `choose_conversation_topic`. Spoken input may be transcript text; do not store raw audio.
4. Output judged level, confidence, strongest skills, weakest skills, first lesson/practice goal, and first conversation goal.

Skippable path:
- CTA: "Start as beginner instead".
- Set `profile.current_level = "A1"`, `profile.level_confidence = 0.35`, `profile.placement_method = "skip_beginner"`, `profile.first_practice_goal = "Build basic introductions and daily phrases."`, and `conversation_memory.next_conversation_goal` to an A1 introductions goal.

Judging rule:
- Compute quiz accuracy and optional prompt scores as deterministic signals.
- If self-report is `new`, `A1`, or `not sure`, cap judged level at `B1` even with perfect results.
- Suggested bands: `<45% => A1`, `45-72% => A2`, `>72% => B1`; only allow `B2+` later through continuous assessment, not first-run placement.
- `profile.level_confidence`: `0.35` skip, `0.50` quiz-only, `0.60` quiz+written, `0.70` quiz+written+conversation.
- Skill seeds: aggregate by question `skill`; optional written affects `writing` and focus skill; optional speaking affects `speaking`, `fluency`, and topic `spoken_use`.
- Strongest/weakest: top/bottom 2 skills after bounded seed updates through `set_skill_score`.

Placement writes:
- `languages[lang].profile.current_level`
- `languages[lang].profile.level_confidence`
- `languages[lang].profile.placement_completed_at`
- `languages[lang].profile.placement_method`
- `languages[lang].profile.first_practice_goal`
- `languages[lang].profile.judged_strengths`
- `languages[lang].profile.judged_weaknesses`
- `languages[lang].weak_topics`
- `languages[lang].conversation_memory.speaking_confidence`
- `languages[lang].conversation_memory.next_speaking_goal`
- `languages[lang].conversation_memory.next_conversation_goal`, shaped like current lesson-derived goals: `{source, topic, skill, instruction, reason}`
- skill/topic evidence with `evidence.mode == "placement"`
- top-level and language history event `type: "placement_completed"` through `add_event`

Example `placement_completed.payload`:
```json
{
  "method": "adaptive",
  "self_reported_level": "A1",
  "judged_level": "A2",
  "level_cap_applied": false,
  "quiz_score": "4/5",
  "written_score": 0.62,
  "conversation_score": 0.48,
  "strongest_skills": ["vocabulary", "reading"],
  "weakest_skills": ["speaking", "conjugations"],
  "first_practice_goal": "Practice daily introductions with complete sentences.",
  "first_conversation_goal": "Answer two simple introduction questions in full Spanish sentences."
}
```

### New Bridge Commands

Add to `fluent_ai/desktop_bridge.py:COMMANDS`, expose through `preload.js`, map in `main.js`, and rely on existing `/api/bridge/<command>` in `web.py`.

`onboarding_status`
- Payload: `{ "state_path"?: string, "language"?: string }`
- Response:
```json
{
  "ok": true,
  "requires_onboarding": true,
  "is_first_launch": true,
  "requires_placement": true,
  "profile": {},
  "defaults": {"language": "Spanish", "session_minutes": 10, "video_default": "off"},
  "logs": ["[Onboarding Agent] First launch detected."]
}
```
- Semantics: no destructive writes except normal `load_state` creation/migration. If file existed and `learner.onboarded_at` exists, return `requires_onboarding: false`.

`onboarding_submit`
- Payload:
```json
{
  "display_name": "Johan",
  "language": "Spanish",
  "motivation": "Travel and conversation",
  "goals": ["Hold a 5-minute conversation"],
  "self_reported_level": "A1",
  "speaking_comfort": "some",
  "session_minutes": 10,
  "voice_default": "openai",
  "video_default": "off",
  "privacy_local_only": true,
  "state_path": "data/progress.json"
}
```
- Response: `{ "ok": true, "profile": profile_for(...), "requires_placement": true, "logs": [...] }`
- Semantics: update only intake fields, set `learner.onboarded_at` if missing, always set `learner.last_onboarding_at`, add `onboarding_completed` event. Do not run placement here.

`placement_start`
- Payload: `{ "language": "Spanish", "include_written": true, "include_conversation": true, "state_path"?: string }`
- Response:
```json
{
  "ok": true,
  "session": {
    "id": "placement_20260708_000001",
    "language": "Spanish",
    "items": [],
    "written_prompt": {},
    "conversation_prompt": {}
  },
  "profile": {},
  "logs": ["[Placement Agent] Built a 5-item adaptive check from the lesson bank."]
}
```
- Semantics: read state and produce questions; do not save score yet unless a lightweight `placement_started` event is desired. Use existing quiz item shape so renderer can reuse `questionNode` patterns.

`placement_submit`
- Payload:
```json
{
  "session": {},
  "answers": ["Nice to meet you", "Soy", "..."],
  "written_answer": "Me llamo Johan.",
  "conversation_answer": "Me llamo Johan y vivo en Nueva York.",
  "skip_beginner": false,
  "state_path": "data/progress.json"
}
```
- Response:
```json
{
  "ok": true,
  "profile": {},
  "placement": {
    "judged_level": "A2",
    "level_confidence": 0.6,
    "strongest_skills": ["vocabulary"],
    "weakest_skills": ["speaking"],
    "first_practice_goal": "...",
    "first_conversation_goal": "..."
  },
  "logs": ["[Placement Agent] Judged starting level A2 from 4/5 placement items."]
}
```
- Semantics: evaluate via existing evaluators, update v2 state, save, add `placement_completed`.

### Renderer Design

Add a full-screen overlay before workspace:
- DOM after `<body>` start, before `<header>`:
  - `section#onboardingOverlay.onboarding-overlay.hidden`
  - `div#onboardingStage`
  - `div#onboardingProgress`
  - `form#onboardingForm`
  - `div#placementStage.hidden`
  - `div#placementItems`
  - `button#onboardingNextBtn`
  - `button#placementSkipBtn`
  - `button#placementSubmitBtn`
- Add CSS near aurora override for `.onboarding-overlay`, `.onboarding-card`, `.onboarding-grid`, `.placement-item`, `.privacy-note`; use existing variables and 8-24px radius rhythm from the aurora studio style.
- Add `state.onboarding`, `state.placementSession`.
- Extend `window.fluentAI` fallback with `onboardingStatus`, `submitOnboarding`, `startPlacement`, `submitPlacement`.
- Add to `els`: overlay/stage/form/buttons.
- New JS functions:
  - `initOnboarding()`: call `window.fluentAI.onboardingStatus(bridgePayload())` before `refreshStatus`.
  - `showOnboardingOverlay(status)`
  - `renderOnboardingStep(index)`
  - `collectOnboardingAnswers()`
  - `submitOnboarding(event)`
  - `startPlacement()`
  - `renderPlacement(session)`
  - `submitPlacement({skipBeginner=false})`
  - `finishOnboarding(result)`: hide overlay, `renderProfile`, `appendLogs`, then `refreshStatus(true)` and `ensureLessonStarted`.
- Startup order changes from `refreshStatus().then(ensureLessonStarted)` to `initOnboarding()`, which either runs the overlay or continues to existing status/lesson auto-start.
- Re-run affordance: add a small button in the future home/memory region, not the header tabs, labeled "Meet your tutor again". It calls `showOnboardingOverlay({rerun:true})`.

## Part 2: WS4 Home Tutor Workspace

### Home Summary Command

Add a dedicated `home_summary` bridge command rather than bloating `status`.

`home_summary`
- Payload: `{ "language": "Spanish", "state_path"?: string }`
- Response:
```json
{
  "ok": true,
  "profile": {},
  "today": {
    "kind": "due_review",
    "title": "Review due phrases",
    "body": "2 items are due; start with past tense.",
    "cta": "Review due phrases",
    "mode": "lesson",
    "topic": "past tense",
    "reason": "Due reviews come before fresh lessons."
  },
  "review_preview": [],
  "recent_progress": [],
  "speaking_confidence": {"score": 0.34, "trend": "up", "recent": []},
  "memory_counts": {"events": 34, "mistakes": 3, "reviews_due": 2},
  "logs": ["[Home Agent] Recommended due review before fresh lesson."]
}
```

Deterministic recommendation rule, computed in `desktop_bridge.py:home_summary` using v2 helpers:
1. If `due_review_items(state)` is non-empty, recommend lesson mode with CTA "Review due phrases".
2. Else if `due_mistake_items(state)` is non-empty, recommend lesson mode with CTA "Practice yesterday's weak topic".
3. Else if `conversation_neglected(state)` is true, recommend conversation mode with CTA "Start live tutor call".
4. Else if `conversation_memory.next_conversation_goal` exists and the last completed lesson produced it but no later conversation has addressed it, recommend conversation mode with CTA "Use this in conversation".
5. Else if `profile.first_practice_goal` exists and `daily_summary.lessons_completed == 0`, recommend lesson mode with CTA "Start today's lesson".
6. Else recommend fresh lesson mode with CTA "Start today's lesson".

Conversation neglected rule:
- Let `lesson_completed_count_since_last_conversation` be the count of `lesson_completed` events after the last `conversation_started` event in `languages[lang].history`.
- If count >= 3, or `conversation_memory.sessions_completed == 0` and at least one lesson is complete, conversation is neglected.
- Reason text: "You have practiced lessons without a tutor call recently."

CTA behavior:
- `Start today's lesson`: calls existing `startLesson()`.
- `Review due phrases`: calls existing `startLesson()`; backend topic selection already prioritizes due reviews.
- `Practice yesterday's weak topic`: calls existing `startLesson()`; topic selection already checks due mistakes before weak topics.
- `Start live tutor call`: `setMode("conversation")`, keep current `voiceMode`, then `startConversation()`.
- `Use this in conversation`: same as call CTA; `choose_conversation_topic` already reads `next_conversation_goal`.

### Home Regions Mapped to Current Renderer

Current renderer starts in lesson mode and auto-starts via `ensureLessonStarted`. WS4 should make home the default first workspace surface, then let CTA launch modes.

New:
- `div#homePane.pane` as the default pane in `workspace`, replacing the initial empty-state-first experience.
- `section#todayPanel` for recommendation card.
- `section#homeProfilePanel` with profile summary and "Meet your tutor again".
- `section#reviewPreviewPanel` with top 3 due/scheduled reviews.
- `section#recentProgressPanel` from typed events.
- `section#speakingTrendPanel` with confidence score and trend.
- `details#memoryInspectorPanel` for sanitized memory.

Reuse:
- Header language selector: `languageSelect`.
- Mode launchers: existing `lessonModeBtn`, `conversationModeBtn`, `startLessonBtn`, `startConversationBtn`; move/duplicate CTA affordances into home panel without changing backend semantics.
- Lesson area: `lessonPane`, `lessonContent`, `lessonHero`, `submitQuiz`.
- Call stage: `conversationPane`, `callStage`, `chatLog`, voice/text fallback.
- Agent log: `agentLogPanel`, `agentLogs`, `appendLogs`, `syncAgentLogPanel`.
- Profile rendering: extend `renderProfile`; keep compatibility keys from `profile_for`.

Renderer functions:
- Add `state.homeSummary`.
- Add `loadHomeSummary()`, `renderHome(summary)`, `runTodayAction()`, `showHome()`.
- `refreshStatus` can still update profile; `loadHomeSummary` owns today/review/recent/memory counts.
- After `submitQuiz`, `sendConversationReply`, and `endRealtimeCall`, call `loadHomeSummary()` after `renderProfile`.
- Disable lesson auto-start on initial app load once home exists. `ensureLessonStarted` should only run from explicit lesson CTA or if preserving current demo behavior behind a `?autostart=lesson` style flag later.

### Memory Inspector

Recommend a dedicated sanitized command: `memory_inspect`. Do not drive the inspector from `/api/progress`, because `/api/progress` is raw state and can include future sensitive payloads.

`memory_inspect`
- Payload: `{ "language": "Spanish", "state_path"?: string }`
- Response:
```json
{
  "ok": true,
  "language": "Spanish",
  "learner": {"display_name": "Johan", "motivation": "...", "onboarded_at": "..."},
  "profile": {"current_level": "A2", "level_confidence": 0.6, "learning_goals": []},
  "skills": [{"name": "speaking", "score": 0.34, "trend": "up", "last_practiced": "..."}],
  "topic_mastery": [{"topic": "introductions", "recognition": 0.5, "recall": 0.42, "spoken_use": 0.35}],
  "mistakes": [{"incorrect_form": "...", "corrected_form": "...", "skill": "speaking", "topic": "introductions", "frequency": 2, "next_review": "..."}],
  "review_queue": [{"id": "...", "target": "past tense", "skill": "conjugations", "due_at": "...", "source": "lesson"}],
  "conversation": {"speaking_confidence": 0.34, "next_speaking_goal": "...", "next_conversation_goal": {}, "post_call_summaries": []},
  "recent_events": [{"id": "evt_...", "type": "lesson_completed", "occurred_at": "...", "summary": "..."}],
  "privacy": {"local_only": true, "store_raw_audio": false, "store_raw_video": false, "store_camera_summaries": true},
  "redactions": ["raw audio", "raw video", "image data URLs", "API keys"]
}
```

Sanitization rules:
- Include summaries and learning signals only.
- Do not include raw image data URLs, raw audio, raw video, API keys, realtime client secrets, raw bridge `raw` stderr, or full transcript beyond bounded post-call summaries already stored.
- `last_video_context.summary` and `primary_object` are allowed because v2 is designed to store camera summaries, not images.

Inspector UI:
- `details#memoryInspectorPanel` collapsed by default.
- Sections: Profile, Skills, Topic mastery, Mistake memory, Review queue, Conversation memory, Recent events, Privacy.
- Use small tables/lists, not raw JSON by default.
- Include "Show JSON" toggle for the sanitized payload only.
- Agent log every open/export/reset/delete action.

Export and delete commands:

`memory_export`
- Payload: `{ "language"?: "Spanish" | null, "scope": "all" | "language", "state_path"?: string }`
- Response: `{ "ok": true, "filename": "fluentai-memory-20260708.json", "data": {...}, "logs": [...] }`
- Semantics: bridge returns sanitized export data and updates `privacy.last_exported_at`; Electron uses `dialog.showSaveDialog` in `main.js` to write JSON to a user-chosen location, while web fallback downloads a Blob. Browser download must not require filesystem paths.

`memory_reset_language`
- Payload: `{ "language": "Spanish", "confirm": "RESET Spanish", "state_path"?: string }`
- Response: `{ "ok": true, "profile": {}, "memory": {}, "logs": [...] }`
- Semantics: replace only `languages[language]` with a fresh `_default_language_state(language)` via a public helper such as `reset_language_state(state, language)`. Preserve top-level `learner`, `preferences`, `privacy`, other languages, and `learner.onboarded_at`. If resetting active language, keep it active but fresh. Add `language_reset` event to top-level `events` after reset if possible.

`memory_delete_all`
- Payload: `{ "confirm": "DELETE ALL MEMORY", "state_path"?: string }`
- Response: `{ "ok": true, "profile": {}, "logs": [...] }`
- Semantics: replace the file with `default_state(active_language_or_payload_language)` via a public helper such as `delete_all_memory(path, language)`. This removes onboarding and placement, so next `onboarding_status` returns `requires_onboarding: true`. Do not delete the file path itself; write fresh v2 JSON for reliability.

Electron IPC additions:
- `preload.js`: `homeSummary`, `memoryInspect`, `memoryExport`, `memoryResetLanguage`, `memoryDeleteAll`, plus onboarding/placement methods.
- `main.js`: map IPC to bridge commands. For export, main should own `dialog.showSaveDialog` and `fs.writeFile`; renderer should receive `{ok, path?}` but never need arbitrary filesystem access.
- Web fallback in renderer: call `/api/bridge/memory_export`, then `URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)]))`.

## Part 3: Sequenced Implementation Plan

Renderer packages must be sequential. Do not run two renderer-editing agents in parallel.

### WP1: State Metadata and Onboarding Bridge

Files touched:
- `fluent_ai/state.py`
- `fluent_ai/desktop_bridge.py`
- `desktop/electron/main.js`
- `desktop/electron/preload.js`
- `tests/test_state_v2.py`
- `tests/test_agent.py`
- `tests/test_web.py`

New bridge commands: `onboarding_status`, `onboarding_submit`.

Renderer regions: none in this package.

Tests:
- state defaults normalize new onboarding/profile fields.
- absent file returns `is_first_launch: true`.
- existing state without `learner.onboarded_at` requires onboarding.
- `onboarding_submit` writes exact mapped fields and `onboarding_completed`.
- `/api/bridge/onboarding_status` and `/api/bridge/onboarding_submit` work through `web.py`.

Acceptance: `npm run check` green.

### WP2: Placement Bridge and Evaluator Reuse

Files touched:
- `fluent_ai/desktop_bridge.py`
- `fluent_ai/state.py` only if reset/helper additions from WP1 did not cover placement metadata normalization
- `tests/test_agent.py`
- `tests/test_web.py`

New bridge commands: `placement_start`, `placement_submit`.

Renderer regions: none in this package.

Tests:
- `placement_start` returns 3-5 existing quiz-shaped items.
- `placement_submit` adaptive path writes judged level, skill evidence, first goals, `next_conversation_goal`, and `placement_completed`.
- beginner self-report cap prevents `B2+`.
- skip path writes A1 beginner state and `payload.method == "skip_beginner"`.
- OpenAI quiz grading remains mocked and no new model interface is introduced.
- web bridge endpoint accepts both placement commands.

Acceptance: `npm run check` green.

### WP3: Onboarding and Placement Renderer Overlay

Files touched:
- `desktop/electron/renderer.html`
- `desktop/electron/preload.js`
- `desktop/electron/main.js`
- `tests/test_renderer_ui.py`
- `tests/test_web.py`

New bridge commands exposed to renderer: `onboarding_status`, `onboarding_submit`, `placement_start`, `placement_submit`.

Renderer regions:
- `onboardingOverlay`
- `onboardingStage`
- `onboardingForm`
- `placementStage`
- `placementItems`
- placement skip/submit buttons

Tests:
- renderer string assertions for overlay IDs, fallback web bridge methods, "Start as beginner instead", privacy local-memory copy, and startup `initOnboarding`.
- preload exposes onboarding/placement APIs.
- main maps IPC to bridge commands.
- web fallback can post to `/api/bridge/onboarding_status`.

Acceptance: `npm run check` green and first launch visibly blocks workspace until onboarding is submitted or completed.

### WP4: Home Workspace and Memory Inspector

Files touched:
- `fluent_ai/desktop_bridge.py`
- `fluent_ai/state.py`
- `fluent_ai/web.py` only if adding a convenience download route; otherwise existing bridge proxy is enough
- `desktop/electron/main.js`
- `desktop/electron/preload.js`
- `desktop/electron/renderer.html`
- `tests/test_agent.py`
- `tests/test_web.py`
- `tests/test_renderer_ui.py`

New bridge commands: `home_summary`, `memory_inspect`, `memory_export`, `memory_reset_language`, `memory_delete_all`.

Renderer regions:
- `homePane`
- `todayPanel`
- `homeProfilePanel`
- `reviewPreviewPanel`
- `recentProgressPanel`
- `speakingTrendPanel`
- `memoryInspectorPanel`

Tests:
- home recommendation priority: due reviews > due mistakes > neglected conversation > lesson-to-conversation goal > first practice goal > fresh lesson.
- sanitized memory payload excludes raw image data URLs and secret-looking strings.
- export returns sanitized v2 payload and updates `privacy.last_exported_at`.
- reset language preserves other languages and top-level learner/preferences/privacy.
- delete all resets to default and makes onboarding required.
- renderer assertions for home pane IDs, memory inspector sections, export/reset/delete confirmations, and no initial `ensureLessonStarted` autostart when home is present.
- web endpoint tests for all new bridge commands.

Acceptance: `npm run check` green. Demo can show: intake, placement result, home recommendation reason, mode launch, progress update, memory inspector, export/reset/delete controls, and agent decision logs throughout.
