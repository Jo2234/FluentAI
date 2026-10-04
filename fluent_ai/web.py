from __future__ import annotations

import argparse
import hmac
import html
import json
import re
import secrets
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from fluent_ai.agent import answer_quiz, evaluate_answers, generate_lesson, generate_quiz, progress_report, snapshot_progress, update_progress
from fluent_ai.app import DEFAULT_PROGRESS_PATH
from fluent_ai.conversation import persist_post_call_summary, run_conversation, update_conversation_progress
from fluent_ai.desktop_bridge import COMMANDS as BRIDGE_COMMANDS
from fluent_ai.desktop_bridge import profile_for
from fluent_ai.openai_provider import OpenAIProvider
from fluent_ai.state import state_transaction, active_language, conversation_memory, load_state


MAX_JSON_BYTES = 64_000
MAX_JSON_DEPTH = 64
# The browser UI is served only to loopback clients. These names are matched
# exactly (with the listening port), so attacker DNS names that rebind to
# 127.0.0.1 are rejected by Host even when Origin matches that Host.
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]")
LOOPBACK_BIND_HOSTS = ("127.0.0.1", "localhost", "::1")
TOKEN_HEADER = "X-FluentAI-Token"
TOKEN_META = "fluentai-api-token"
BRIDGE_PREFIX = "/api/bridge/"
COMMAND_RE = re.compile(r"[a-z_]{1,64}")
SAME_ORIGIN_FETCH_SITES = ("same-origin", "none")
NO_STORE_HEADERS = (
    ("Cache-Control", "no-store"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
)
# Pages carrying the API token must not be framed by another site (clickjacking).
HTML_HEADERS = (("X-Frame-Options", "DENY"), ("Content-Security-Policy", "frame-ancestors 'none'"))


class RequestRejected(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class FluentAIServer(ThreadingHTTPServer):
    """Loopback HTTP server with a fresh API token for each launch."""

    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], handler_class: type[BaseHTTPRequestHandler]) -> None:
        if server_address[0] not in LOOPBACK_BIND_HOSTS:
            raise ValueError(f"FluentAI web only binds to loopback hosts: {', '.join(LOOPBACK_BIND_HOSTS)}")
        if server_address[0] == "::1":
            self.address_family = socket.AF_INET6
        super().__init__(server_address, handler_class)
        self.api_token = secrets.token_urlsafe(32)
        port = self.server_address[1]
        authorities = {f"{host}:{port}" for host in LOOPBACK_HOSTS}
        if port == 80:
            authorities.update(LOOPBACK_HOSTS)
        self.allowed_authorities = frozenset(authorities)
        self.allowed_origins = frozenset(f"http://{authority}" for authority in authorities)


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

    const apiToken = document.querySelector('meta[name="fluentai-api-token"]')?.content || "";

    async function postJSON(url, body) {
      output.textContent = "Running agents...";
      const response = await fetch(url, {
        method: "POST",
        headers: {"Content-Type": "application/json", "X-FluentAI-Token": apiToken},
        body: JSON.stringify(body || {})
      });
      const data = await response.json();
      output.textContent = data.text || data.error || JSON.stringify(data, null, 2);
    }

    async function loadStatus() {
      const response = await fetch("/api/status", { headers: {"X-FluentAI-Token": apiToken} });
      const data = await response.json();
      statusEl.textContent = data.status || data.error;
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
    timeout = 30

    # Every request is checked in this order before any learner state is read,
    # any provider is constructed, or any bridge command runs:
    #   1. Host is an exact loopback authority on the listening port.
    #   2. API requests: Origin (if sent) is that same loopback origin, fetch
    #      metadata (if sent) is same-origin, and X-FluentAI-Token matches.
    #   3. POST bodies are application/json, bounded, UTF-8 JSON objects.
    def do_GET(self) -> None:
        try:
            path = self._checked_path()
            if path == "/":
                self._send_html(self._with_token(self._renderer_html()))
                return
            if path not in ("/api/status", "/api/progress"):
                raise RequestRejected(404, "not_found", "Not found.")
            self._check_api_caller()
        except RequestRejected as exc:
            self._send_rejection(exc)
            return
        if path == "/api/status":
            provider = OpenAIProvider()
            state = load_state(self.state_path, self.language)
            profile = profile_for(state, provider)
            status = f"{provider.status()} Level {profile['level']}; weak topics: {', '.join(profile['weak_topics'])}."
            self._send_json({"status": status})
            return
        self._send_json(load_state(self.state_path, self.language))

    def do_POST(self) -> None:
        self._body_consumed = False
        try:
            path = self._checked_path()
            self._check_api_caller()
            command = self._route_post(path)
            body = self._read_json()
        except RequestRejected as exc:
            self._send_rejection(exc)
            return
        if command is not None:
            self._send_json(self._run_bridge_command(command, body))
            return
        if path == "/api/lesson":
            self._send_json({"text": run_lesson_cycle(self.state_path, self.language)})
            return
        turns = _bounded_int(body.get("turns", 4), 2, 8, 4)
        video_on = body.get("video", "off") == "on"
        video_object = str(body.get("object") or "").strip() or None
        self._send_json({"text": run_conversation_cycle(self.state_path, self.language, turns, video_on, video_object)})

    def do_OPTIONS(self) -> None:
        # No CORS: preflights get no Access-Control-* grant.
        self._send_rejection(RequestRejected(405, "method_not_allowed", "Method not allowed."))

    do_PUT = do_PATCH = do_DELETE = do_OPTIONS

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _renderer_html(self) -> str:
        try:
            return self.renderer_path.read_text(encoding="utf-8")
        except OSError:
            return HTML

    def _with_token(self, page: str) -> str:
        meta = f'<meta name="{TOKEN_META}" content="{html.escape(self._server_token(), quote=True)}">'
        if "<head>" in page:
            return page.replace("<head>", f"<head>\n  {meta}", 1)
        return meta + page

    def _server_token(self) -> str:
        token = getattr(self.server, "api_token", None)
        if not isinstance(token, str) or not token:
            # Plain ThreadingHTTPServer instances have no token; fail closed.
            raise RequestRejected(500, "server_misconfigured", "Server has no API token; start it with FluentAIServer.")
        return token

    def _single_header(self, name: str) -> str | None:
        values = self.headers.get_all(name) or []
        if len(values) > 1:
            raise RequestRejected(400, "duplicate_header", f"Duplicate {name} header.")
        return values[0] if values else None

    def _checked_path(self) -> str:
        allowed = getattr(self.server, "allowed_authorities", frozenset())
        host = self._single_header("Host")
        if host is None or host.strip().lower() not in allowed:
            raise RequestRejected(421, "invalid_host", "Requests must address this app on a loopback host and port.")
        if not self.path.startswith("/") or self.path.startswith("//"):
            raise RequestRejected(400, "invalid_path", "Invalid request path.")
        return self.path.split("?", 1)[0]

    def _check_api_caller(self) -> None:
        origin = self._single_header("Origin")
        if origin is not None and origin.strip().lower() not in getattr(self.server, "allowed_origins", frozenset()):
            raise RequestRejected(403, "invalid_origin", "Cross-origin requests are not allowed.")
        fetch_site = self._single_header("Sec-Fetch-Site")
        if fetch_site is not None and fetch_site.strip().lower() not in SAME_ORIGIN_FETCH_SITES:
            raise RequestRejected(403, "invalid_origin", "Cross-site requests are not allowed.")
        expected = self._server_token()
        supplied = self._single_header(TOKEN_HEADER) or ""
        if not hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
            raise RequestRejected(403, "invalid_token", "Missing or stale app token. Reload the FluentAI page.")

    def _route_post(self, path: str) -> str | None:
        if path.startswith(BRIDGE_PREFIX):
            command = path[len(BRIDGE_PREFIX):]
            if not COMMAND_RE.fullmatch(command) or command not in BRIDGE_COMMANDS:
                raise RequestRejected(404, "unknown_command", f"Unknown command: {command[:64]}")
            return command
        if path in ("/api/lesson", "/api/conversation"):
            return None
        raise RequestRejected(404, "not_found", "Not found.")

    def _run_bridge_command(self, command: str, body: dict[str, Any]) -> dict[str, Any]:
        handler = BRIDGE_COMMANDS.get(command)
        if handler is None:
            return {"ok": False, "error": f"Unknown command: {command}"}
        payload = {**body, "state_path": str(self.state_path)}
        if "language" in body:
            payload["language"] = body.get("language")
        try:
            return handler(payload)
        except Exception as exc:  # pragma: no cover - defensive web boundary.
            return {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}

    def _read_json(self) -> dict[str, Any]:
        content_type = self._single_header("Content-Type")
        if not _is_json_media_type(content_type):
            raise RequestRejected(415, "unsupported_media_type", "Requests must use Content-Type: application/json.")
        if self._single_header("Transfer-Encoding") is not None:
            raise RequestRejected(400, "unsupported_transfer_encoding", "Transfer-Encoding is not supported; send Content-Length.")
        raw_length = self._single_header("Content-Length")
        if raw_length is None:
            raise RequestRejected(411, "length_required", "Content-Length is required.")
        length = _parse_content_length(raw_length)
        if length is None:
            raise RequestRejected(400, "invalid_content_length", "Invalid Content-Length.")
        if length > MAX_JSON_BYTES:
            raise RequestRejected(413, "body_too_large", f"Request body exceeds {MAX_JSON_BYTES} bytes.")
        if length == 0:
            raise RequestRejected(400, "empty_body", "Request body must be a JSON object; send {} for no options.")
        raw = self.rfile.read(length)
        self._body_consumed = True
        if len(raw) != length:
            raise RequestRejected(400, "incomplete_body", "Request body ended before Content-Length.")
        try:
            value = json.loads(raw.decode("utf-8"), parse_constant=_reject_json_constant)
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise RequestRejected(400, "invalid_json", "Request body must be valid UTF-8 JSON.") from None
        if not isinstance(value, dict):
            raise RequestRejected(400, "invalid_json", "Request body must be a JSON object.")
        if _json_depth(value) > MAX_JSON_DEPTH:
            raise RequestRejected(400, "invalid_json", f"JSON nesting exceeds {MAX_JSON_DEPTH} levels.")
        return value

    def _send_rejection(self, exc: RequestRejected) -> None:
        # Unread request bodies must not be parsed as a follow-up request.
        self.close_connection = True
        self._discard_small_body()
        self._send_json({"ok": False, "error": exc.message, "error_code": exc.code}, status=exc.status)

    def _discard_small_body(self) -> None:
        # Drain (never parse) a bounded body so closing the socket does not
        # reset the connection before the client reads the JSON error.
        # Malformed or oversized lengths are not drained; the connection closes
        # and the original rejection status is still sent.
        if self.command != "POST" or getattr(self, "_body_consumed", False) or "Transfer-Encoding" in self.headers:
            return
        lengths = self.headers.get_all("Content-Length") or []
        length = _parse_content_length(lengths[0]) if len(lengths) == 1 else None
        if length is None or length > MAX_JSON_BYTES:
            return
        try:
            self.rfile.read(length)
        except OSError:
            pass

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        self._send_bytes(json.dumps(payload).encode("utf-8"), "application/json", status)

    def _send_html(self, payload: str) -> None:
        self._send_bytes(payload.encode("utf-8"), "text/html; charset=utf-8", 200, HTML_HEADERS)

    def _send_bytes(self, data: bytes, content_type: str, status: int, extra: tuple[tuple[str, str], ...] = ()) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        for name, value in NO_STORE_HEADERS + extra:
            self.send_header(name, value)
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)


def _is_json_media_type(value: str | None) -> bool:
    if value is None:
        return False
    media_type, *params = (part.strip() for part in value.split(";"))
    if media_type.lower() != "application/json":
        return False
    for param in params:
        name, _, param_value = param.partition("=")
        if name.strip().lower() != "charset" or param_value.strip().strip('"').lower() not in ("utf-8", "utf8"):
            return False
    return True


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"Unsupported JSON constant: {value}")


def _parse_content_length(value: str) -> int | None:
    """ASCII decimal Content-Length; None if malformed, MAX_JSON_BYTES + 1 if too large.

    Never converts unbounded digit strings to int (Python caps int() digits).
    """
    digits = value.strip(" \t")
    if not digits or not digits.isascii() or not digits.isdigit():
        return None
    digits = digits.lstrip("0") or "0"
    if len(digits) > len(str(MAX_JSON_BYTES)):
        return MAX_JSON_BYTES + 1
    return min(int(digits), MAX_JSON_BYTES + 1)


def _json_depth(value: Any) -> int:
    deepest = 0
    stack = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if isinstance(item, dict):
            children = item.values()
        elif isinstance(item, list):
            children = item
        else:
            continue
        deepest = max(deepest, depth)
        if deepest > MAX_JSON_DEPTH:
            return deepest
        stack.extend((child, depth + 1) for child in children)
    return deepest


def _bounded_int(value: Any, low: int, high: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(high, parsed))


def run_lesson_cycle(state_path: Path, language: str) -> str:
    state = load_state(state_path, language)
    provider = OpenAIProvider()
    if not provider.available:
        return f"[OpenAI Model Agent] {provider.status()}\n[Orchestrator] Add OPENAI_API_KEY to .env before running Lesson Mode."

    lesson = generate_lesson(state)
    enhanced = provider.enhance_lesson(state, lesson)
    if enhanced.get("source") != "openai":
        return f"[OpenAI Model Agent] OpenAI lesson generation failed: {provider.last_error or 'empty model response'}"
    lesson = enhanced
    source = f"OpenAI Responses API ({provider.model})"

    quiz = generate_quiz(state, lesson)
    answers = answer_quiz(quiz, state, "auto")
    results = evaluate_answers(quiz, answers)
    with state_transaction(state_path, active_language(state), generation=state["memory_generation"]) as state:
        before = snapshot_progress(state)
        update_progress(state, lesson, results)

    lines = [
        f"[OpenAI Model Agent] Source: {source}",
        f"[Lesson Generator Agent] {lesson['level']} lesson on {lesson['topic']}",
        f"[Curriculum Agent] Selected {lesson['topic']}: {lesson.get('reason', 'Lesson selected for current progress.')}",
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
    if not provider.available:
        return f"[OpenAI Model Agent] {provider.status()}\n[Orchestrator] Add OPENAI_API_KEY to .env before running Conversation Mode."

    try:
        transcript, state, topic = run_conversation(
            state=state,
            turns=max(2, min(8, turns)),
            mode="auto",
            video_on=video_on,
            video_object=video_object,
            tutor_reply_fn=provider.conversation_tutor_reply,
            conversation_grade_fn=getattr(provider, "evaluate_conversation_reply", None),
        )
    except Exception as exc:
        return f"[OpenAI Model Agent] OpenAI conversation generation failed: {exc.__class__.__name__}: {exc}"
    with state_transaction(state_path, active_language(state), generation=state["memory_generation"]) as state:
        update_conversation_progress(state, topic, transcript, video_on, video_object)
        summary = persist_post_call_summary(state, topic, transcript)

    source = f"OpenAI Responses API ({provider.model})"
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
    lines.append(f"[Memory Agent] Next speaking goal: {conversation_memory(state)['next_speaking_goal']}")
    if summary:
        lines.extend(
            [
                "",
                "Post-call summary:",
                f"- Did well: {summary['did_well']}",
                f"- Correction: {summary['correction_to_remember'] or 'None'}",
                f"- Phrase to review: {summary['phrase_to_review']}",
                f"- Next goal: {summary['next_speaking_goal']}",
            ]
        )
    return "\n".join(lines)


def run_server(host: str, port: int, state_path: Path, language: str) -> None:
    FluentAIHandler.state_path = state_path
    FluentAIHandler.language = language
    server = FluentAIServer((host, port), FluentAIHandler)
    url_host = "[::1]" if host == "::1" else host
    print(f"FluentAI web app running at http://{url_host}:{server.server_address[1]}")
    server.serve_forever()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the FluentAI local web app.")
    parser.add_argument("--host", default="127.0.0.1", choices=LOOPBACK_BIND_HOSTS, help="Loopback bind address.")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--state-path", type=Path, default=DEFAULT_PROGRESS_PATH)
    parser.add_argument("--language", default="Spanish")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    run_server(args.host, args.port, args.state_path, args.language)


if __name__ == "__main__":
    main()
