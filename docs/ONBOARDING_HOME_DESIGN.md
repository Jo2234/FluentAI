# Onboarding, home, and privacy boundaries

## Current flow

The shared Electron/browser renderer starts with onboarding when required, then Home. Onboarding records native/target language, motivation, goals, session length, correction/tutor preferences, accessibility preferences, and speaking comfort. A learner may start as a beginner or complete placement. Placement combines quiz/written/conversation evidence to seed a level, confidence, strengths, weaknesses, and initial practice goals; it is not a certified assessment.

`home_summary` returns the next recommendation, review preview, recent progress, and speaking-confidence summary. Recommendations reuse the lesson/conversation selection logic so Home and the next activity agree.

## Memory controls

| Bridge command | Behavior |
| --- | --- |
| `memory_inspect` | Returns a sanitized view of learner and selected-language memory |
| `memory_export` | Exports one language by default, or all languages with `scope=all`; records export time |
| `memory_reset_language` | Requires `RESET <language>`; resets that language while preserving other languages and top-level learner/preferences/privacy |
| `memory_delete_all` | Requires `DELETE ALL MEMORY`; replaces progress with a fresh generation and removes managed session checkpoints, TTS cache, corrupt backups, and temporary recovery files |

Electron exports through a save dialog; the browser downloads JSON. Exports omit secrets, raw media, and internal fields through the bridge sanitizer. They are selected memory views, not full round-trip database backups. Delete-all prevents stale in-flight sessions from restoring deleted learning memory. Previously exported copies outside managed storage and the separately managed API key are not learner-memory deletion targets.

## Local storage versus provider access

The schema's `privacy.local_only` describes local learner-memory storage. The app still sends relevant learner context and text to OpenAI for teaching and grading, audio for Realtime calls, camera frames for enabled vision context, and phrase text for speech synthesis. It is not an offline app.

Raw microphone recordings and raw camera video are not persisted as learner memory. Transcripts, corrections, session checkpoints, and camera summaries can contain personal context. Generated phrase audio is cached under `cache/tts` beside the state file and removed by delete-all. Camera sampling skips unchanged frames before inference, with explicit capture and a bounded refresh; fake test feeds must not become claimed real-world objects.

The browser server only answers same-origin loopback requests that carry the per-launch app token. Other websites cannot read or delete memory through it (see [local web security](GAP_AND_DESIGN.md#local-web-security)). Any local process that can load the page can still obtain the token, just as it could read `data/` directly.

The privacy fields document intent and supported controls; do not treat them as a general consent engine or a guarantee about provider retention. Keep API keys out of progress, exports, and logs. Electron key storage and precedence are described in [packaging](PACKAGING_DESIGN.md).

## Validation limits

Tests cover sanitization, export/reset behavior, complete managed-memory deletion, and stale-session rejection. Physical permission dialogs and clean-account desktop acceptance remain manual checks in the [roadmap](FLUENTAI_LIMITLESS_IDEAL.md).
