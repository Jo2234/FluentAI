# Plan

## Goal
Create a demoable agentic language learning app with Lesson Mode and Conversation Mode. Both modes read local learner state, adapt to current ability, update progress, and make agent decisions visible during a judging demo.

## MVP Shape
- Python CLI loop for a reliable judging demo.
- Local state in `data/progress.json`.
- Autonomous demo mode that simulates learner answers so the loop can run unattended for 5-10 minutes.
- Interactive mode for a real learner.
- Standalone fullscreen Electron desktop app for manual testing outside the browser.
- Conversation mode: a FaceTime-like tutor that initiates and steers spoken/chat conversation based on learner ability, with video optional.
- Video-on conversation can use an object/image context such as "apple" to keep the target-language conversation grounded.
- Optional Gradio UI when the dependency is installed, with console fallback.
- OpenAI-backed generation with deterministic local fallback.

## Build Steps
- Scaffold project docs and concise Goal-mode instructions. Done.
- Implement local learner state model. Done.
- Implement lesson generation, quiz generation, evaluation, and adaptation. Done.
- Add a CLI loop with duration and interval settings. Done.
- Add a smoke test or command that proves state updates. Done.
- Add optional Gradio UI fallback. Done.
- Add Conversation Mode state, turn loop, adaptive topic steering, video-object handling, and memory updates. Done.
- Add `.env` loading and OpenAI Responses API support for lesson enhancement and conversation tutor utterances. Done.
- Add no-dependency local web app for browser testing. Done.
- Add standalone fullscreen Electron desktop app. Done.
- Replace transcript-only desktop output with real lesson quiz submission and turn-by-turn conversation. Done.
- Apply approved red Duolingo-inspired Demo Studio UI to the Electron and browser app. Done.
- Polish Lesson Mode UI and make Conversation Mode voice-first with text fallback. Done.
- Add OpenAI Realtime voice-agent integration for speech-to-speech conversation. Done.
- Put voice-only and video calls in the main Conversation Mode stage instead of a side panel. Done.
- Replace typed video-object demo labels with OpenAI camera-frame recognition. Done.
- Stabilize call/video/text fallback UX after live app testing. Done.
- Make video mode use the live camera feed with recurring OpenAI vision updates and filter synthetic green test feeds. Done.
- Remove model-name UI copy and improve English-help responsiveness in tutor conversation. Done.
- Add Hindi, Spanish, and French language selection across lessons, text fallback, realtime voice, and camera-context prompts. Done.

## Next
- Continue polishing the red Demo Studio UI after user feedback.
- Add spaced repetition scheduling.
