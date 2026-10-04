import json
import re
import socket
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fluent_ai import web
from fluent_ai.desktop_bridge import COMMANDS as BRIDGE_COMMANDS
from fluent_ai.state import default_state, save_state
from fluent_ai.web import FluentAIHandler, FluentAIServer, ThreadingHTTPServer

TOKEN_RE = re.compile(r'<meta name="fluentai-api-token" content="([A-Za-z0-9_-]+)">')
# 60,007 bytes: under the size cap but deep enough to exhaust json's recursion.
DEEP_JSON = b'{"a":' + b"[" * 30000 + b"0" + b"]" * 30000 + b"}"
ONBOARDING = {
    "display_name": "Johan",
    "language": "Spanish",
    "motivation": "Travel",
    "goals": ["Hold a 5-minute conversation"],
    "self_reported_level": "A1",
    "speaking_comfort": "some",
    "session_minutes": 10,
    "voice_default": "openai",
    "video_default": "off",
    "privacy_local_only": True,
}


class FakeOpenAIProvider:
    model = "test-model"
    last_error = None
    available = True
    api_key = None

    def status(self):
        return "OpenAI enabled: model test-model."

    def enhance_lesson(self, state, lesson):
        enhanced = lesson.copy()
        enhanced["source"] = "openai"
        return enhanced

    def conversation_tutor_reply(self, topic, state, transcript, phase, fallback):
        return fallback


class Response:
    def __init__(self, raw: bytes):
        head, _, self.body = raw.partition(b"\r\n\r\n")
        lines = head.decode("iso-8859-1").split("\r\n")
        self.status = int(lines[0].split()[1])
        self.headers = {}
        for line in lines[1:]:
            name, _, value = line.partition(":")
            self.headers[name.strip().lower()] = value.strip()

    def json(self):
        return json.loads(self.body.decode("utf-8"))

    @property
    def text(self):
        return self.body.decode("utf-8")


class WebServerMixin:
    @contextmanager
    def serve(self, state_path, handler=FluentAIHandler, server_class=FluentAIServer):
        handler.state_path = state_path
        handler.language = "Spanish"
        try:
            server = server_class(("127.0.0.1", 0), handler)
        except PermissionError as exc:
            self.skipTest(f"Local socket bind is unavailable in this sandbox: {exc}")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server, server.server_address[1]
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def raw(self, port, method, path, headers=(), body=None, host=True, length=True):
        """Send an exact HTTP/1.1 request so tests control every header."""
        lines = [f"{method} {path} HTTP/1.1"]
        if host:
            lines.append(f"Host: 127.0.0.1:{port}")
        lines.extend(f"{name}: {value}" for name, value in headers)
        if body is not None and length:
            lines.append(f"Content-Length: {len(body)}")
        lines.append("Connection: close")
        data = ("\r\n".join(lines) + "\r\n\r\n").encode("iso-8859-1") + (body or b"")
        with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
            sock.sendall(data)
            chunks = []
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        return Response(b"".join(chunks))

    def token(self, port):
        page = self.raw(port, "GET", "/")
        self.assertEqual(page.status, 200)
        return TOKEN_RE.search(page.text).group(1)

    def post(self, port, path, payload, token, headers=()):
        all_headers = [("Content-Type", "application/json"), ("X-FluentAI-Token", token), *headers]
        return self.raw(port, "POST", path, all_headers, json.dumps(payload).encode("utf-8"))

    def json_post(self, port, path, payload, token, headers=()):
        response = self.post(port, path, payload, token, headers)
        self.assertEqual(response.status, 200, response.text)
        return response.json()


class WebSmokeTests(WebServerMixin, unittest.TestCase):
    def test_web_status_lesson_and_conversation_endpoints(self):
        with TemporaryDirectory() as tmpdir, patch("fluent_ai.web.OpenAIProvider", FakeOpenAIProvider):
            with self.serve(Path(tmpdir) / "progress.json") as (_, port):
                token = self.token(port)
                status = self.raw(port, "GET", "/api/status", [("X-FluentAI-Token", token)])
                self.assertEqual(status.status, 200)
                self.assertIn("status", status.json())
                lesson = self.json_post(port, "/api/lesson", {}, token)
                self.assertIn("Lesson Generator Agent", lesson["text"])
                conversation = self.json_post(port, "/api/conversation", {"turns": 2, "video": "on", "object": "apple"}, token)
                self.assertIn("manzana", conversation["text"])
                self.assertIn("Post-call summary", conversation["text"])

    def test_web_bridge_routes_onboarding_and_placement_commands(self):
        with TemporaryDirectory() as tmpdir, patch("fluent_ai.web.OpenAIProvider", FakeOpenAIProvider):
            state_path = Path(tmpdir) / "progress.json"
            with self.serve(state_path) as (_, port):
                token = self.token(port)
                status = self.json_post(port, "/api/bridge/onboarding_status", {}, token)
                self.assertTrue(status["ok"])
                self.assertTrue(status["requires_onboarding"])
                self.assertFalse(state_path.exists())

                submitted = self.json_post(port, "/api/bridge/onboarding_submit", ONBOARDING, token)
                self.assertTrue(submitted["ok"])

                placement = self.json_post(
                    port,
                    "/api/bridge/placement_start",
                    {"language": "Spanish", "include_written": True, "include_conversation": True},
                    token,
                )
                self.assertTrue(placement["ok"])
                self.assertIn("session", placement)
                self.assertGreaterEqual(len(placement["session"]["items"]), 3)

    def test_web_bridge_routes_home_memory_commands(self):
        with TemporaryDirectory() as tmpdir, patch("fluent_ai.web.OpenAIProvider", FakeOpenAIProvider):
            with self.serve(Path(tmpdir) / "progress.json") as (_, port):
                token = self.token(port)
                self.assertTrue(self.json_post(port, "/api/bridge/onboarding_submit", ONBOARDING, token)["ok"])

                home = self.json_post(port, "/api/bridge/home_summary", {"language": "Spanish"}, token)
                self.assertTrue(home["ok"])
                self.assertIn("today", home)

                memory = self.json_post(port, "/api/bridge/memory_inspect", {"language": "Spanish"}, token)
                self.assertTrue(memory["ok"])
                self.assertIn("privacy", memory)

                exported = self.json_post(port, "/api/bridge/memory_export", {"language": "Spanish", "scope": "language"}, token)
                self.assertTrue(exported["ok"])
                self.assertIn("data", exported)

                reset = self.json_post(
                    port, "/api/bridge/memory_reset_language", {"language": "Spanish", "confirm": "RESET Spanish"}, token
                )
                self.assertTrue(reset["ok"])

                deleted = self.json_post(
                    port, "/api/bridge/memory_delete_all", {"language": "Spanish", "confirm": "DELETE ALL MEMORY"}, token
                )
                self.assertTrue(deleted["ok"])
                status = self.json_post(port, "/api/bridge/onboarding_status", {"language": "Spanish"}, token)
                self.assertTrue(status["requires_onboarding"])

    def test_web_root_serves_renderer_with_onboarding_overlay(self):
        with TemporaryDirectory() as tmpdir, patch("fluent_ai.web.OpenAIProvider", FakeOpenAIProvider):
            with self.serve(Path(tmpdir) / "progress.json") as (_, port):
                html = self.raw(port, "GET", "/").text
                self.assertIn('id="onboardingOverlay"', html)
                self.assertIn('id="placementStage"', html)
                self.assertIn("Start as beginner instead", html)
                self.assertIn("function initOnboarding", html)
                self.assertIn("onboardingStatus: (payload) => bridge(\"onboarding_status\", payload)", html)


class WebSecurityTests(WebServerMixin, unittest.TestCase):
    """Rejected requests must never reach state, bridge dispatch, or providers."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state_path = Path(self.tmp.name) / "progress.json"
        state = default_state("Spanish")
        state["learner"]["display_name"] = "Disposable Learner"
        save_state(self.state_path, state)
        self.reached = []

        def spy(name):
            def handler(payload):
                self.reached.append(name)
                return {"ok": True}
            return handler

        def counting(name):
            def fn(*args, **kwargs):
                self.reached.append(name)
                return {} if name == "load_state" else "ok"
            return fn

        test = self

        class CountingProvider(FakeOpenAIProvider):
            def __init__(self):
                test.reached.append("provider")

        for patcher in (
            patch.dict(web.BRIDGE_COMMANDS, {name: spy(name) for name in BRIDGE_COMMANDS}),
            patch("fluent_ai.web.OpenAIProvider", CountingProvider),
            patch("fluent_ai.desktop_bridge.OpenAIProvider", CountingProvider),
            patch("fluent_ai.web.load_state", counting("load_state")),
            patch("fluent_ai.web.run_lesson_cycle", counting("lesson")),
            patch("fluent_ai.web.run_conversation_cycle", counting("conversation")),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def snapshot(self):
        root = self.state_path.parent
        return {str(path.relative_to(root)): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}

    def post_routes(self):
        return [f"/api/bridge/{name}" for name in sorted(BRIDGE_COMMANDS)] + ["/api/lesson", "/api/conversation"]

    def assert_untouched(self, before):
        self.assertEqual(self.reached, [])
        self.assertEqual(self.snapshot(), before)

    def assert_rejected(self, response, status, code):
        self.assertEqual(response.status, status, response.text)
        payload = response.json()
        self.assertEqual(payload["ok"], False)
        self.assertEqual(payload["error_code"], code)
        self.assertNotIn("Traceback", response.text)
        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_cross_site_text_plain_delete_all_is_rejected_without_side_effects(self):
        before = self.snapshot()
        with self.serve(self.state_path) as (_, port):
            body = json.dumps({"confirm": "DELETE ALL MEMORY"}).encode()
            for headers in (
                # What a no-cors form/fetch from another site sends.
                [("Origin", "https://attacker.example"), ("Content-Type", "text/plain;charset=UTF-8"), ("Sec-Fetch-Site", "cross-site")],
                [("Origin", "https://attacker.example"), ("Content-Type", "text/plain")],
                [("Content-Type", "text/plain")],
            ):
                response = self.raw(port, "POST", "/api/bridge/memory_delete_all", headers, body)
                self.assertIn(response.status, (403,))
                self.assertFalse(response.json()["ok"])
        self.assert_untouched(before)

    def test_untrusted_callers_are_rejected_on_every_post_route_even_with_valid_token(self):
        before = self.snapshot()
        with self.serve(self.state_path) as (_, port):
            token = self.token(port)
            with self.serve(self.state_path) as (_, other_port):
                stale = self.token(other_port)
            self.assertNotEqual(token, stale)
            cases = [
                ([("Origin", "https://attacker.example")], token, 403, "invalid_origin"),
                ([("Origin", "null")], token, 403, "invalid_origin"),
                ([("Origin", f"http://127.0.0.1:{port + 1}")], token, 403, "invalid_origin"),
                ([("Origin", f"https://127.0.0.1:{port}")], token, 403, "invalid_origin"),
                ([("Origin", f"http://127.0.0.1:{port}/path")], token, 403, "invalid_origin"),
                ([("Origin", f"http://user@127.0.0.1:{port}")], token, 403, "invalid_origin"),
                ([("Origin", f"http://127.0.0.1:{port}"), ("Origin", "https://attacker.example")], token, 400, "duplicate_header"),
                ([("Sec-Fetch-Site", "cross-site")], token, 403, "invalid_origin"),
                ([("Sec-Fetch-Site", "same-site")], token, 403, "invalid_origin"),
                ([], "", 403, "invalid_token"),
                ([], "wrong-token", 403, "invalid_token"),
                ([], stale, 403, "invalid_token"),
                ([], token + "x", 403, "invalid_token"),
                ([("X-FluentAI-Token", token)], token, 400, "duplicate_header"),
            ]
            for route in self.post_routes():
                for headers, supplied, status, code in cases:
                    with self.subTest(route=route, headers=headers, token=supplied[:4]):
                        all_headers = [("Content-Type", "application/json"), *headers]
                        if supplied:
                            all_headers.append(("X-FluentAI-Token", supplied))
                        self.assert_rejected(self.raw(port, "POST", route, all_headers, b"{}"), status, code)
                with self.subTest(route=route, case="missing token header"):
                    response = self.raw(port, "POST", route, [("Content-Type", "application/json")], b"{}")
                    self.assert_rejected(response, 403, "invalid_token")
        self.assert_untouched(before)

    def test_dns_rebinding_and_invalid_host_are_rejected_before_html_or_api(self):
        before = self.snapshot()
        with self.serve(self.state_path) as (_, port):
            token = self.token(port)
            bad_hosts = [
                f"attacker.example:{port}",
                f"localhost.attacker.example:{port}",
                f"localhost.:{port}",
                f"127.0.0.2:{port}",
                f"127.0.0.1:{port + 1}",
                "127.0.0.1",
                f"user@127.0.0.1:{port}",
                f"0.0.0.0:{port}",
                "",
            ]
            for host in bad_hosts:
                origin = [("Origin", f"http://{host}")] if host else []
                with self.subTest(host=host, route="/"):
                    response = self.raw(port, "GET", "/", [("Host", host)], host=False)
                    self.assert_rejected(response, 421, "invalid_host")
                    self.assertNotIn(token, response.text)
                    self.assertNotIn("fluentai-api-token", response.text)
                for route in ["/api/status", "/api/progress", *self.post_routes()]:
                    with self.subTest(host=host, route=route):
                        headers = [("Host", host), *origin, ("Content-Type", "application/json"), ("X-FluentAI-Token", token)]
                        method = "GET" if route in ("/api/status", "/api/progress") else "POST"
                        response = self.raw(port, method, route, headers, b"{}" if method == "POST" else None, host=False)
                        self.assert_rejected(response, 421, "invalid_host")
            self.assert_rejected(self.raw(port, "GET", "/", host=False), 421, "invalid_host")
            duplicate = [("Host", f"127.0.0.1:{port}"), ("Host", f"attacker.example:{port}")]
            self.assert_rejected(self.raw(port, "GET", "/", duplicate, host=False), 400, "duplicate_header")
            absolute = self.raw(port, "POST", f"http://attacker.example/api/bridge/memory_delete_all",
                                [("Content-Type", "application/json"), ("X-FluentAI-Token", token)], b"{}")
            self.assertGreaterEqual(absolute.status, 400)
        self.assert_untouched(before)

    def test_invalid_bodies_are_rejected_before_dispatch(self):
        before = self.snapshot()
        with self.serve(self.state_path) as (_, port):
            token = self.token(port)
            auth = [("X-FluentAI-Token", token)]
            json_type = [("Content-Type", "application/json")]
            cases = [
                (json_type, b"{not json", 400, "invalid_json", True),
                (json_type, b"[]", 400, "invalid_json", True),
                (json_type, b'"text"', 400, "invalid_json", True),
                (json_type, b"null", 400, "invalid_json", True),
                (json_type, b'{"turns": NaN}', 400, "invalid_json", True),
                (json_type, b'{"name": "\xff\xfe"}', 400, "invalid_json", True),
                (json_type, b"", 400, "empty_body", True),
                (json_type, b"{}", 411, "length_required", False),
                ([("Content-Type", "text/plain")], b"{}", 415, "unsupported_media_type", True),
                ([("Content-Type", "application/x-www-form-urlencoded")], b"{}", 415, "unsupported_media_type", True),
                ([("Content-Type", "multipart/form-data; boundary=x")], b"{}", 415, "unsupported_media_type", True),
                ([("Content-Type", "application/json; charset=latin-1")], b"{}", 415, "unsupported_media_type", True),
                ([("Content-Type", "application/jsonx")], b"{}", 415, "unsupported_media_type", True),
                ([], b"{}", 415, "unsupported_media_type", True),
                ([*json_type, ("Content-Type", "application/json")], b"{}", 400, "duplicate_header", True),
                ([*json_type, ("Content-Length", "abc")], b"", 400, "invalid_content_length", False),
                ([*json_type, ("Content-Length", "-1")], b"", 400, "invalid_content_length", False),
                ([*json_type, ("Content-Length", "2"), ("Content-Length", "2")], b"{}", 400, "duplicate_header", False),
                ([*json_type, ("Content-Length", str(web.MAX_JSON_BYTES + 1))], b"", 413, "body_too_large", False),
                # Beyond Python's int() digit limit: must stay a bounded 413, not a crash.
                ([*json_type, ("Content-Length", "9" * 5000)], b"", 413, "body_too_large", False),
                ([*json_type, ("Content-Length", "\u00b2")], b"", 400, "invalid_content_length", False),
                (json_type, DEEP_JSON, 400, "invalid_json", True),
                (json_type, b'{"a":' + b"[" * 100 + b"0" + b"]" * 100 + b"}", 400, "invalid_json", True),
                ([*json_type, ("Transfer-Encoding", "chunked")], b"2\r\n{}\r\n0\r\n\r\n", 400, "unsupported_transfer_encoding", False),
            ]
            for route in self.post_routes():
                for headers, body, status, code, auto_length in cases:
                    with self.subTest(route=route, headers=headers, body=body[:12]):
                        response = self.raw(port, "POST", route, [*auth, *headers], body, length=auto_length)
                        self.assert_rejected(response, status, code)
        self.assert_untouched(before)

    def test_malformed_length_keeps_auth_and_host_rejection_status(self):
        before = self.snapshot()
        with self.serve(self.state_path) as (_, port):
            for length in ("9" * 5000, "\u00b2", "abc", str(web.MAX_JSON_BYTES + 1)):
                with self.subTest(length=length[:8]):
                    headers = [("Content-Type", "text/plain"), ("Content-Length", length)]
                    response = self.raw(port, "POST", "/api/bridge/memory_delete_all", headers, b"", length=False)
                    self.assert_rejected(response, 403, "invalid_token")
                    rebind = [("Host", f"attacker.example:{port}"), *headers]
                    response = self.raw(port, "POST", "/api/bridge/memory_delete_all", rebind, b"", host=False, length=False)
                    self.assert_rejected(response, 421, "invalid_host")
            # A small unauthenticated body is drained, so the client still reads the 403.
            response = self.raw(port, "POST", "/api/bridge/memory_delete_all", [("Content-Type", "text/plain")], b"x" * 4096)
            self.assert_rejected(response, 403, "invalid_token")
        self.assert_untouched(before)

    def test_content_length_parser_is_bounded_ascii(self):
        self.assertEqual(web._parse_content_length("2"), 2)
        self.assertEqual(web._parse_content_length(" 0002\t"), 2)
        self.assertEqual(web._parse_content_length("9" * 5000), web.MAX_JSON_BYTES + 1)
        self.assertEqual(web._parse_content_length("0" * 5000 + "2"), 2)
        for bad in ("", " ", "-1", "+1", "1.0", "1e3", "\u00b2", "\u0662", "\uff11", "1 2"):
            with self.subTest(bad=bad):
                self.assertIsNone(web._parse_content_length(bad))

    def test_api_reads_require_token_and_do_not_touch_state_when_rejected(self):
        self.state_path.unlink()
        with self.serve(self.state_path) as (_, port):
            token = self.token(port)
            for route in ("/api/status", "/api/progress"):
                with self.subTest(route=route):
                    self.assert_rejected(self.raw(port, "GET", route), 403, "invalid_token")
                    self.assert_rejected(
                        self.raw(port, "GET", route, [("X-FluentAI-Token", token), ("Origin", "https://attacker.example")]),
                        403,
                        "invalid_origin",
                    )
            self.assertEqual(self.reached, [])
            self.assertFalse(self.state_path.exists())
            ok = self.raw(port, "GET", "/api/progress", [("X-FluentAI-Token", token), ("Sec-Fetch-Site", "same-origin")])
            self.assertEqual(ok.status, 200)
            self.assertEqual(ok.headers["cache-control"], "no-store")
            self.assertEqual(self.reached, ["load_state"])

    def test_unknown_routes_and_methods_do_not_bypass_guards(self):
        before = self.snapshot()
        with self.serve(self.state_path) as (_, port):
            token = self.token(port)
            auth = [("Content-Type", "application/json"), ("X-FluentAI-Token", token)]
            for route in ("/api/bridge/nope", "/api/bridge/x/memory_delete_all", "/api/bridge/MEMORY_DELETE_ALL", "/api/other"):
                with self.subTest(route=route):
                    self.assertEqual(self.raw(port, "POST", route, auth, b"{}").status, 404)
                    self.assertEqual(self.raw(port, "POST", route, [("Content-Type", "text/plain")], b"{}").status, 403)
            preflight = self.raw(
                port,
                "OPTIONS",
                "/api/bridge/memory_delete_all",
                [("Origin", "https://attacker.example"), ("Access-Control-Request-Method", "POST"),
                 ("Access-Control-Request-Headers", "content-type,x-fluentai-token")],
            )
            self.assert_rejected(preflight, 405, "method_not_allowed")
            for method in ("PUT", "DELETE", "PATCH"):
                self.assertEqual(self.raw(port, method, "/api/bridge/memory_delete_all", auth, b"{}").status, 405)
        self.assert_untouched(before)

    def test_token_bootstrap_is_per_launch_no_store_and_not_frameable(self):
        with self.serve(self.state_path) as (server, port):
            page = self.raw(port, "GET", "/")
            first = TOKEN_RE.search(page.text).group(1)
            self.assertEqual(first, server.api_token)
            self.assertGreaterEqual(len(first), 40)
            self.assertEqual(page.headers["cache-control"], "no-store")
            self.assertEqual(page.headers["x-frame-options"], "DENY")
            self.assertIn("frame-ancestors 'none'", page.headers["content-security-policy"])
            self.assertEqual(TOKEN_RE.search(self.raw(port, "GET", "/").text).group(1), first, "refresh keeps launch token")
            localhost = self.raw(port, "GET", "/", [("Host", f"localhost:{port}")], host=False)
            self.assertEqual(localhost.status, 200)
        with self.serve(self.state_path) as (_, port):
            self.assertNotEqual(self.token(port), first)
        self.assertNotIn(first, self.state_path.read_text())

    def test_plain_server_without_launch_token_fails_closed(self):
        before = self.snapshot()
        with self.serve(self.state_path, server_class=ThreadingHTTPServer) as (_, port):
            page = self.raw(port, "GET", "/")
            self.assertGreaterEqual(page.status, 400)
            response = self.raw(port, "POST", "/api/bridge/memory_delete_all",
                                [("Content-Type", "application/json"), ("X-FluentAI-Token", "")], b"{}")
            self.assertGreaterEqual(response.status, 400)
        self.assert_untouched(before)

    def test_server_refuses_non_loopback_binds(self):
        for host in ("0.0.0.0", "192.168.1.10", "::"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                FluentAIServer((host, 0), FluentAIHandler)
        with self.assertRaises(SystemExit), patch("sys.stderr"):
            web.build_parser().parse_args(["--host", "0.0.0.0"])


class WebAuthorizedClientTests(WebServerMixin, unittest.TestCase):
    def test_browser_shaped_and_originless_token_requests_persist_disposable_state(self):
        with TemporaryDirectory() as tmpdir, patch("fluent_ai.web.OpenAIProvider", FakeOpenAIProvider), \
                patch("fluent_ai.desktop_bridge.OpenAIProvider", FakeOpenAIProvider):
            state_path = Path(tmpdir) / "progress.json"
            with self.serve(state_path) as (_, port):
                token = self.token(port)
                browser = [
                    ("Host", f"localhost:{port}"),
                    ("Origin", f"http://localhost:{port}"),
                    ("Sec-Fetch-Site", "same-origin"),
                    ("Content-Type", "application/json; charset=UTF-8"),
                    ("X-FluentAI-Token", token),
                ]
                response = self.raw(port, "POST", "/api/bridge/onboarding_submit", browser,
                                    json.dumps(ONBOARDING).encode(), host=False)
                self.assertEqual(response.status, 200, response.text)
                self.assertTrue(response.json()["ok"])
                self.assertEqual(response.headers["cache-control"], "no-store")
                saved = json.loads(state_path.read_text())
                self.assertEqual(saved["learner"]["display_name"], "Johan")
                self.assertNotIn(token, state_path.read_text())

                # Local automation without Origin still works with Host + token.
                status = self.json_post(port, "/api/bridge/status", {}, token)
                self.assertTrue(status["ok"])
                # Every bridge command is reachable for an authorized caller (routing smoke).
                for command in sorted(BRIDGE_COMMANDS):
                    if command in ("memory_delete_all", "memory_reset_language"):
                        continue
                    with self.subTest(command=command):
                        self.assertEqual(self.post(port, f"/api/bridge/{command}", {"language": "Spanish"}, token).status, 200)
                self.assertTrue(json.loads(state_path.read_text())["learner"]["display_name"])


if __name__ == "__main__":
    unittest.main()
