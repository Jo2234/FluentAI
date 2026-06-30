from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from fluent_ai.agent import answer_quiz, evaluate_answers, generate_lesson, generate_quiz, progress_report, snapshot_progress, update_progress
from fluent_ai.app import DEFAULT_PROGRESS_PATH
from fluent_ai.conversation import run_conversation
from fluent_ai.desktop_bridge import COMMANDS as BRIDGE_COMMANDS
from fluent_ai.openai_provider import OpenAIProvider
from fluent_ai.state import load_state, save_state


MAX_JSON_BYTES = 64_000

HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FluentAI</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #172026;
      --muted: #5e6a71;
      --line: #d9e0e4;
      --panel: #fff5f5;
      --accent: #ef4444;
      --accent-strong: #b91c1c;
      --warm: #f59e0b;
      --surface: #ffffff;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      background:
        linear-gradient(180deg, #fff1f2 0%, #ffffff 360px),
        var(--surface);
      font: 15px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    header {
      border-bottom: 1px solid var(--line);
      padding: 18px 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }
    h1, h2, h3, p { margin: 0; }
    h1 { font-size: 22px; }
    h2 { font-size: 18px; margin-bottom: 12px; }
    main {
      display: grid;
      grid-template-columns: minmax(280px, 380px) minmax(0, 1fr);
      min-height: calc(100vh - 70px);
    }
    aside {
      border-right: 1px solid var(--line);
      background: var(--panel);
      padding: 20px;
    }
    section { padding: 20px; }
    .status {
      color: var(--muted);
      font-size: 13px;
      max-width: 720px;
    }
    .field { margin: 14px 0; }
    label {
      display: block;
      font-weight: 650;
      margin-bottom: 6px;
    }
    input, select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px 11px;
      font: inherit;
      background: #fff;
    }
    button {
      border: 0;
      border-radius: 6px;
      background: var(--accent);
      color: white;
      padding: 10px 13px;
      font-weight: 700;
      cursor: pointer;
    }
    button.secondary { background: var(--warm); color: #2f2100; }
    button:hover { background: var(--accent-strong); }
    button.secondary:hover { background: #d97706; }
    .actions { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 18px; }
    .video {
      aspect-ratio: 16 / 10;
      border: 1px solid var(--line);
      border-radius: 8px;
      background:
        linear-gradient(135deg, #991b1b 0%, #172026 100%);
      color: #fff;
      display: grid;
      place-items: center;
      text-align: center;
      padding: 20px;
      margin-bottom: 14px;
    }
    .video strong { display: block; font-size: 22px; margin-bottom: 8px; }
    .output {
      white-space: pre-wrap;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      min-height: 420px;
      background: #fff;
      overflow: auto;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 5px 9px;
      color: var(--muted);
      font-size: 13px;
      margin-right: 6px;
    }
    @media (max-width: 860px) {
      main { grid-template-columns: 1fr; }
      aside { border-right: 0; border-bottom: 1px solid var(--line); }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>FluentAI</h1>
      <p class="status" id="status">Loading model status...</p>
    </div>
    <div><span class="pill">Lesson Mode</span><span class="pill">Conversation Mode</span></div>
  </header>
  <main>
    <aside>
      <div class="video" id="videoPreview">
        <div><strong>Video Off</strong><span>Turn video on and type an object like apple.</span></div>
      </div>
      <h2>Controls</h2>
      <div class="field">
        <label for="turns">Conversation turns</label>
        <input id="turns" type="number" min="2" max="8" value="4">
      </div>
      <div class="field">
        <label for="video">Video</label>
        <select id="video">
          <option value="off">Off</option>
          <option value="on">On</option>
        </select>
      </div>
      <div class="field">
        <label for="object">Visible object</label>
        <input id="object" placeholder="apple, banana, book, cup">
      </div>
      <div class="actions">
        <button id="lessonBtn">Run Lesson</button>
        <button class="secondary" id="conversationBtn">Start Conversation</button>
      </div>
    </aside>
    <section>
      <h2>Agent Output</h2>
      <div class="output" id="output">Choose a mode to begin.</div>
    </section>
  </main>
  <script>
    const output = document.getElementById("output");
    const statusEl = document.getElementById("status");
    const videoEl = document.getElementById("video");
    const objectEl = document.getElementById("object");
    const preview = document.getElementById("videoPreview");

    async function postJSON(url, body) {
      output.textContent = "Running agents...";
      const response = await fetch(url, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body || {})
      });
      const data = await response.json();
      output.textContent = data.text || JSON.stringify(data, null, 2);
    }

    async function loadStatus() {
      const response = await fetch("/api/status");
      const data = await response.json();
      statusEl.textContent = data.status;
    }

    function updateVideoPreview() {
      const on = videoEl.value === "on";
      const objectName = objectEl.value.trim() || "camera object";
      preview.textContent = "";
      const wrapper = document.createElement("div");
      const title = document.createElement("strong");
      const caption = document.createElement("span");
      title.textContent = on ? "Video On" : "Video Off";
      caption.textContent = on ? `Visible context: ${objectName}` : "Audio/text conversation only.";
      wrapper.append(title, caption);
      preview.append(wrapper);
    }

    document.getElementById("lessonBtn").addEventListener("click", () => postJSON("/api/lesson", {}));
    document.getElementById("conversationBtn").addEventListener("click", () => postJSON("/api/conversation", {
      turns: Number(document.getElementById("turns").value || 4),
      video: videoEl.value,
      object: objectEl.value
    }));
    videoEl.addEventListener("change", updateVideoPreview);
    objectEl.addEventListener("input", updateVideoPreview);
    updateVideoPreview();
    loadStatus();
  </script>
</body>
</html>
"""


class FluentAIHandler(BaseHTTPRequestHandler):
    state_path = DEFAULT_PROGRESS_PATH
    language = "Spanish"
    renderer_path = Path(__file__).resolve().parent.parent / "desktop" / "electron" / "renderer.html"

    def do_GET(self) -> None:
        if self.path == "/":
            self._send_text(self._renderer_html(), "text/html")
            return
        if self.path == "/api/status":
            provider = OpenAIProvider()
            state = load_state(self.state_path, self.language)
            status = f"{provider.status()} Level {state['learner']['current_level']}; weak topics: {', '.join(state.get('weak_topics', []))}."
            self._send_json({"status": status})
            return
        if self.path == "/api/progress":
            self._send_json(load_state(self.state_path, self.language))
            return
        self.send_error(404)

    def do_POST(self) -> None:
        body = self._read_json()
        if self.path.startswith("/api/bridge/"):
            command = self.path.rsplit("/", 1)[-1]
            self._send_json(self._run_bridge_command(command, body))
            return
        if self.path == "/api/lesson":
            self._send_json({"text": run_lesson_cycle(self.state_path, self.language)})
            return
        if self.path == "/api/conversation":
            turns = _bounded_int(body.get("turns", 4), 2, 8, 4)
            video_on = body.get("video", "off") == "on"
            video_object = str(body.get("object") or "").strip() or None
            self._send_json({"text": run_conversation_cycle(self.state_path, self.language, turns, video_on, video_object)})
            return
        self.send_error(404)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _renderer_html(self) -> str:
        try:
            return self.renderer_path.read_text(encoding="utf-8")
        except OSError:
            return HTML

    def _run_bridge_command(self, command: str, body: dict[str, Any]) -> dict[str, Any]:
        handler = BRIDGE_COMMANDS.get(command)
        if handler is None:
            return {"ok": False, "error": f"Unknown command: {command}"}
        payload = {
            **body,
            "state_path": str(self.state_path),
            "language": body.get("language") or self.language,
        }
        try:
            return handler(payload)
        except Exception as exc:  # pragma: no cover - defensive web boundary.
            return {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}

    def _read_json(self) -> dict[str, Any]:
        length = _bounded_int(self.headers.get("content-length", "0"), 0, MAX_JSON_BYTES, 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    def _send_json(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_text(self, payload: str, content_type: str) -> None:
        data = payload.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _bounded_int(value: Any, low: int, high: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(high, parsed))


def run_lesson_cycle(state_path: Path, language: str) -> str:
    state = load_state(state_path, language)
    provider = OpenAIProvider()
    before = snapshot_progress(state)
    lesson = generate_lesson(state)
    source = "local deterministic fallback"
    if provider.available:
        enhanced = provider.enhance_lesson(state, lesson)
        if enhanced.get("source") == "openai":
            lesson = enhanced
            source = f"OpenAI Responses API ({provider.model})"
        elif provider.last_error:
            source = f"local fallback after OpenAI issue: {provider.last_error}"

    quiz = generate_quiz(state, lesson)
    answers = answer_quiz(quiz, state, "auto")
    results = evaluate_answers(quiz, answers)
    update_progress(state, lesson, results)
    save_state(state_path, state)

    lines = [
        f"[OpenAI Model Agent] Source: {source}",
        f"[Lesson Generator Agent] {lesson['level']} lesson on {lesson['topic']}",
        "",
        "Vocabulary:",
    ]
    lines.extend(f"- {word}: {meaning}" for word, meaning in lesson["vocabulary"])
    lines.extend(["", f"Grammar: {lesson['grammar_explanation']}", "", "Examples:"])
    lines.extend(f"- {source_text} = {meaning}" for source_text, meaning in lesson["examples"])
    lines.extend(["", "Quiz feedback:"])
    for index, result in enumerate(results, start=1):
        status = "correct" if result.correct else "review"
        lines.append(f"{index}. {status}: {result.feedback}")
    lines.extend(["", f"[Progress Reporter Agent] {progress_report(before, state)}"])
    return "\n".join(lines)


def run_conversation_cycle(state_path: Path, language: str, turns: int, video_on: bool, video_object: str | None) -> str:
    state = load_state(state_path, language)
    provider = OpenAIProvider()
    transcript, state, topic = run_conversation(
        state=state,
        turns=max(2, min(8, turns)),
        mode="auto",
        video_on=video_on,
        video_object=video_object,
        tutor_reply_fn=provider.conversation_tutor_reply if provider.available else None,
    )
    save_state(state_path, state)

    source = f"OpenAI Responses API ({provider.model})" if provider.available and not provider.last_error else "local deterministic fallback"
    if provider.last_error:
        source = f"local fallback after OpenAI issue: {provider.last_error}"
    lines = [
        f"[OpenAI Model Agent] Source: {source}",
        f"[Speaking Tutor Agent] AI initiated topic: {topic['topic']} ({topic['complexity']})",
        f"[Vision Context Agent] Video {'on' if video_on else 'off'}" + (f"; visible object: {video_object}" if video_on and video_object else ""),
        "",
    ]
    for turn in transcript:
        lines.append(f"Turn {turn.turn_number}")
        lines.append(f"Tutor: {turn.tutor_text}")
        lines.append(f"Learner: {turn.learner_text}")
        lines.append(f"Feedback: {turn.feedback}")
        if turn.correction:
            lines.append(f"Model phrase: {turn.correction}")
        lines.append("")
    lines.append(f"[Memory Agent] Next speaking goal: {state['conversation_memory']['next_speaking_goal']}")
    return "\n".join(lines)


def run_server(host: str, port: int, state_path: Path, language: str) -> None:
    FluentAIHandler.state_path = state_path
    FluentAIHandler.language = language
    server = ThreadingHTTPServer((host, port), FluentAIHandler)
    print(f"FluentAI web app running at http://{host}:{port}")
    server.serve_forever()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the FluentAI local web app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--state-path", type=Path, default=DEFAULT_PROGRESS_PATH)
    parser.add_argument("--language", default="Spanish")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    run_server(args.host, args.port, args.state_path, args.language)


if __name__ == "__main__":
    main()
