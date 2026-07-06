import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fluent_ai.state import (
    add_event,
    append_history_event,
    conversation_memory,
    default_state,
    language_state,
    load_state,
    migrate_state,
    profile_state,
    record_mistake,
    review_queue,
    save_state,
    set_skill_score,
    set_topic_score,
)


def representative_v1_state():
    return {
        "learner": {
            "name": "Johan",
            "target_language": "Spanish",
            "current_level": "A2",
            "level": "A1",
            "xp": 120,
            "streak_days": 4,
            "learning_goals": ["Order food", "Talk about work"],
        },
        "skills": {"vocabulary": 0.44, "grammar": 0.31, "conjugation": 0.22},
        "topic_mastery": {"travel": 0.41},
        "weak_topics": ["conjugations", "travel"],
        "preferences": {"lesson_minutes": 12, "daily_quiz_questions": 7, "tone": "direct"},
        "recent_topics": ["introductions"],
        "review_queue": {
            "past tense": {
                "topic": "past tense",
                "focus_skill": "conjugations",
                "due_at": "2026-07-09T00:00:00+00:00",
                "interval_days": 1,
                "missed_count": 2,
            }
        },
        "history": [
            {"topic": "travel", "focus_skill": "vocabulary", "correct_count": 4, "total_questions": 6},
            {"mode": "conversation", "topic": "weather", "turns": 3},
            {"mode": "conversation_turn", "topic": "weather", "score": 0.6},
        ],
        "daily_summary": {"last_sent_at": "2026-07-08T00:00:00+00:00", "lessons_completed": 2},
        "conversation_memory": {
            "sessions_completed": 1,
            "total_turns": 3,
            "fluency_score": 0.52,
            "speaking_confidence": 0.48,
            "recent_topics": ["weather"],
            "missed_phrases": ["yo hablo"],
            "last_video_object": "apple",
            "next_speaking_goal": "Answer weather questions.",
            "last_session_at": "2026-07-08T01:00:00+00:00",
        },
        "custom_note": {"keep": True},
        "updated_at": "2026-07-08T02:00:00+00:00",
    }


class StateV2Tests(unittest.TestCase):
    def test_v1_to_v2_mapping_is_lossless_for_representative_state(self):
        migrated = migrate_state(representative_v1_state(), "Spanish")
        language = migrated["languages"]["Spanish"]

        self.assertEqual(migrated["schema_version"], 2)
        self.assertEqual(migrated["learner"]["display_name"], "Johan")
        self.assertEqual(migrated["learner"]["active_goals"], ["Order food", "Talk about work"])
        self.assertEqual(migrated["learner"]["preferred_session_length_minutes"], 12)
        self.assertEqual(migrated["learner"]["preferred_tutor_tone"], "direct")
        self.assertEqual(migrated["active_language"], "Spanish")
        self.assertEqual(language["profile"]["current_level"], "A2")
        self.assertEqual(language["profile"]["xp"], 120)
        self.assertEqual(language["profile"]["streak_days"], 4)
        self.assertEqual(language["profile"]["learning_goals"], ["Order food", "Talk about work"])
        self.assertEqual(language["profile"]["last_session_at"], "2026-07-08T01:00:00+00:00")

        self.assertEqual(language["skills"]["vocabulary"]["score"], 0.44)
        self.assertEqual(language["skills"]["conjugations"]["score"], 0.22)
        self.assertNotIn("conjugation", language["skills"])
        self.assertEqual(language["topic_mastery"]["travel"]["recognition"], 0.41)
        self.assertEqual(language["topic_mastery"]["travel"]["recall"], 0.41)
        self.assertEqual(language["weak_topics"], ["conjugations", "travel"])
        self.assertEqual(language["recent_topics"], ["introductions"])
        self.assertEqual(language["daily_summary"]["lessons_completed"], 2)

        review = language["review_queue"]["review_topic_past_tense"]
        self.assertEqual(review["id"], "review_topic_past_tense")
        self.assertEqual(review["item_type"], "topic")
        self.assertEqual(review["target"], "past tense")
        self.assertEqual(review["source"], "lesson")
        self.assertEqual(review["focus_skill"], "conjugations")
        self.assertEqual(review["missed_count"], 2)

        history_types = [event["type"] for event in language["history"]]
        self.assertEqual(history_types, ["lesson_completed", "conversation_started", "learner_replied"])
        self.assertEqual(language["history"][0]["payload"]["legacy"]["topic"], "travel")
        self.assertEqual(language["history"][1]["payload"]["legacy"]["mode"], "conversation")
        self.assertEqual(language["history"][2]["payload"]["legacy"]["mode"], "conversation_turn")

        memory = language["conversation_memory"]
        self.assertEqual(memory["sessions_completed"], 1)
        self.assertEqual(memory["total_turns"], 3)
        self.assertEqual(memory["fluency_score"], 0.52)
        self.assertEqual(memory["speaking_confidence"], 0.48)
        self.assertEqual(memory["missed_phrases"], ["yo hablo"])
        self.assertEqual(memory["last_video_context"]["primary_object"], "apple")
        self.assertEqual(memory["next_speaking_goal"], "Answer weather questions.")
        self.assertTrue(any(record["source"] == "legacy_missed_phrase" for record in language["mistake_memory"].values()))
        self.assertEqual(language["legacy_extra"], {"custom_note": {"keep": True}})

    def test_migration_is_idempotent_byte_identical(self):
        first = migrate_state(representative_v1_state(), "Spanish")
        second = migrate_state(copy.deepcopy(first), "Spanish")

        self.assertEqual(
            json.dumps(first, sort_keys=True, ensure_ascii=False),
            json.dumps(second, sort_keys=True, ensure_ascii=False),
        )

    def test_default_v2_shape_has_required_sections(self):
        state = default_state("French")
        self.assertEqual(state["schema_version"], 2)
        self.assertEqual(state["active_language"], "French")
        self.assertIn("French", state["languages"])
        self.assertIn("profile", state["languages"]["French"])
        self.assertIn("skills", state["languages"]["French"])
        self.assertIn("topic_mastery", state["languages"]["French"])
        self.assertIn("mistake_memory", state["languages"]["French"])
        self.assertIn("last_video_context", state["languages"]["French"]["conversation_memory"])
        self.assertIn("privacy", state)
        self.assertIn("events", state)
        self.assertEqual(state["active_language"], "French")
        self.assertNotIn("target_language", state["learner"])
        self.assertNotIn("skills", state)
        self.assertEqual(state["languages"]["French"]["skills"]["vocabulary"]["score"], 0.34)

    def test_append_history_event_caps_language_history_and_keeps_newest(self):
        state = default_state("Spanish")
        for index in range(305):
            append_history_event(state, {"type": "progress_updated", "summary": f"event {index}", "payload": {}})

        history = state["languages"]["Spanish"]["history"]
        self.assertEqual(len(history), 300)
        self.assertEqual(history[0]["summary"], "event 5")
        self.assertEqual(history[-1]["summary"], "event 304")
        self.assertEqual(len(state["events"]), 305)

    def test_record_mistake_dedupes_and_increments_frequency(self):
        state = default_state("Spanish")
        mistake = {
            "incorrect_form": "yo hablar",
            "corrected_form": "yo hablo",
            "context": "Present tense practice.",
            "skill": "conjugations",
            "topic": "daily routines",
            "error_category": "wrong_conjugation",
        }

        first = record_mistake(state, mistake)
        second = record_mistake(state, mistake)

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["frequency"], 2)
        self.assertEqual(len(state["languages"]["Spanish"]["mistake_memory"]), 1)
        self.assertEqual(second["first_seen"], first["first_seen"])

    def test_set_skill_score_tracks_trend_and_bounds_evidence(self):
        state = default_state("Spanish")
        for index in range(10):
            set_skill_score(state, "grammar", 0.40 + index / 100, evidence={"event_id": str(index)})
        record = state["languages"]["Spanish"]["skills"]["grammar"]

        self.assertEqual(record["trend"], "up")
        self.assertEqual(record["score"], 0.49)
        self.assertEqual(len(record["evidence"]), 8)
        self.assertEqual(record["evidence"][0]["event_id"], "2")
        set_skill_score(state, "grammar", 2.0)
        self.assertEqual(state["languages"]["Spanish"]["skills"]["grammar"]["score"], 0.99)
        set_skill_score(state, "grammar", 0.01)
        self.assertEqual(state["languages"]["Spanish"]["skills"]["grammar"]["score"], 0.05)
        self.assertEqual(state["languages"]["Spanish"]["skills"]["grammar"]["trend"], "down")

    def test_pure_v2_round_trips_without_duplicate_top_level_views(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "progress.json"
            state = load_state(path, "Spanish")
            profile_state(state)["xp"] = 77
            profile_state(state)["current_level"] = "B1"
            set_skill_score(state, "vocabulary", 0.88)
            set_topic_score(state, "travel", 0.66)
            review_queue(state)["review_topic_travel"] = {
                "id": "review_topic_travel",
                "item_type": "topic",
                "target": "travel",
                "topic": "travel",
                "focus_skill": "vocabulary",
                "due_at": "2026-07-09T00:00:00+00:00",
                "interval_days": 2,
            }
            append_history_event(
                state,
                {
                    "type": "lesson_completed",
                    "source": "test",
                    "summary": "Travel lesson.",
                    "payload": {"topic": "travel", "correct_count": 5, "total_questions": 6},
                },
            )
            conversation_memory(state)["last_video_context"]["primary_object"] = "book"
            save_state(path, state)

            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["schema_version"], 2)
            for key in ("skills", "topic_mastery", "weak_topics", "recent_topics", "review_queue", "history", "conversation_memory", "daily_summary"):
                self.assertNotIn(key, persisted)
            self.assertNotIn("xp", persisted["learner"])
            self.assertEqual(persisted["languages"]["Spanish"]["profile"]["xp"], 77)
            self.assertEqual(persisted["languages"]["Spanish"]["profile"]["current_level"], "B1")
            self.assertEqual(persisted["languages"]["Spanish"]["skills"]["vocabulary"]["score"], 0.88)
            self.assertEqual(persisted["languages"]["Spanish"]["topic_mastery"]["travel"]["recognition"], 0.66)
            self.assertIn("review_topic_travel", persisted["languages"]["Spanish"]["review_queue"])
            self.assertEqual(
                persisted["languages"]["Spanish"]["conversation_memory"]["last_video_context"]["primary_object"],
                "book",
            )
            self.assertEqual(persisted["languages"]["Spanish"]["history"][-1]["payload"]["topic"], "travel")

            reloaded = load_state(path, "Spanish")
            self.assertEqual(profile_state(reloaded)["xp"], 77)
            self.assertEqual(language_state(reloaded)["skills"]["vocabulary"]["score"], 0.88)
            self.assertIn("review_topic_travel", review_queue(reloaded))

    def test_event_ids_remain_unique_after_top_level_cap(self):
        state = default_state("Spanish")
        for index in range(1005):
            add_event(state, {"type": "progress_updated", "summary": f"event {index}", "payload": {}})

        ids = [event["id"] for event in state["events"]]
        self.assertEqual(len(state["events"]), 1000)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(state["event_counter"], 1005)


if __name__ == "__main__":
    unittest.main()
