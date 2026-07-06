import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from fluent_ai.desktop_bridge import (
    home_summary,
    memory_delete_all,
    memory_export,
    memory_inspect,
    memory_reset_language,
)
from fluent_ai.state import (
    add_event,
    conversation_memory,
    default_state,
    language_state,
    load_state,
    profile_state,
    record_practice_session,
    save_state,
)
from fluent_ai.desktop_bridge import onboarding_status


PAST = "2000-01-01T00:00:00+00:00"


def save_temp_state(path: Path, state: dict) -> None:
    save_state(path, state)


class HomeMemoryBridgeTests(unittest.TestCase):
    def test_home_recommendation_priority(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "progress.json"

            state = default_state("Spanish")
            language_state(state)["review_queue"]["review_topic_past_tense"] = {
                "id": "review_topic_past_tense",
                "item_type": "topic",
                "target": "past tense",
                "topic": "past tense",
                "due_at": PAST,
                "source": "lesson",
            }
            save_temp_state(path, state)
            self.assertEqual(home_summary({"state_path": str(path), "language": "Spanish"})["today"]["kind"], "due_review")

            state = default_state("Spanish")
            language_state(state)["mistake_memory"]["m1"] = {
                "id": "m1",
                "incorrect_form": "yo habla",
                "corrected_form": "yo hablo",
                "skill": "conjugations",
                "topic": "conjugations",
                "frequency": 1,
                "next_review": PAST,
            }
            save_temp_state(path, state)
            self.assertEqual(home_summary({"state_path": str(path), "language": "Spanish"})["today"]["kind"], "due_mistake")

            state = default_state("Spanish")
            add_event(state, {"type": "lesson_completed", "summary": "Lesson done.", "payload": {"score": "4/6"}})
            save_temp_state(path, state)
            self.assertEqual(home_summary({"state_path": str(path), "language": "Spanish"})["today"]["kind"], "neglected_conversation")

            state = default_state("Spanish")
            conversation_memory(state)["sessions_completed"] = 1
            conversation_memory(state)["next_conversation_goal"] = {
                "source": "lesson",
                "topic": "past tense",
                "instruction": "Ask about yesterday.",
            }
            add_event(state, {"type": "conversation_started", "summary": "Started.", "payload": {"topic": "introductions"}})
            add_event(state, {"type": "lesson_completed", "summary": "Lesson done.", "payload": {"topic": "past tense", "score": "3/6"}})
            save_temp_state(path, state)
            self.assertEqual(home_summary({"state_path": str(path), "language": "Spanish"})["today"]["kind"], "lesson_goal_conversation")

            state = default_state("Spanish")
            language_state(state)["profile"]["first_practice_goal"] = "Build basic introductions."
            save_temp_state(path, state)
            self.assertEqual(home_summary({"state_path": str(path), "language": "Spanish"})["today"]["kind"], "first_practice_goal")

            state = default_state("Spanish")
            save_temp_state(path, state)
            self.assertEqual(home_summary({"state_path": str(path), "language": "Spanish"})["today"]["kind"], "fresh_lesson")

    def test_memory_inspect_sanitizes_secrets_images_and_transcripts(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "progress.json"
            state = default_state("Spanish")
            state["learner"]["motivation"] = "Use sk-testsecret123456789 in a note"
            memory = conversation_memory(state)
            memory["last_video_context"]["summary"] = "data:image/png;base64,AAAA"
            memory["last_video_context"]["primary_object"] = "client_secret=supersecretvalue"
            memory["post_call_summaries"].append(
                {"topic": "introductions", "summary": "safe", "raw_transcript": "full transcript sk-hidden123456"}
            )
            save_temp_state(path, state)

            result = memory_inspect({"state_path": str(path), "language": "Spanish"})
            payload = json.dumps(result)

            self.assertTrue(result["ok"])
            self.assertNotIn("sk-testsecret", payload)
            self.assertNotIn("data:image", payload)
            self.assertNotIn("raw_transcript", payload)
            self.assertNotIn("full transcript", payload)
            self.assertIn("[redacted", payload)

    def test_memory_export_updates_privacy_and_uses_sanitized_payload(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "progress.json"
            state = default_state("Spanish")
            state["learner"]["motivation"] = "sk-secret987654321"
            save_temp_state(path, state)

            result = memory_export({"state_path": str(path), "language": "Spanish", "scope": "language"})
            saved = load_state(path, "Spanish")

            self.assertTrue(result["ok"])
            self.assertTrue(result["filename"].startswith("fluentai-memory-"))
            self.assertIsNotNone(saved["privacy"]["last_exported_at"])
            self.assertNotIn("sk-secret", json.dumps(result["data"]))

    def test_reset_language_preserves_other_language_and_top_level_memory(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "progress.json"
            state = default_state("Spanish")
            state["learner"]["onboarded_at"] = "2026-07-08T00:00:00+00:00"
            state["preferences"]["lesson_minutes"] = 15
            language_state(state, "French")["profile"]["xp"] = 220
            language_state(state, "Spanish")["profile"]["xp"] = 120
            save_temp_state(path, state)

            result = memory_reset_language(
                {"state_path": str(path), "language": "Spanish", "confirm": "RESET Spanish"}
            )
            saved = load_state(path, "Spanish")

            self.assertTrue(result["ok"])
            self.assertEqual(saved["learner"]["onboarded_at"], "2026-07-08T00:00:00+00:00")
            self.assertEqual(saved["preferences"]["lesson_minutes"], 15)
            self.assertEqual(language_state(saved, "French")["profile"]["xp"], 220)
            self.assertEqual(language_state(saved, "Spanish")["profile"]["xp"], 0)
            self.assertIn("language_reset", [event["type"] for event in saved["events"]])

    def test_practice_session_updates_language_streak_and_resets_daily_summary(self):
        state = default_state("Spanish")
        profile = profile_state(state)
        yesterday = datetime(2026, 7, 7, 9, 0, tzinfo=timezone.utc)
        today = yesterday + timedelta(days=1)
        next_week = today + timedelta(days=6)

        record_practice_session(state, "Spanish", yesterday)
        language_state(state)["daily_summary"]["lessons_completed"] = 2
        self.assertEqual(profile["streak_days"], 1)
        self.assertEqual(profile["last_practice_date"], "2026-07-07")

        record_practice_session(state, "Spanish", today)
        self.assertEqual(profile["streak_days"], 2)
        self.assertEqual(language_state(state)["daily_summary"]["lessons_completed"], 0)
        self.assertEqual(language_state(state)["daily_summary"]["conversations_completed"], 0)

        record_practice_session(state, "Spanish", today.replace(hour=18))
        self.assertEqual(profile["streak_days"], 2)

        record_practice_session(state, "Spanish", next_week)
        self.assertEqual(profile["streak_days"], 1)
        self.assertEqual(profile["last_practice_date"], "2026-07-14")

    def test_delete_all_resets_default_state_and_requires_onboarding(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "progress.json"
            state = default_state("Spanish")
            state["learner"]["onboarded_at"] = "2026-07-08T00:00:00+00:00"
            language_state(state)["profile"]["placement_completed_at"] = "2026-07-08T00:00:01+00:00"
            save_temp_state(path, state)

            result = memory_delete_all({"state_path": str(path), "language": "Spanish", "confirm": "DELETE ALL MEMORY"})
            status = onboarding_status({"state_path": str(path), "language": "Spanish"})
            saved = load_state(path, "Spanish")

            self.assertTrue(result["ok"])
            self.assertTrue(status["requires_onboarding"])
            self.assertIsNone(saved["learner"]["onboarded_at"])
            self.assertEqual(language_state(saved)["profile"]["xp"], 0)


if __name__ == "__main__":
    unittest.main()
