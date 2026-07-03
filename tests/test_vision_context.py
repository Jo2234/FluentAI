import json
import unittest
from unittest.mock import patch

from fluent_ai.openai_provider import OpenAIProvider
from fluent_ai.state import default_state


class FakeHTTPResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(
            {
                "output_text": json.dumps(
                    {
                        "summary": "a pillow on a chair",
                        "primary_object": "pillow",
                        "spanish_prompt": "Veo una almohada. ¿De qué color es?",
                        "confidence": "high",
                    }
                )
            }
        ).encode("utf-8")


class VisionContextTests(unittest.TestCase):
    def test_vision_context_uses_fast_default_model_and_uncertainty_prompt(self):
        captured = {}

        def fake_urlopen(request, timeout=12):
            captured["timeout"] = timeout
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeHTTPResponse()

        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=False), patch(
            "urllib.request.urlopen", fake_urlopen
        ):
            result = OpenAIProvider().analyze_camera_frame(default_state("Spanish"), "data:image/jpeg;base64,abc")

        self.assertTrue(result["ok"])
        self.assertEqual(result["model"], "gpt-4.1-mini")
        self.assertEqual(result["primary_object"], "pillow")
        self.assertEqual(captured["timeout"], 12)
        prompt = captured["payload"]["input"][0]["content"][0]["text"].lower()
        self.assertIn("prefer being uncertain over being wrong", prompt)
        self.assertIn("if unclear", prompt)


if __name__ == "__main__":
    unittest.main()
