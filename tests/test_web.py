import json
import threading
import time
import unittest
import urllib.request
from tempfile import TemporaryDirectory
from pathlib import Path

from fluent_ai.web import FluentAIHandler, ThreadingHTTPServer


class WebSmokeTests(unittest.TestCase):
    def test_web_status_lesson_and_conversation_endpoints(self):
        with TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "progress.json"
            FluentAIHandler.state_path = state_path
            FluentAIHandler.language = "Spanish"
            server = ThreadingHTTPServer(("127.0.0.1", 0), FluentAIHandler)
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
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

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
