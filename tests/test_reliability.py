import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fluent_ai.conversation import build_follow_up
from fluent_ai.desktop_bridge import (
    MODEL_FAILURE_MESSAGE,
    call_checkpoint,
    call_checkpoint_discard,
    call_checkpoint_summarize,
    conversation_reply,
    lesson_checkpoint,
    lesson_checkpoint_discard,
    lesson_start,
    lesson_submit,
    session_checkpoints,
)
from fluent_ai.state import conversation_memory, default_state, load_state, save_state


class FakeOpenAIProvider:
    api_key = "sk-test"
    available = True
    model = "test-model"
    last_error = None

    def status(self):
        return "OpenAI enabled: model test-model."

    def enhance_lesson(self, state, lesson):
        enhanced = lesson.copy()
        enhanced["source"] = "openai"
        return enhanced

    def evaluate_quiz_answers(self, state, lesson, items):
        return None

    def conversation_tutor_reply(self, topic, state, transcript, phase, fallback):
        return fallback


class EmptyThenTextProvider(FakeOpenAIProvider):
    calls = 0

    def conversation_tutor_reply(self, topic, state, transcript, phase, fallback):
        type(self).calls += 1
        return "" if type(self).calls == 1 else "¿Qué comida te gusta?"


class EmptyTwiceProvider(FakeOpenAIProvider):
    calls = 0

    def conversation_tutor_reply(self, topic, state, transcript, phase, fallback):
        type(self).calls += 1
        return ""


class ModelFailureProvider(FakeOpenAIProvider):
    last_error = "TimeoutError: request timed out"

    def enhance_lesson(self, state, lesson):
        return lesson


def conversation_session():
    topic = {
        "topic": "likes and food",
        "complexity": "beginner",
        "support": "Model answer: Me gusta la pizza.",
        "keywords": ["gusta", "pizza"],
    }
    return {
        "topic": topic,
        "turns": [],
        "video_on": False,
        "video_object": None,
        "max_turns": 4,
    }


class ReliabilityTests(unittest.TestCase):
    def test_empty_tutor_response_retries_once_then_uses_text(self):
        EmptyThenTextProvider.calls = 0
        with TemporaryDirectory() as tmpdir, patch("fluent_ai.desktop_bridge.OpenAIProvider", EmptyThenTextProvider):
            result = conversation_reply(
                {
                    "state_path": str(Path(tmpdir) / "progress.json"),
                    "language": "Spanish",
                    "session": conversation_session(),
                    "message": "Me gusta la pizza.",
                    "tutor_message": "¿Qué comida te gusta?",
                }
            )

        self.assertTrue(result["ok"])
        self.assertEqual(EmptyThenTextProvider.calls, 2)
        self.assertEqual(result["tutor_message"], "¿Qué comida te gusta?")
        self.assertFalse(any("Used recovery prompt" in log for log in result["logs"]))

    def test_empty_tutor_response_twice_uses_recovery_prompt_and_logs(self):
        EmptyTwiceProvider.calls = 0
        with TemporaryDirectory() as tmpdir, patch("fluent_ai.desktop_bridge.OpenAIProvider", EmptyTwiceProvider):
            state_path = str(Path(tmpdir) / "progress.json")
            session = conversation_session()
            result = conversation_reply(
                {
                    "state_path": state_path,
                    "language": "Spanish",
                    "session": session,
                    "message": "No sé",
                    "tutor_message": "¿Qué comida te gusta?",
                }
            )

        self.assertTrue(result["ok"])
        self.assertEqual(EmptyTwiceProvider.calls, 2)
        expected = build_follow_up(session["topic"], "No sé", result["turn"]["score"], 1, default_state("Spanish"))
        self.assertEqual(result["tutor_message"], expected)
        self.assertIn("[Conversation Orchestrator] Used recovery prompt after empty model response.", result["logs"])

    def test_model_failure_with_key_uses_timeout_message_not_key_setup(self):
        with TemporaryDirectory() as tmpdir, patch("fluent_ai.desktop_bridge.OpenAIProvider", ModelFailureProvider):
            result = lesson_start({"state_path": str(Path(tmpdir) / "progress.json"), "language": "Spanish"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], MODEL_FAILURE_MESSAGE)
        self.assertNotIn("OPENAI_API_KEY", result["error"])

    def test_lesson_checkpoint_lifecycle_resume_submit_once_and_discard(self):
        with TemporaryDirectory() as tmpdir, patch("fluent_ai.desktop_bridge.OpenAIProvider", FakeOpenAIProvider):
            state_path = str(Path(tmpdir) / "progress.json")
            start = lesson_start({"state_path": state_path, "language": "Spanish"})
            checks = session_checkpoints({"state_path": state_path, "language": "Spanish"})
            self.assertTrue(checks["checkpoints"]["lesson"])

            answers = [question["answer"] for question in start["quiz"]]
            lesson_checkpoint(
                {
                    "state_path": state_path,
                    "language": "Spanish",
                    "lesson": start["lesson"],
                    "quiz": start["quiz"],
                    "answers": answers,
                }
            )
            resumed = session_checkpoints({"state_path": state_path, "language": "Spanish"})["checkpoints"]["lesson"]
            self.assertEqual(resumed["answers"], answers)

            result = lesson_submit(
                {
                    "state_path": state_path,
                    "language": "Spanish",
                    "lesson": resumed["lesson"],
                    "quiz": resumed["quiz"],
                    "answers": resumed["answers"],
                }
            )
            self.assertTrue(result["ok"])
            self.assertIsNone(session_checkpoints({"state_path": state_path})["checkpoints"]["lesson"])

            lesson_checkpoint(
                {
                    "state_path": state_path,
                    "language": "Spanish",
                    "lesson": start["lesson"],
                    "quiz": start["quiz"],
                    "answers": [],
                }
            )
            self.assertTrue(session_checkpoints({"state_path": state_path})["checkpoints"]["lesson"])
            lesson_checkpoint_discard({"state_path": state_path})
            self.assertIsNone(session_checkpoints({"state_path": state_path})["checkpoints"]["lesson"])

    def test_call_checkpoint_summarize_path_and_discard(self):
        with TemporaryDirectory() as tmpdir:
            state_path = str(Path(tmpdir) / "progress.json")
            save_state(Path(state_path), default_state("Spanish"))
            topic = conversation_session()["topic"]
            turn = {"tutor_text": "¿Qué comida te gusta?", "learner_text": "Me gusta la pizza."}

            call_checkpoint(
                {
                    "state_path": state_path,
                    "language": "Spanish",
                    "topic": topic,
                    "turns": [turn],
                    "video": "off",
                }
            )
            result = call_checkpoint_summarize({"state_path": state_path, "language": "Spanish"})
            persisted = load_state(Path(state_path), "Spanish")

            self.assertTrue(result["ok"])
            self.assertEqual(result["post_call_summary"]["topic"], "likes and food")
            self.assertEqual(len(conversation_memory(persisted)["post_call_summaries"]), 1)
            self.assertIsNone(session_checkpoints({"state_path": state_path})["checkpoints"]["call"])

            call_checkpoint({"state_path": state_path, "language": "Spanish", "topic": topic, "turns": [turn]})
            self.assertTrue(session_checkpoints({"state_path": state_path})["checkpoints"]["call"])
            call_checkpoint_discard({"state_path": state_path})
            self.assertIsNone(session_checkpoints({"state_path": state_path})["checkpoints"]["call"])

    def test_checkpoint_age_expiry_deletes_stale_checkpoint(self):
        with TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "progress.json"
            sessions = state_path.parent / "sessions"
            sessions.mkdir()
            stale = {
                "type": "lesson",
                "language": "Spanish",
                "lesson": {"topic": "weather"},
                "quiz": [],
                "answers": [],
                "created_at": (datetime.now(timezone.utc) - timedelta(hours=25)).replace(microsecond=0).isoformat(),
            }
            checkpoint_path = sessions / "current_lesson.json"
            checkpoint_path.write_text(json.dumps(stale), encoding="utf-8")

            result = session_checkpoints({"state_path": str(state_path), "language": "Spanish"})

            self.assertIsNone(result["checkpoints"]["lesson"])
            self.assertFalse(checkpoint_path.exists())


if __name__ == "__main__":
    unittest.main()
