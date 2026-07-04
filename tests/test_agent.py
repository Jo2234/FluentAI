import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from fluent_ai.agent import choose_topic, evaluate_answers, generate_lesson, generate_quiz, update_progress
from fluent_ai.conversation import asks_for_english_help, build_follow_up, choose_conversation_topic, run_conversation
from fluent_ai.desktop_bridge import conversation_reply, conversation_start, lesson_start, lesson_submit, status
from fluent_ai.state import default_state


def fake_tutor_reply(topic, state, transcript, phase, fallback):
    return fallback


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


class AgentTests(unittest.TestCase):
    def test_progress_updates_after_quiz(self):
        state = default_state("Spanish")
        lesson = generate_lesson(state)
        quiz = generate_quiz(state, lesson)
        answers = [question["answer"] for question in quiz]

        results = evaluate_answers(quiz, answers)
        update_progress(state, lesson, results)

        self.assertGreater(state["learner"]["xp"], 0)
        self.assertTrue(state["history"])
        self.assertIn(lesson["topic"], state["recent_topics"])
        self.assertIn("current_level", state["learner"])

    def test_quiz_has_required_mixed_question_types(self):
        state = default_state("Spanish")
        lesson = generate_lesson(state)
        quiz = generate_quiz(state, lesson)
        question_types = {question["type"] for question in quiz}

        self.assertGreaterEqual(len(quiz), 5)
        self.assertLessEqual(len(quiz), 8)
        self.assertIn("multiple_choice", question_types)
        self.assertIn("fill_blank", question_types)
        self.assertIn("open_ended", question_types)

    def test_missed_lesson_schedules_spaced_review(self):
        state = default_state("Spanish")
        lesson = generate_lesson(state)
        quiz = generate_quiz(state, lesson)
        answers = ["not yet" for _question in quiz]

        results = evaluate_answers(quiz, answers)
        update_progress(state, lesson, results)

        scheduled = state["review_queue"][lesson["topic"]]
        self.assertEqual(scheduled["topic"], lesson["topic"])
        self.assertEqual(scheduled["focus_skill"], lesson["focus_skill"])
        self.assertEqual(scheduled["interval_days"], 1)
        self.assertIn("due_at", scheduled)

    def test_due_spaced_review_overrides_recent_topic_rotation(self):
        state = default_state("Spanish")
        state["recent_topics"] = ["past tense", "conjugations", "vocabulary"]
        state["review_queue"] = {
            "past tense": {
                "topic": "past tense",
                "focus_skill": "conjugations",
                "due_at": "2000-01-01T00:00:00+00:00",
                "interval_days": 1,
                "missed_count": 2,
            }
        }

        self.assertEqual(choose_topic(state), "past tense")

    def test_conversation_mode_initiates_and_updates_memory(self):
        state = default_state("Spanish")

        transcript, updated_state, topic = run_conversation(
            state=state,
            turns=3,
            mode="auto",
            video_on=False,
            video_object=None,
            tutor_reply_fn=fake_tutor_reply,
        )

        self.assertEqual(len(transcript), 3)
        self.assertTrue(transcript[0].tutor_text)
        self.assertEqual(updated_state["conversation_memory"]["sessions_completed"], 1)
        self.assertEqual(updated_state["conversation_memory"]["total_turns"], 3)
        self.assertIn(topic["topic"], updated_state["conversation_memory"]["recent_topics"])

    def test_video_object_steers_beginner_conversation(self):
        state = default_state("Spanish")

        topic = choose_conversation_topic(state, video_on=True, video_object="apple")
        transcript, updated_state, _topic = run_conversation(
            state=state,
            turns=2,
            mode="auto",
            video_on=True,
            video_object="apple",
            tutor_reply_fn=fake_tutor_reply,
        )

        self.assertIn("manzana", topic["opening"])
        self.assertIn("manzana", transcript[0].tutor_text)
        self.assertEqual(updated_state["conversation_memory"]["last_video_object"], "apple")

    def test_advanced_conversation_uses_complex_topics(self):
        state = default_state("Spanish")
        state["learner"]["current_level"] = "C1"
        state["learner"]["level"] = "C1"

        topic = choose_conversation_topic(state, video_on=False, video_object=None)

        self.assertIn(topic["complexity"], {"advanced", "near-native"})

    def test_conversation_can_switch_to_english_help(self):
        state = default_state("Spanish")
        topic = {
            "topic": "weather",
            "complexity": "beginner",
            "support": "Model answer: Hace sol.",
            "keywords": ["hace", "sol"],
        }

        self.assertTrue(asks_for_english_help("What does that mean in English?"))
        follow_up = build_follow_up(topic, "What does that mean in English?", 0.2, 1, state)
        self.assertIn("In English", follow_up)
        self.assertIn("Hace sol", follow_up)

    def test_desktop_bridge_switches_supported_languages(self):
        with TemporaryDirectory() as tmpdir:
            state_path = str(Path(tmpdir) / "progress.json")

            hindi = status({"state_path": state_path, "language": "Hindi"})
            french = status({"state_path": state_path, "language": "French"})

            self.assertTrue(hindi["ok"])
            self.assertEqual(hindi["profile"]["language"], "Hindi")
            self.assertTrue(french["ok"])
            self.assertEqual(french["profile"]["language"], "French")
            self.assertIn("French", french["profile"]["next_speaking_goal"])

    def test_non_spanish_lesson_quiz_uses_target_language_content(self):
        state = default_state("Hindi")
        lesson = generate_lesson(state)
        quiz = generate_quiz(state, lesson)

        self.assertEqual(lesson["language"], "Hindi")
        self.assertIn("नमस्ते", [item[0] for item in lesson["vocabulary"]])
        self.assertEqual(quiz[0]["answer"], "hello")
        self.assertTrue(any("Hindi" in question["prompt"] for question in quiz))

    def test_desktop_bridge_lesson_waits_for_real_answers(self):
        with TemporaryDirectory() as tmpdir, patch("fluent_ai.desktop_bridge.OpenAIProvider", FakeOpenAIProvider):
            state_path = str(Path(tmpdir) / "progress.json")
            start = lesson_start({"state_path": state_path, "language": "Spanish"})
            answers = [question["answer"] for question in start["quiz"]]

            result = lesson_submit(
                {
                    "state_path": state_path,
                    "language": "Spanish",
                    "lesson": start["lesson"],
                    "quiz": start["quiz"],
                    "answers": answers,
                }
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["summary"]["score"], f"{len(answers)}/{len(answers)}")
            self.assertGreater(result["profile"]["xp"], 0)

    def test_desktop_bridge_conversation_accepts_user_reply(self):
        with TemporaryDirectory() as tmpdir, patch("fluent_ai.desktop_bridge.OpenAIProvider", FakeOpenAIProvider):
            state_path = str(Path(tmpdir) / "progress.json")
            start = conversation_start(
                {
                    "state_path": state_path,
                    "language": "Spanish",
                    "video": "on",
                    "object": "apple",
                    "turns": 2,
                }
            )
            reply = conversation_reply(
                {
                    "state_path": state_path,
                    "language": "Spanish",
                    "session": start["session"],
                    "message": "Esto es una manzana.",
                    "tutor_message": start["tutor_message"],
                }
            )

            self.assertTrue(reply["ok"])
            self.assertEqual(len(reply["session"]["turns"]), 1)
            self.assertIn("manzana", reply["tutor_message"])
            self.assertGreater(reply["profile"]["fluency_score"], start["profile"]["fluency_score"])


if __name__ == "__main__":
    unittest.main()
