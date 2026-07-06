import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fluent_ai.desktop_bridge import onboarding_status, onboarding_submit, placement_start, placement_submit
from fluent_ai.state import conversation_memory, default_state, language_state, load_state, save_state


def onboarding_payload(path: Path, **overrides):
    payload = {
        "display_name": "Johan",
        "language": "Spanish",
        "motivation": "Travel and conversation",
        "goals": ["Hold a 5-minute conversation"],
        "self_reported_level": "A1",
        "speaking_comfort": "some",
        "session_minutes": 10,
        "voice_default": "openai",
        "video_default": "off",
        "privacy_local_only": True,
        "state_path": str(path),
    }
    payload.update(overrides)
    return payload


def manual_session(language: str = "Spanish") -> dict:
    items = [
        {
            "type": "multiple_choice",
            "skill": "vocabulary",
            "topic": "introductions",
            "prompt": f"Question {index}",
            "answer": f"correct {index}",
            "choices": [f"correct {index}", "wrong"],
        }
        for index in range(1, 6)
    ]
    return {
        "id": "placement_test",
        "language": language,
        "items": items,
        "written_prompt": {},
        "conversation_prompt": {},
    }


class OnboardingBridgeTests(unittest.TestCase):
    def test_onboarding_status_detects_first_launch_without_creating_file(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "progress.json"
            result = onboarding_status({"state_path": str(path), "language": "Spanish"})

            self.assertTrue(result["ok"])
            self.assertTrue(result["requires_onboarding"])
            self.assertTrue(result["is_first_launch"])
            self.assertTrue(result["requires_placement"])
            self.assertEqual(result["profile"], {})
            self.assertFalse(path.exists())

    def test_onboarding_status_requires_onboarding_for_legacy_v2_state(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "progress.json"
            state = default_state("Spanish")
            state["learner"].pop("onboarded_at", None)
            path.write_text(json.dumps(state), encoding="utf-8")

            result = onboarding_status({"state_path": str(path), "language": "Spanish"})

            self.assertTrue(result["ok"])
            self.assertTrue(result["requires_onboarding"])
            self.assertFalse(result["is_first_launch"])
            self.assertTrue(result["requires_placement"])

    def test_onboarding_submit_writes_fields_event_and_preserves_memory_on_rerun(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "progress.json"
            state = default_state("Spanish")
            memory = conversation_memory(state, "Spanish")
            memory["missed_phrases"] = ["Me llamo."]
            save_state(path, state)

            first = onboarding_submit(onboarding_payload(path))
            second = onboarding_submit(onboarding_payload(path, motivation="Work calls", speaking_comfort="comfortable"))
            saved = load_state(path, "Spanish")
            profile = language_state(saved, "Spanish")["profile"]

            self.assertTrue(first["ok"])
            self.assertTrue(second["ok"])
            self.assertEqual(saved["learner"]["display_name"], "Johan")
            self.assertEqual(saved["learner"]["motivation"], "Work calls")
            self.assertEqual(saved["learner"]["active_goals"], ["Hold a 5-minute conversation"])
            self.assertEqual(saved["learner"]["preferred_session_length_minutes"], 10)
            self.assertEqual(saved["preferences"]["lesson_minutes"], 10)
            self.assertEqual(saved["preferences"]["voice_default"], "openai")
            self.assertEqual(saved["preferences"]["video_default"], "off")
            self.assertTrue(saved["privacy"]["local_only"])
            self.assertIsNotNone(saved["privacy"]["local_memory_notice_seen_at"])
            self.assertEqual(profile["target_language"], "Spanish")
            self.assertEqual(profile["self_reported_level"], "A1")
            self.assertEqual(profile["speaking_comfort"], "comfortable")
            self.assertEqual(conversation_memory(saved, "Spanish")["speaking_confidence"], 0.50)
            self.assertEqual(conversation_memory(saved, "Spanish")["missed_phrases"], ["Me llamo."])
            self.assertLess(saved["learner"]["onboarded_at"], saved["learner"]["last_onboarding_at"])
            self.assertEqual(
                [event["type"] for event in saved["events"] if event["type"] == "onboarding_completed"],
                ["onboarding_completed", "onboarding_completed"],
            )

    def test_placement_start_returns_item_shape_without_progress_mutation(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "progress.json"
            onboarding_submit(onboarding_payload(path))
            before = load_state(path, "Spanish")
            before_events = len(before["events"])

            result = placement_start(
                {"state_path": str(path), "language": "Spanish", "include_written": True, "include_conversation": True}
            )
            after = load_state(path, "Spanish")

            self.assertTrue(result["ok"])
            session = result["session"]
            self.assertTrue(session["id"].startswith("placement_"))
            self.assertEqual(session["language"], "Spanish")
            self.assertGreaterEqual(len(session["items"]), 3)
            self.assertLessEqual(len(session["items"]), 5)
            for item in session["items"]:
                self.assertIn("type", item)
                self.assertIn("skill", item)
                self.assertIn("topic", item)
                self.assertIn("prompt", item)
                self.assertIn("answer", item)
            self.assertEqual(session["written_prompt"]["type"], "open_ended")
            self.assertEqual(session["conversation_prompt"]["type"], "conversation")
            self.assertEqual(len(after["events"]), before_events)
            self.assertIsNone(language_state(after, "Spanish")["profile"]["placement_completed_at"])

    def test_placement_judging_bands_and_b1_cap(self):
        cases = [(2, "A1"), (3, "A2"), (5, "B1")]
        for correct_answers, expected_level in cases:
            with self.subTest(correct_answers=correct_answers), TemporaryDirectory() as tmpdir:
                path = Path(tmpdir) / "progress.json"
                onboarding_submit(onboarding_payload(path, self_reported_level="new"))
                session = manual_session()
                answers = [
                    item["answer"] if index < correct_answers else "wrong"
                    for index, item in enumerate(session["items"])
                ]

                result = placement_submit({"state_path": str(path), "session": session, "answers": answers})

                self.assertTrue(result["ok"])
                self.assertEqual(result["placement"]["judged_level"], expected_level)
                self.assertEqual(result["placement"]["level_confidence"], 0.50)
                self.assertLessEqual({"A1": 1, "A2": 2, "B1": 3}[result["placement"]["judged_level"]], 3)

    def test_placement_submit_writes_state_goals_weak_topics_and_placement_evidence(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "progress.json"
            onboarding_submit(onboarding_payload(path, self_reported_level="A1"))
            start = placement_start(
                {"state_path": str(path), "language": "Spanish", "include_written": True, "include_conversation": True}
            )
            session = start["session"]
            answers = [item["answer"] for item in session["items"]]
            written_answer = session["written_prompt"]["answer"]
            keywords = session["conversation_prompt"].get("keywords", [])
            conversation_answer = " ".join(keywords + ["me", "llamo", "Johan", "soy", "de", "Nueva", "York"])

            result = placement_submit(
                {
                    "state_path": str(path),
                    "session": session,
                    "answers": answers,
                    "written_answer": written_answer,
                    "conversation_answer": conversation_answer,
                }
            )
            saved = load_state(path, "Spanish")
            data = language_state(saved, "Spanish")
            profile = data["profile"]
            memory = conversation_memory(saved, "Spanish")
            placement_events = [event for event in saved["events"] if event["type"] == "placement_completed"]

            self.assertTrue(result["ok"])
            self.assertEqual(profile["current_level"], "B1")
            self.assertEqual(profile["level_confidence"], 0.70)
            self.assertEqual(profile["placement_method"], "adaptive")
            self.assertIsNotNone(profile["placement_completed_at"])
            self.assertEqual(profile["first_practice_goal"], result["placement"]["first_practice_goal"])
            self.assertEqual(profile["judged_strengths"], result["placement"]["strongest_skills"])
            self.assertEqual(profile["judged_weaknesses"], result["placement"]["weakest_skills"])
            self.assertTrue(data["weak_topics"])
            self.assertEqual(memory["next_conversation_goal"]["source"], "placement")
            self.assertEqual(memory["next_conversation_goal"]["instruction"], result["placement"]["first_conversation_goal"])
            self.assertTrue(placement_events)
            self.assertEqual(placement_events[-1]["payload"]["method"], "adaptive")
            self.assertEqual(placement_events[-1]["payload"]["quiz_score"], f"{len(session['items'])}/{len(session['items'])}")
            self.assertIn("strongest_skills", placement_events[-1]["payload"])
            evidence_modes = [
                evidence.get("mode")
                for record in data["skills"].values()
                for evidence in record.get("evidence", [])
            ]
            self.assertIn("placement", evidence_modes)

    def test_placement_skip_beginner_path(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "progress.json"
            onboarding_submit(onboarding_payload(path, self_reported_level="not sure"))

            result = placement_submit({"state_path": str(path), "session": {"language": "Spanish"}, "skip_beginner": True})
            saved = load_state(path, "Spanish")
            profile = language_state(saved, "Spanish")["profile"]
            memory = conversation_memory(saved, "Spanish")
            placement_event = [event for event in saved["events"] if event["type"] == "placement_completed"][-1]

            self.assertTrue(result["ok"])
            self.assertEqual(profile["current_level"], "A1")
            self.assertEqual(profile["level_confidence"], 0.35)
            self.assertEqual(profile["placement_method"], "skip_beginner")
            self.assertEqual(profile["first_practice_goal"], "Build basic introductions and daily phrases.")
            self.assertEqual(memory["next_conversation_goal"]["topic"], "introductions")
            self.assertEqual(placement_event["payload"]["method"], "skip_beginner")


if __name__ == "__main__":
    unittest.main()
