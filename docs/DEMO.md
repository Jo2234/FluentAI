# Live API walkthrough

[Watch the narrated recording](media/workflow-demo.mp4) · [Captions](media/narration.vtt) · [Capture metadata](media/recording.json)

The 93-second recording runs the production Python bridge and shared browser renderer against OpenAI's Responses API. Five requests completed using `gpt-5.5-2026-04-23`, consuming 2,136 input and 623 output tokens. Responses were observed without modification; there was no fixture provider or response substitution.

| Time | Visible behavior |
| --- | --- |
| 2–13 s | Load a fresh Spanish learner and start a lesson |
| 13–34 s | Read generated vocabulary and answer six questions, including one deliberate mistake |
| 35–46 s | See specific feedback, a 5/6 result, 55 XP, and scheduled review |
| 47–77 s | Practice with the text tutor; it corrects the tense and asks a follow-up question |
| 78–93 s | Inspect saved memory and reload; 55 XP and three reviews persist |

Capture used a disposable default A1 profile with onboarding and placement marked complete before recording. It did not read existing personal learner data. The top 48 pixels of a recording-only status banner were cropped from the final 1440×952 video; the timeline is continuous, with no speed changes or generated UI. Real calls, replies, timings, and initial/final state were retained privately for verification. Credentials and request headers are excluded from published artifacts.

English narration was added after capture using the generic Kokoro `af_heart` voice. Its [timed script and hashes](media/narration.json) describe the actual visible results. This walkthrough uses text conversation; Realtime voice, microphone, camera, and desktop packaging are outside its scope.

## Run the real app

Install the project as described in the root README, configure `OPENAI_API_KEY` in the server environment, and start:

```bash
python -m fluent_ai.web --port 7860
```

Open `http://127.0.0.1:7860`, use a separate learner profile, complete placement, then try a lesson and text conversation. The recording used `OPENAI_MODEL=gpt-5.5`, reasoning effort `low`, and verbosity `low`. Model-generated lessons, replies, and timings vary; inspect the actual results when narrating a new capture. Paid calls are required for ordinary app use.

## Offline development harness

`scripts/portfolio_demo.py` and `scripts/record_portfolio_demo.cjs` remain available as explicit mock-provider development tools. The harness uses `FluentAIServer`. The recorder copies the page's per-launch token into its direct API check. They write the older labelled workflow capture under ignored `cache/offline-recording/`, keeping it separate from the published live API assets. Tests continue to mock providers so CI requires no credentials or paid requests.

## Validation

The live capture verified five completed Responses requests, specific wrong-answer feedback, three scheduled reviews, and saved progress after reload, with no browser errors or failed bridge responses. Separately, 133 Python tests passed without skips and all 11 JavaScript renderer scenarios passed. The lesson screenshot comes from the new API-backed recording. Original mockups, earlier captures, and historical validation remain in Git history.
