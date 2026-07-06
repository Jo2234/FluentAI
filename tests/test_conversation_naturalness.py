import json
import unittest
from unittest.mock import patch

from fluent_ai.conversation import asks_for_english_help, build_follow_up
from fluent_ai.openai_provider import OpenAIProvider, _realtime_turn_detection
from fluent_ai.state import conversation_memory, default_state, profile_state


class FakeHTTPResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps({"value": "secret-test", "expires_at": 999}).encode("utf-8")


class NaturalConversationTests(unittest.TestCase):
    def test_realtime_session_waits_for_real_silence_and_does_not_interrupt(self):
        captured = {}

        def fake_urlopen(request, timeout=20, context=None):
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["context"] = context
            return FakeHTTPResponse()

        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=False), patch(
            "urllib.request.urlopen", fake_urlopen
        ):
            result = OpenAIProvider().realtime_client_secret(default_state("Spanish"))

        self.assertTrue(result["ok"])
        self.assertIsNotNone(captured["context"])
        turn_detection = captured["payload"]["session"]["audio"]["input"]["turn_detection"]
        self.assertGreaterEqual(turn_detection["silence_duration_ms"], 2200)
        self.assertFalse(turn_detection["interrupt_response"])
        self.assertTrue(turn_detection["create_response"])

        instructions = captured["payload"]["session"]["instructions"].lower()
        self.assertIn("do not interrupt", instructions)
        self.assertIn("2.5 seconds", instructions)
        self.assertIn("short check-in", instructions)
        self.assertIn("english", instructions)

    def test_english_help_covers_common_confusion_phrases(self):
        state = default_state("Spanish")
        topic = {
            "topic": "weather",
            "complexity": "beginner",
            "support": "Model answer: Hace sol.",
            "keywords": ["hace", "sol"],
        }

        for phrase in ["Sorry, what was that?", "No entiendo", "¿Qué significa eso?", "Can you repeat that?"]:
            self.assertTrue(asks_for_english_help(phrase), phrase)

        follow_up = build_follow_up(topic, "Sorry, what was that?", 0.2, 1, state)
        self.assertIn("In English", follow_up)
        self.assertIn("Hace sol", follow_up)

    def test_turn_detection_env_overrides_are_bounded(self):
        with patch.dict("os.environ", {"OPENAI_REALTIME_SILENCE_MS": "100", "OPENAI_REALTIME_IDLE_PROMPT_MS": "99999"}):
            config = _realtime_turn_detection()

        self.assertEqual(config["silence_duration_ms"], 1400)
        self.assertEqual(config["idle_timeout_ms"], 11000)

    def test_turn_detection_is_dynamic_for_confident_advanced_learners(self):
        beginner = default_state("Spanish")
        advanced = default_state("Spanish")
        profile_state(advanced)["current_level"] = "C1"
        conversation_memory(advanced)["speaking_confidence"] = 0.82

        self.assertGreater(
            _realtime_turn_detection(beginner)["silence_duration_ms"],
            _realtime_turn_detection(advanced)["silence_duration_ms"],
        )


if __name__ == "__main__":
    unittest.main()
