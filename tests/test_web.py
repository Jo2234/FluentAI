import json
import threading
import unittest
import urllib.request
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from fluent_ai.web import FluentAIHandler, ThreadingHTTPServer


class FakeOpenAIProvider:
    model = "test-model"
    last_error = None
    available = True

    def status(self):
        return "OpenAI enabled: model test-model."

    def enhance_lesson(self, state, lesson):
        enhanced = lesson.copy()
        enhanced["source"] = "openai"
        return enhanced

    def conversation_tutor_reply(self, topic, state, transcript, phase, fallback):
        return fallback


class WebSmokeTests(unittest.TestCase):
    def test_web_status_lesson_and_conversation_endpoints(self):
        with TemporaryDirectory() as tmpdir, patch("fluent_ai.web.OpenAIProvider", FakeOpenAIProvider):
            state_path = Path(tmpdir) / "progress.json"
            FluentAIHandler.state_path = state_path
            FluentAIHandler.language = "Spanish"
            server = self._start_server()
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                self.assertIn("FluentAI", self._get(f"http://127.0.0.1:{port}/"))
                status = self._json_get(f"http://127.0.0.1:{port}/api/status")
                self.assertIn("status", status)
                lesson = self._json_post(f"http://127.0.0.1:{port}/api/lesson", {})
                self.assertIn("Lesson Generator Agent", lesson["text"])
                conversation = self._json_post(
                    f"http://127.0.0.1:{port}/api/conversation",
                    {"turns": 2, "video": "on", "object": "apple"},
                )
                self.assertIn("manzana", conversation["text"])
                self.assertIn("Post-call summary", conversation["text"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_web_bridge_routes_onboarding_and_placement_commands(self):
        with TemporaryDirectory() as tmpdir, patch("fluent_ai.web.OpenAIProvider", FakeOpenAIProvider):
            state_path = Path(tmpdir) / "progress.json"
            FluentAIHandler.state_path = state_path
            FluentAIHandler.language = "Spanish"
            server = self._start_server()
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                status = self._json_post(f"http://127.0.0.1:{port}/api/bridge/onboarding_status", {})
                self.assertTrue(status["ok"])
                self.assertTrue(status["requires_onboarding"])
                self.assertFalse(state_path.exists())

                submitted = self._json_post(
                    f"http://127.0.0.1:{port}/api/bridge/onboarding_submit",
                    {
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
                    },
                )
                self.assertTrue(submitted["ok"])

                placement = self._json_post(
                    f"http://127.0.0.1:{port}/api/bridge/placement_start",
                    {"language": "Spanish", "include_written": True, "include_conversation": True},
                )
                self.assertTrue(placement["ok"])
                self.assertIn("session", placement)
                self.assertGreaterEqual(len(placement["session"]["items"]), 3)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def _start_server(self):
        try:
            return ThreadingHTTPServer(("127.0.0.1", 0), FluentAIHandler)
        except PermissionError as exc:
            self.skipTest(f"Local socket bind is unavailable in this sandbox: {exc}")

    def _get(self, url: str) -> str:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.read().decode("utf-8")

    def _json_get(self, url: str) -> dict:
        return json.loads(self._get(url))

    def _json_post(self, url: str, payload: dict) -> dict:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
