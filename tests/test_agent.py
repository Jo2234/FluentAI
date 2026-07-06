import json
import unittest
from datetime import datetime, timezone
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from fluent_ai.agent import (
    QuizResult,
    categorize_error,
    choose_topic,
    choose_topic_with_reason,
    due_mistake_items,
    due_review_items,
    evaluate_answers,
    generate_lesson,
    generate_quiz,
    update_progress,
)
from fluent_ai.conversation import (
    asks_for_english_help,
    apply_turn_progress,
    build_post_call_summary,
    build_follow_up,
    build_opening,
    choose_conversation_topic,
    evaluate_reply_with_metadata,
    persist_post_call_summary,
    run_conversation,
    visual_reply_options,
)
from fluent_ai.desktop_bridge import (
    _load,
    apply_conversation_turn_progress,
    conversation_end,
    conversation_reply,
    conversation_start,
    lesson_start,
    lesson_submit,
    profile_for,
    status,
)
from fluent_ai.openai_provider import OpenAIProvider, _realtime_instructions
from fluent_ai.state import conversation_memory, default_state, language_state, load_state, profile_state, record_mistake, review_queue, save_state


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

    def evaluate_quiz_answers(self, state, lesson, items):
        return None


class OpenAIGradingProvider(FakeOpenAIProvider):
    calls = 0
    seen_items = []

    def evaluate_quiz_answers(self, state, lesson, items):
        type(self).calls += 1
        type(self).seen_items = items
        return [
            {
                "correct": False,
                "error_category": "wrong_tense",
                "feedback": "Almost. Use the past-tense form from the lesson.",
                "corrected_form": "fui",
                "severity": "high",
                "confidence": 0.91,
            }
            for _item in items
        ]


class PartialOpenAIGradingProvider(FakeOpenAIProvider):
    calls = 0

    def evaluate_quiz_answers(self, state, lesson, items):
        type(self).calls += 1
        return [
            {
                "correct": False,
                "error_category": "comprehension",
                "feedback": "Not quite. Use the meaning from the lesson.",
                "corrected_form": "Me llamo Ana.",
                "severity": "high",
                "confidence": 0.87,
            },
            None,
        ]


class ConversationWrongConjugationProvider(FakeOpenAIProvider):
    calls = 0

    def evaluate_conversation_reply(self, state, topic, learner_text):
        type(self).calls += 1
        return {
            "score": 0.42,
            "understandable": True,
            "correction": "Yo estudio por la manana.",
            "incorrect_form": "yo estudiar",
            "corrected_form": "Yo estudio",
            "error_category": "wrong_conjugation",
            "feedback": "Use the conjugated form estudio with yo.",
            "blocked_meaning": False,
        }


class MalformedConversationGradeProvider(FakeOpenAIProvider):
    calls = 0

    def evaluate_conversation_reply(self, state, topic, learner_text):
        type(self).calls += 1
        return {"score": 0.1, "feedback": "Malformed and incomplete."}


class CorrectConversationGradeProvider(FakeOpenAIProvider):
    calls = 0

    def evaluate_conversation_reply(self, state, topic, learner_text):
        type(self).calls += 1
        return {
            "score": 0.86,
            "understandable": True,
            "correction": None,
            "incorrect_form": None,
            "corrected_form": None,
            "error_category": None,
            "feedback": "Clear and appropriate for this level.",
            "blocked_meaning": False,
        }


class MalformedQuizProvider(OpenAIProvider):
    @property
    def available(self):
        return True

    def _text_response(self, prompt):
        return '{"correct": false, "error_category": "not_allowed"}'


class ValidConversationEvaluatorProvider(MalformedQuizProvider):
    def _text_response(self, prompt):
        return json.dumps(
            {
                "score": 0.4,
                "understandable": True,
                "correction": "Yo estudio por la manana.",
                "incorrect_form": "yo estudiar",
                "corrected_form": "Yo estudio",
                "error_category": "wrong_conjugation",
                "feedback": "Use estudio after yo.",
                "blocked_meaning": False,
            }
        )


class InvalidEntryQuizProvider(MalformedQuizProvider):
    def _text_response(self, prompt):
        return (
            '[{"correct": false, "error_category": "not_allowed", "feedback": "Bad", '
            '"corrected_form": "Quisiera un cafe, por favor.", "severity": "high", "confidence": 0.9}]'
        )


class PromptCaptureProvider(OpenAIProvider):
    captured_prompt = ""

    @property
    def available(self):
        return True

    def _text_response(self, prompt):
        type(self).captured_prompt = prompt
        return "Hola, practicamos."


class AgentTests(unittest.TestCase):
    def test_progress_updates_after_quiz(self):
        state = default_state("Spanish")
        lesson = generate_lesson(state)
        quiz = generate_quiz(state, lesson)
        answers = [question["answer"] for question in quiz]

        results = evaluate_answers(quiz, answers)
        update_progress(state, lesson, results)

        self.assertGreater(profile_state(state)["xp"], 0)
        self.assertTrue(language_state(state)["history"])
        self.assertIn(lesson["topic"], language_state(state)["recent_topics"])
        self.assertIn("current_level", profile_state(state))
        self.assertEqual(language_state(state)["history"][-3]["type"], "lesson_completed")

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

    def test_categorizes_too_short_open_answer(self):
        question = {
            "type": "open_ended",
            "skill": "vocabulary",
            "topic": "introductions",
            "prompt": "Write one short sentence about introductions.",
            "answer": "Me llamo Ana.",
            "keywords": ["llamo"],
        }

        self.assertEqual(categorize_error(question, ""), "too_short")

    def test_categorizes_vocabulary_missing_multiple_choice(self):
        question = {
            "type": "multiple_choice",
            "skill": "vocabulary",
            "topic": "cafe orders",
            "prompt": "What does 'la cuenta' mean?",
            "answer": "the bill",
        }

        self.assertEqual(categorize_error(question, "friend"), "vocabulary_missing")

    def test_categorizes_wrong_conjugation_fill_blank(self):
        question = {
            "type": "fill_blank",
            "skill": "conjugations",
            "topic": "conjugations",
            "prompt": "Fill in the blank: Yo ___ espanol.",
            "answer": "hablo",
            "acceptable_answers": ["hablo"],
        }

        self.assertEqual(categorize_error(question, "hablar"), "wrong_conjugation")

    def test_categorizes_wrong_tense(self):
        question = {
            "type": "open_ended",
            "skill": "conjugations",
            "topic": "past tense",
            "prompt": "Write one short sentence about past tense.",
            "answer": "Ayer fui al mercado.",
            "keywords": ["ayer", "fui"],
        }

        self.assertEqual(categorize_error(question, "Yo voy al mercado"), "wrong_tense")

    def test_categorizes_word_order(self):
        question = {
            "type": "open_ended",
            "skill": "vocabulary",
            "topic": "vocabulary",
            "prompt": "Write one model sentence.",
            "answer": "Mi casa es pequena.",
            "keywords": ["casa", "pequena"],
        }

        self.assertEqual(categorize_error(question, "casa mi pequena es"), "word_order")

    def test_categorizes_comprehension(self):
        question = {
            "type": "open_ended",
            "skill": "vocabulary",
            "topic": "cafe orders",
            "prompt": "Write one cafe order.",
            "answer": "Quisiera un cafe, por favor.",
            "keywords": ["quisiera", "cafe"],
        }

        self.assertEqual(categorize_error(question, "Trabajo oficina"), "comprehension")

    def test_unnatural_keyword_match_is_advisory_correct(self):
        state = default_state("Spanish")
        lesson = {
            "language": "Spanish",
            "level": "A1",
            "topic": "cafe orders",
            "focus_skill": "vocabulary",
            "difficulty": "steady",
            "minutes": 10,
        }
        question = {
            "type": "open_ended",
            "skill": "vocabulary",
            "topic": "cafe orders",
            "prompt": "Write one cafe order.",
            "answer": "Quisiera un cafe, por favor.",
            "keywords": ["cafe"],
        }

        self.assertEqual(categorize_error(question, "cafe ahora"), "unnatural")
        result = evaluate_answers([question], ["cafe ahora"])[0]
        self.assertTrue(result.correct)
        self.assertEqual(result.error_category, "unnatural")
        self.assertEqual(result.corrected_form, "Quisiera un cafe, por favor.")
        self.assertEqual(result.severity, "low")
        self.assertEqual(
            result.feedback,
            "Understandable! A native speaker might say: 'Quisiera un cafe, por favor.'.",
        )

        update_progress(state, lesson, [result])

        self.assertEqual(language_state(state)["mistake_memory"], {})
        self.assertEqual(profile_state(state)["xp"], 15)
        self.assertIsNone(conversation_memory(state)["next_conversation_goal"])

    def test_missed_lesson_sets_next_conversation_goal_and_clean_lesson_clears_it(self):
        state = default_state("Spanish")
        lesson = {
            "language": "Spanish",
            "level": "A1",
            "topic": "daily routines",
            "focus_skill": "conjugations",
            "difficulty": "steady",
            "minutes": 10,
        }
        missed = [
            QuizResult(
                prompt="Fill in the blank: Yo ___ cada dia.",
                expected="trabajo",
                actual="trabajar",
                skill="conjugations",
                topic="daily routines",
                question_type="fill_blank",
                correct=False,
                feedback="Use trabajo.",
                error_category="wrong_conjugation",
                corrected_form="trabajo",
                severity="medium",
                confidence=0.9,
            )
        ]

        update_progress(state, lesson, missed)

        goal = conversation_memory(state)["next_conversation_goal"]
        self.assertEqual(goal["topic"], "daily routines")
        self.assertEqual(goal["skill"], "conjugations")
        self.assertEqual(goal["error_category"], "wrong_conjugation")
        self.assertIn("first-person present tense", goal["instruction"])
        self.assertEqual(goal["source"], "lesson")
        self.assertEqual(language_state(state)["history"][-1]["payload"]["next_conversation_goal"], goal)

        clean = [
            QuizResult(
                prompt="Fill in the blank: Yo ___ cada dia.",
                expected="trabajo",
                actual="trabajo",
                skill="conjugations",
                topic="daily routines",
                question_type="fill_blank",
                correct=True,
                feedback="Good.",
            )
        ]
        update_progress(state, lesson, clean)

        self.assertIsNone(conversation_memory(state)["next_conversation_goal"])
        self.assertIsNone(language_state(state)["history"][-1]["payload"]["next_conversation_goal"])

    def test_personal_intro_variation_stays_correct_with_advisory(self):
        question = {
            "type": "open_ended",
            "skill": "vocabulary",
            "topic": "introductions",
            "prompt": "Write one short sentence about introductions",
            "answer": "Me llamo Ana.",
            "keywords": ["llamo"],
        }

        result = evaluate_answers([question], ["Me llamo Johan."])[0]

        self.assertTrue(result.correct)
        self.assertEqual(result.error_category, "unnatural")
        self.assertEqual(result.corrected_form, "Me llamo Ana.")
        self.assertEqual(
            result.feedback,
            "Understandable! A native speaker might say: 'Me llamo Ana.'.",
        )

    def test_missed_lesson_schedules_spaced_review(self):
        state = default_state("Spanish")
        lesson = generate_lesson(state)
        quiz = generate_quiz(state, lesson)
        answers = ["not yet" for _question in quiz]

        results = evaluate_answers(quiz, answers)
        update_progress(state, lesson, results)

        scheduled = review_queue(state)[f"review_topic_{lesson['topic'].replace(' ', '_')}"]
        self.assertEqual(scheduled["topic"], lesson["topic"])
        self.assertEqual(scheduled["focus_skill"], lesson["focus_skill"])
        self.assertEqual(scheduled["interval_days"], 1)
        self.assertIn("due_at", scheduled)

    def test_missed_lesson_creates_mistake_memory_with_next_review(self):
        state = default_state("Spanish")
        lesson = {
            "language": "Spanish",
            "level": "A1",
            "topic": "conjugations",
            "focus_skill": "conjugations",
            "difficulty": "steady",
            "minutes": 10,
        }
        quiz = [
            {
                "type": "fill_blank",
                "skill": "conjugations",
                "topic": "conjugations",
                "prompt": "Fill in the blank: Yo ___ espanol.",
                "answer": "hablo",
                "acceptable_answers": ["hablo"],
            }
        ]

        results = evaluate_answers(quiz, ["hablar"])
        update_progress(state, lesson, results)

        mistakes = language_state(state)["mistake_memory"]
        self.assertEqual(len(mistakes), 1)
        mistake = next(iter(mistakes.values()))
        self.assertEqual(mistake["incorrect_form"], "hablar")
        self.assertEqual(mistake["corrected_form"], "hablo")
        self.assertEqual(mistake["error_category"], "wrong_conjugation")
        self.assertEqual(mistake["severity"], "medium")
        self.assertIn("next_review", mistake)
        self.assertTrue(mistake["next_review"])
        self.assertGreater(datetime.fromisoformat(mistake["next_review"]), datetime.now(timezone.utc))
        self.assertIn(f"review_{mistake['id']}", review_queue(state))

    def test_successful_mistake_memory_lesson_reschedules_mistake_review(self):
        state = default_state("Spanish")
        mistake = record_mistake(
            state,
            {
                "incorrect_form": "yo estudiar",
                "corrected_form": "yo estudio",
                "skill": "conjugations",
                "topic": "daily routines",
                "error_category": "wrong_conjugation",
                "source": "conversation",
                "next_review": "2000-01-01T00:00:00+00:00",
            },
        )
        lesson = {
            "language": "Spanish",
            "level": "A1",
            "topic": "daily routines",
            "selection_source": "mistake_memory",
            "focus_skill": "conjugations",
            "difficulty": "steady",
            "minutes": 10,
        }
        results = [
            QuizResult(
                prompt="Fill in the blank: Yo ___ por la manana.",
                expected="estudio",
                actual="estudio",
                skill="conjugations",
                topic="daily routines",
                question_type="fill_blank",
                correct=True,
                feedback="Good.",
            ),
            QuizResult(
                prompt="Fill in the blank: Tu ___ por la manana.",
                expected="estudias",
                actual="estudias",
                skill="conjugations",
                topic="daily routines",
                question_type="fill_blank",
                correct=True,
                feedback="Good.",
            ),
            QuizResult(
                prompt="Fill in the blank: Yo ___ cada dia.",
                expected="trabajo",
                actual="trabajar",
                skill="conjugations",
                topic="daily routines",
                question_type="fill_blank",
                correct=False,
                feedback="Use trabajo.",
                error_category="wrong_conjugation",
                corrected_form="trabajo",
                severity="medium",
            ),
        ]

        update_progress(state, lesson, results)

        rescheduled = language_state(state)["mistake_memory"][mistake["id"]]
        due_at = datetime.fromisoformat(rescheduled["next_review"])
        self.assertGreater(due_at, datetime.now(timezone.utc))
        self.assertEqual(review_queue(state)[f"review_{mistake['id']}"]["due_at"], rescheduled["next_review"])
        self.assertEqual(due_mistake_items(state), [])

    def test_due_spaced_review_overrides_recent_topic_rotation(self):
        state = default_state("Spanish")
        language_state(state)["recent_topics"] = ["past tense", "conjugations", "vocabulary"]
        review_queue(state)["review_topic_past_tense"] = {
            "id": "review_topic_past_tense",
            "item_type": "topic",
            "target": "past tense",
                "topic": "past tense",
                "focus_skill": "conjugations",
                "due_at": "2000-01-01T00:00:00+00:00",
                "interval_days": 1,
                "missed_count": 2,
        }

        self.assertEqual(choose_topic(state), "past tense")

    def test_lesson_reason_for_due_review(self):
        state = default_state("Spanish")
        review_queue(state)["review_topic_past_tense"] = {
            "id": "review_topic_past_tense",
            "item_type": "topic",
            "target": "past tense",
            "topic": "past tense",
            "focus_skill": "conjugations",
            "due_at": "2000-01-01T00:00:00+00:00",
            "interval_days": 2,
            "last_score": "3/6",
        }

        lesson = generate_lesson(state)

        self.assertEqual(lesson["topic"], "past tense")
        self.assertEqual(lesson["selection_source"], "due_review")
        self.assertIn("last score was 3/6", lesson["reason"])
        self.assertIn("interval is 2 days", lesson["reason"])

    def test_lesson_reason_for_mistake_memory(self):
        state = default_state("Spanish")
        record_mistake(
            state,
            {
                "incorrect_form": "yo hablar",
                "corrected_form": "yo hablo",
                "skill": "conjugations",
                "topic": "conjugations",
                "error_category": "wrong_conjugation",
                "source": "conversation",
                "next_review": "2000-01-01T00:00:00+00:00",
            },
        )

        lesson = generate_lesson(state)

        self.assertEqual(lesson["topic"], "conjugations")
        self.assertEqual(lesson["selection_source"], "mistake_memory")
        self.assertIn("'yo hablar' -> 'yo hablo'", lesson["reason"])

    def test_lesson_reason_for_weak_topic(self):
        state = default_state("Spanish")
        language_state(state)["weak_topics"] = ["vocabulary"]

        lesson = generate_lesson(state)

        self.assertEqual(lesson["topic"], "vocabulary")
        self.assertEqual(lesson["selection_source"], "weak_topic")
        self.assertEqual(
            lesson["reason"],
            "Your weakest current topic is vocabulary based on recent lesson and conversation evidence.",
        )

    def test_lesson_reason_for_rotation(self):
        state = default_state("Spanish")
        language_state(state)["weak_topics"] = []

        with patch("fluent_ai.agent.random.choice", return_value="daily routines"):
            lesson = generate_lesson(state)

        self.assertEqual(lesson["topic"], "daily routines")
        self.assertEqual(lesson["selection_source"], "rotation")
        self.assertEqual(lesson["reason"], "This avoids repeating recent topics while staying at level A1.")

    def test_due_mistake_drives_topic_choice_after_reviews_before_weak_topics(self):
        state = default_state("Spanish")
        language_state(state)["weak_topics"] = ["past tense"]
        record_mistake(
            state,
            {
                "incorrect_form": "cuenta",
                "corrected_form": "la cuenta",
                "skill": "vocabulary",
                "topic": "cafe orders",
                "error_category": "vocabulary_missing",
                "source": "lesson_practice",
                "next_review": "2000-01-01T00:00:00+00:00",
            },
        )

        lesson = generate_lesson(state)

        self.assertEqual(choose_topic(state), "cafe orders")
        self.assertEqual(lesson["topic"], "cafe orders")
        self.assertEqual(lesson["selection_source"], "mistake_memory")
        self.assertIn("so this lesson practices cafe orders", lesson["reason"])

    def test_profile_separates_due_reviews_from_future_schedule(self):
        state = default_state("Spanish")
        queue = review_queue(state)
        queue["review_topic_past_tense"] = {
            "id": "review_topic_past_tense",
            "item_type": "topic",
            "target": "past tense",
                "topic": "past tense",
                "focus_skill": "conjugations",
                "due_at": "2000-01-01T00:00:00+00:00",
                "interval_days": 1,
                "missed_count": 2,
        }
        queue["review_topic_vocabulary"] = {
            "id": "review_topic_vocabulary",
            "item_type": "topic",
            "target": "vocabulary",
                "topic": "vocabulary",
                "focus_skill": "vocabulary",
                "due_at": "2999-01-01T00:00:00+00:00",
                "interval_days": 30,
                "missed_count": 0,
        }

        profile = profile_for(state)
        due_topics = [topic for _due_at, topic in due_review_items(state)]

        self.assertEqual(due_topics, ["past tense"])
        self.assertEqual(profile["review_count"], 2)
        self.assertEqual(profile["due_review_count"], 1)
        self.assertEqual(profile["next_review_topic"], "past tense")
        self.assertEqual(profile["next_review_due_at"], "2000-01-01T00:00:00+00:00")

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
        memory = conversation_memory(updated_state)
        self.assertEqual(memory["sessions_completed"], 1)
        self.assertEqual(memory["total_turns"], 3)
        self.assertIn(topic["topic"], memory["recent_topics"])
        self.assertEqual([event["type"] for event in language_state(updated_state)["history"][:2]], ["conversation_started", "learner_replied"])

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
        self.assertEqual(conversation_memory(updated_state)["last_video_context"]["primary_object"], "apple")

    def test_goal_driven_conversation_topic_and_video_still_wins(self):
        state = default_state("Spanish")
        conversation_memory(state)["next_conversation_goal"] = {
            "topic": "daily routines",
            "skill": "conjugations",
            "error_category": "wrong_conjugation",
            "instruction": "Ask simple daily-routine questions that force first-person present tense.",
            "source": "lesson",
            "set_at": "2026-07-08T00:00:00+00:00",
        }

        topic = choose_conversation_topic(state, video_on=False, video_object=None)
        opening = build_opening(topic, state)
        visual_topic = choose_conversation_topic(state, video_on=True, video_object="apple")

        self.assertEqual(topic["topic"], "daily routines")
        self.assertEqual(topic["goal"]["topic"], "daily routines")
        self.assertIn("Today, steer toward", opening)
        self.assertIn("first-person present tense", opening)
        self.assertIn("manzana", visual_topic["topic"])
        self.assertNotIn("goal", visual_topic)

    def test_tutor_prompts_and_realtime_instructions_include_lesson_goal(self):
        state = default_state("Spanish")
        goal = {
            "topic": "cafe orders",
            "skill": "vocabulary",
            "error_category": "vocabulary_missing",
            "instruction": "Use cafe-order phrases in a short role-play.",
            "source": "lesson",
            "set_at": "2026-07-08T00:00:00+00:00",
        }
        topic = {
            "topic": "likes and food",
            "complexity": "beginner",
            "opening": "Hola. ¿Te gusta la comida?",
            "support": "Model answer: Si, me gusta.",
            "keywords": ["gusta"],
            "goal": goal,
        }
        provider = PromptCaptureProvider()

        provider.conversation_tutor_reply(topic, state, [], "opening", build_opening(topic, state))
        realtime = _realtime_instructions(
            target_language="Spanish",
            level="A1",
            weak_topics=[],
            goal_instruction=goal["instruction"],
        )

        self.assertIn("Today, steer toward: Use cafe-order phrases in a short role-play.", PromptCaptureProvider.captured_prompt)
        self.assertIn("Today, steer toward: Use cafe-order phrases in a short role-play.", realtime)

    def test_advanced_conversation_uses_complex_topics(self):
        state = default_state("Spanish")
        profile_state(state)["current_level"] = "C1"

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

    def test_conversation_correction_records_real_mistake_and_maps_to_teachable_lesson_topic(self):
        state = default_state("Spanish")
        topic = {
            "topic": "likes and food",
            "complexity": "beginner",
            "support": "Model answer: Si, me gustan las manzanas.",
            "keywords": ["gusta", "manzana"],
        }
        score, feedback, correction, mistake = evaluate_reply_with_metadata(topic, "No se todavia", state)
        turn = {
            "turn_number": 1,
            "tutor_text": "¿Te gustan las manzanas?",
            "learner_text": "No se todavia",
            "topic": topic["topic"],
            "complexity": topic["complexity"],
            "video_on": False,
            "video_object": None,
            "score": score,
            "feedback": feedback,
            "correction": correction,
            "mistake": mistake,
        }

        apply_turn_progress(state, topic, turn, is_first_turn=True)

        mistake_record = next(iter(language_state(state)["mistake_memory"].values()))
        self.assertEqual(mistake_record["incorrect_form"], "No se todavia")
        self.assertEqual(mistake_record["corrected_form"], "Si, me gustan las manzanas.")
        self.assertEqual(mistake_record["topic"], "vocabulary")
        self.assertEqual(mistake_record["source"], "conversation")
        self.assertTrue(mistake_record["blocked_meaning"])
        self.assertIn("next_review", mistake_record)

        mistake_record["next_review"] = "2000-01-01T00:00:00+00:00"
        review_queue(state)[f"review_{mistake_record['id']}"]["due_at"] = "2000-01-01T00:00:00+00:00"
        lesson = generate_lesson(state)

        self.assertEqual(lesson["topic"], "vocabulary")
        self.assertEqual(lesson["selection_source"], "mistake_memory")
        self.assertIn("'No se todavia' -> 'Si, me gustan las manzanas.'", lesson["reason"])
        self.assertIn("conversation", lesson["reason"])

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

    def test_non_spanish_conversation_scaffold_uses_target_language(self):
        french_state = default_state("French")
        hindi_state = default_state("Hindi")
        conversation_memory(french_state)["recent_topics"] = ["weather", "likes and food"]
        conversation_memory(hindi_state)["recent_topics"] = ["weather", "likes and food"]

        french_topic = choose_conversation_topic(french_state, video_on=False, video_object=None)
        hindi_topic = choose_conversation_topic(hindi_state, video_on=False, video_object=None)
        french_help = build_follow_up(french_topic, "I don't understand", 0.2, 1, french_state)
        french_next = build_follow_up(french_topic, "Je m'appelle Johan.", 0.7, 1, french_state)
        hindi_next = build_follow_up(hindi_topic, "मेरा नाम जोहान है।", 0.7, 1, hindi_state)

        self.assertIn("Bonjour", build_opening(french_topic, french_state))
        self.assertIn("नमस्ते", build_opening(hindi_topic, hindi_state))
        self.assertIn("Je m'appelle", french_help)
        self.assertIn("phrase complète", french_next)
        self.assertIn("पूरा वाक्य", hindi_next)
        self.assertNotIn("Hace sol", french_help)
        self.assertNotIn("Muy bien", french_next)

    def test_non_spanish_visual_conversation_followups_and_auto_replies_are_localized(self):
        french_state = default_state("French")
        hindi_state = default_state("Hindi")
        french_topic = choose_conversation_topic(french_state, video_on=True, video_object="apple")
        hindi_topic = choose_conversation_topic(hindi_state, video_on=True, video_object="apple")

        french_follow_up = build_follow_up(french_topic, "C'est une pomme.", 0.7, 1, french_state)
        hindi_follow_up = build_follow_up(hindi_topic, "यह एक सेब है।", 0.7, 1, hindi_state)
        french_replies = visual_reply_options(french_topic["visual"], french_state)
        hindi_replies = visual_reply_options(hindi_topic["visual"], hindi_state)

        self.assertIn("pomme", french_follow_up)
        self.assertIn("सेब", hindi_follow_up)
        self.assertFalse(any("manzana" in reply or "Si," in reply for reply in french_replies))
        self.assertFalse(any("manzana" in reply or "Si," in reply for reply in hindi_replies))
        self.assertTrue(any("pomme" in reply for reply in french_replies))
        self.assertTrue(any("सेब" in reply for reply in hindi_replies))

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

    def test_desktop_bridge_openai_grading_overrides_local_for_open_questions(self):
        OpenAIGradingProvider.calls = 0
        OpenAIGradingProvider.seen_items = []
        with TemporaryDirectory() as tmpdir, patch("fluent_ai.desktop_bridge.OpenAIProvider", OpenAIGradingProvider):
            state_path = str(Path(tmpdir) / "progress.json")
            lesson = {
                "language": "Spanish",
                "level": "A1",
                "topic": "past tense",
                "focus_skill": "conjugations",
                "difficulty": "steady",
                "minutes": 10,
                "reason": "This is due for review because the last score was 2/6 and the interval is 1 day.",
            }
            quiz = [
                {
                    "type": "multiple_choice",
                    "skill": "vocabulary",
                    "topic": "past tense",
                    "prompt": "What does mercado mean?",
                    "answer": "market",
                    "choices": ["market", "friend", "house"],
                },
                {
                    "type": "fill_blank",
                    "skill": "conjugations",
                    "topic": "past tense",
                    "prompt": "Fill in the blank: Ayer ___ al mercado.",
                    "answer": "fui",
                    "acceptable_answers": ["fui"],
                },
                {
                    "type": "open_ended",
                    "skill": "conjugations",
                    "topic": "past tense",
                    "prompt": "Write one past-tense sentence.",
                    "answer": "Ayer fui al mercado.",
                    "keywords": ["ayer", "fui"],
                },
            ]

            result = lesson_submit(
                {
                    "state_path": state_path,
                    "language": "Spanish",
                    "lesson": lesson,
                    "quiz": quiz,
                    "answers": ["market", "voy", "Yo voy al mercado"],
                }
            )

            self.assertTrue(result["ok"])
            self.assertEqual(OpenAIGradingProvider.calls, 1)
            self.assertEqual([item["index"] for item in OpenAIGradingProvider.seen_items], [1, 2])
            self.assertIsNone(result["results"][0]["error_category"])
            self.assertEqual(result["results"][1]["error_category"], "wrong_tense")
            self.assertEqual(result["results"][1]["corrected_form"], "fui")
            self.assertEqual(result["results"][1]["severity"], "high")
            self.assertIn("past-tense", result["results"][1]["feedback"])
            self.assertEqual(result["results"][2]["error_category"], "wrong_tense")

    def test_desktop_bridge_partial_openai_grading_falls_back_per_item(self):
        PartialOpenAIGradingProvider.calls = 0
        with TemporaryDirectory() as tmpdir, patch("fluent_ai.desktop_bridge.OpenAIProvider", PartialOpenAIGradingProvider):
            state_path = str(Path(tmpdir) / "progress.json")
            lesson = {
                "language": "Spanish",
                "level": "A1",
                "topic": "introductions",
                "focus_skill": "vocabulary",
                "difficulty": "steady",
                "minutes": 10,
                "reason": "Your weakest current topic is introductions based on recent lesson and conversation evidence.",
            }
            quiz = [
                {
                    "type": "open_ended",
                    "skill": "vocabulary",
                    "topic": "introductions",
                    "prompt": "Write one short sentence about introductions.",
                    "answer": "Me llamo Ana.",
                    "keywords": ["llamo"],
                },
                {
                    "type": "fill_blank",
                    "skill": "conjugations",
                    "topic": "conjugations",
                    "prompt": "Fill in the blank: Yo ___ espanol.",
                    "answer": "hablo",
                    "acceptable_answers": ["hablo"],
                },
            ]

            result = lesson_submit(
                {
                    "state_path": state_path,
                    "language": "Spanish",
                    "lesson": lesson,
                    "quiz": quiz,
                    "answers": ["No se", "hablar"],
                }
            )

            self.assertTrue(result["ok"])
            self.assertEqual(PartialOpenAIGradingProvider.calls, 1)
            self.assertEqual(result["results"][0]["error_category"], "comprehension")
            self.assertEqual(result["results"][0]["feedback"], "Not quite. Use the meaning from the lesson.")
            self.assertEqual(result["results"][1]["error_category"], "wrong_conjugation")
            self.assertIn("verb form", result["results"][1]["feedback"])

    def test_desktop_bridge_malformed_openai_grading_falls_back_to_local(self):
        with TemporaryDirectory() as tmpdir, patch("fluent_ai.desktop_bridge.OpenAIProvider", FakeOpenAIProvider):
            state_path = str(Path(tmpdir) / "progress.json")
            lesson = {
                "language": "Spanish",
                "level": "A1",
                "topic": "conjugations",
                "focus_skill": "conjugations",
                "difficulty": "steady",
                "minutes": 10,
                "reason": "Your weakest current topic is conjugations based on recent lesson and conversation evidence.",
            }
            quiz = [
                {
                    "type": "fill_blank",
                    "skill": "conjugations",
                    "topic": "conjugations",
                    "prompt": "Fill in the blank: Yo ___ espanol.",
                    "answer": "hablo",
                    "acceptable_answers": ["hablo"],
                }
            ]

            result = lesson_submit(
                {
                    "state_path": state_path,
                    "language": "Spanish",
                    "lesson": lesson,
                    "quiz": quiz,
                    "answers": ["hablar"],
                }
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["results"][0]["error_category"], "wrong_conjugation")
            self.assertIn("verb form", result["results"][0]["feedback"])

    def test_openai_quiz_grading_rejects_malformed_category_entry(self):
        provider = InvalidEntryQuizProvider()
        state = default_state("Spanish")
        question = {
            "type": "open_ended",
            "skill": "vocabulary",
            "topic": "cafe orders",
            "prompt": "Write one cafe order.",
            "answer": "Quisiera un cafe, por favor.",
        }
        lesson = generate_lesson(state)
        items = [{"index": 0, "question": question, "answer": "no se"}]

        self.assertEqual(provider.evaluate_quiz_answers(state, lesson, items), [None])

    def test_openai_quiz_grading_rejects_malformed_overall_response(self):
        provider = MalformedQuizProvider()
        state = default_state("Spanish")
        question = {
            "type": "open_ended",
            "skill": "vocabulary",
            "topic": "cafe orders",
            "prompt": "Write one cafe order.",
            "answer": "Quisiera un cafe, por favor.",
        }
        lesson = generate_lesson(state)
        items = [{"index": 0, "question": question, "answer": "no se"}]

        self.assertIsNone(provider.evaluate_quiz_answers(state, lesson, items))

    def test_openai_conversation_evaluator_accepts_valid_strict_json(self):
        provider = ValidConversationEvaluatorProvider()
        state = default_state("Spanish")
        topic = {
            "topic": "daily routines",
            "complexity": "beginner",
            "support": "Model answer: Yo estudio por la manana.",
            "keywords": ["estudio", "manana"],
        }

        result = provider.evaluate_conversation_reply(state, topic, "yo estudiar por la manana")

        self.assertIsNotNone(result)
        self.assertEqual(result["score"], 0.4)
        self.assertEqual(result["incorrect_form"], "yo estudiar")
        self.assertEqual(result["corrected_form"], "Yo estudio")
        self.assertEqual(result["error_category"], "wrong_conjugation")

    def test_openai_conversation_evaluator_rejects_malformed_output(self):
        provider = MalformedQuizProvider()
        state = default_state("Spanish")
        topic = {
            "topic": "daily routines",
            "complexity": "beginner",
            "support": "Model answer: Yo estudio por la manana.",
            "keywords": ["estudio", "manana"],
        }

        self.assertIsNone(provider.evaluate_conversation_reply(state, topic, "yo estudiar por la manana"))

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

    def test_provider_conversation_grade_records_conjugation_mistake_and_summary(self):
        ConversationWrongConjugationProvider.calls = 0
        with TemporaryDirectory() as tmpdir, patch("fluent_ai.desktop_bridge.OpenAIProvider", ConversationWrongConjugationProvider):
            state_path = str(Path(tmpdir) / "progress.json")
            session = {
                "topic": {
                    "topic": "daily routines",
                    "complexity": "beginner",
                    "support": "Model answer: Yo estudio por la manana.",
                    "keywords": ["estudio", "manana"],
                    "speaking_confidence_before": 0.30,
                },
                "turns": [],
                "video_on": False,
                "video_object": None,
                "max_turns": 1,
            }

            reply = conversation_reply(
                {
                    "state_path": state_path,
                    "language": "Spanish",
                    "session": session,
                    "message": "yo estudiar por la manana",
                    "tutor_message": "¿Que haces por la manana?",
                }
            )

            persisted = load_state(Path(state_path), "Spanish")
            mistake = next(iter(language_state(persisted)["mistake_memory"].values()))
            selection = choose_topic_with_reason(persisted)
            lesson = generate_lesson(persisted)

        self.assertTrue(reply["ok"])
        self.assertEqual(ConversationWrongConjugationProvider.calls, 1)
        self.assertEqual(reply["turn"]["score"], 0.42)
        self.assertEqual(reply["turn"]["correction"], "Yo estudio por la manana.")
        self.assertEqual(reply["turn"]["mistake"]["incorrect_form"], "yo estudiar")
        self.assertEqual(reply["turn"]["mistake"]["corrected_form"], "Yo estudio")
        self.assertEqual(reply["turn"]["mistake"]["error_category"], "wrong_conjugation")
        self.assertEqual(mistake["incorrect_form"], "yo estudiar")
        self.assertEqual(mistake["corrected_form"], "Yo estudio")
        self.assertEqual(mistake["error_category"], "wrong_conjugation")
        self.assertEqual(mistake["skill"], "conjugations")
        self.assertEqual(mistake["topic"], "daily routines")
        self.assertLessEqual(datetime.fromisoformat(mistake["next_review"]), datetime.now(timezone.utc))
        self.assertEqual(review_queue(persisted)[f"review_{mistake['id']}"]["due_at"], mistake["next_review"])
        self.assertEqual(reply["post_call_summary"]["correction_to_remember"], "Yo estudio por la manana.")
        self.assertEqual(reply["post_call_summary"]["phrase_to_review"], "Yo estudio por la manana.")
        self.assertEqual(selection.source, "mistake_memory")
        self.assertEqual(selection.topic, "daily routines")
        self.assertEqual(lesson["selection_source"], "mistake_memory")
        self.assertIn("'yo estudiar' -> 'Yo estudio'", lesson["reason"])
        self.assertIn("conversation", lesson["reason"])

    def test_malformed_provider_conversation_grade_falls_back_to_local_evaluator(self):
        MalformedConversationGradeProvider.calls = 0
        with TemporaryDirectory() as tmpdir, patch("fluent_ai.desktop_bridge.OpenAIProvider", MalformedConversationGradeProvider):
            state_path = str(Path(tmpdir) / "progress.json")
            session = {
                "topic": {
                    "topic": "weather",
                    "complexity": "beginner",
                    "support": "Model answer: Hace sol.",
                    "keywords": ["hace", "sol"],
                },
                "turns": [],
                "video_on": False,
                "video_object": None,
                "max_turns": 2,
            }

            reply = conversation_reply(
                {
                    "state_path": state_path,
                    "language": "Spanish",
                    "session": session,
                    "message": "No se",
                    "tutor_message": "¿Que tiempo hace?",
                }
            )

        self.assertTrue(reply["ok"])
        self.assertEqual(MalformedConversationGradeProvider.calls, 1)
        self.assertEqual(reply["turn"]["score"], 0.2)
        self.assertEqual(reply["turn"]["correction"], "Hace sol.")
        self.assertEqual(reply["turn"]["mistake"]["error_category"], "other")

    def test_correct_provider_conversation_grade_does_not_record_mistake(self):
        CorrectConversationGradeProvider.calls = 0
        with TemporaryDirectory() as tmpdir, patch("fluent_ai.desktop_bridge.OpenAIProvider", CorrectConversationGradeProvider):
            state_path = str(Path(tmpdir) / "progress.json")
            session = {
                "topic": {
                    "topic": "daily routines",
                    "complexity": "beginner",
                    "support": "Model answer: Yo estudio por la manana.",
                    "keywords": ["estudio", "manana"],
                    "speaking_confidence_before": 0.30,
                },
                "turns": [],
                "video_on": False,
                "video_object": None,
                "max_turns": 1,
            }

            reply = conversation_reply(
                {
                    "state_path": state_path,
                    "language": "Spanish",
                    "session": session,
                    "message": "Yo estudio por la manana.",
                    "tutor_message": "¿Que haces por la manana?",
                }
            )
            persisted = load_state(Path(state_path), "Spanish")

        self.assertTrue(reply["ok"])
        self.assertEqual(CorrectConversationGradeProvider.calls, 1)
        self.assertIsNone(reply["turn"]["correction"])
        self.assertIsNone(reply["turn"]["mistake"])
        self.assertIsNone(reply["post_call_summary"]["correction_to_remember"])
        self.assertEqual(language_state(persisted)["mistake_memory"], {})

    def test_bridge_language_switch_preserves_per_language_state(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "progress.json"
            status({"state_path": str(path)})
            persisted = json.loads(path.read_text(encoding="utf-8"))
            persisted["languages"]["Spanish"]["profile"]["xp"] = 500
            path.write_text(json.dumps(persisted), encoding="utf-8")

            french = status({"state_path": str(path), "language": "french"})
            self.assertEqual(french["profile"]["language"], "French")
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["active_language"], "French")
            self.assertEqual(set(persisted["languages"]), {"Spanish", "French"})
            self.assertEqual(persisted["languages"]["Spanish"]["profile"]["xp"], 500)

            no_language = status({"state_path": str(path)})
            self.assertEqual(no_language["profile"]["language"], "French")
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["active_language"], "French")

            spanish = status({"state_path": str(path), "language": "spanish"})
            self.assertEqual(spanish["profile"]["language"], "Spanish")
            self.assertEqual(spanish["profile"]["xp"], 500)
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["active_language"], "Spanish")
            self.assertEqual(set(persisted["languages"]), {"Spanish", "French"})
            self.assertEqual(persisted["languages"]["Spanish"]["profile"]["xp"], 500)

    def test_bridge_turn_progress_delegates_to_shared_conversation_helper(self):
        state = default_state("Spanish")
        topic = {"topic": "introductions", "complexity": "beginner"}
        turn = {
            "turn_number": 1,
            "tutor_text": "Hola",
            "learner_text": "No se",
            "topic": "introductions",
            "complexity": "beginner",
            "video_on": False,
            "video_object": None,
            "score": 0.2,
            "feedback": "Try again.",
            "correction": "Me llamo Ana.",
        }

        apply_conversation_turn_progress(state, topic, turn, is_first_turn=True)

        types = [event["type"] for event in language_state(state)["history"]]
        self.assertEqual(types[:2], ["conversation_started", "learner_replied"])
        self.assertTrue(language_state(state)["mistake_memory"])

    def test_post_call_summary_fields_persistence_and_cap(self):
        state = default_state("Spanish")
        topic = {
            "topic": "weather",
            "complexity": "beginner",
            "support": "Model answer: Hace sol.",
            "keywords": ["hace", "sol"],
            "speaking_confidence_before": conversation_memory(state)["speaking_confidence"],
        }
        turn = {
            "turn_number": 1,
            "tutor_text": "¿Que tiempo hace?",
            "learner_text": "Hace sol hoy.",
            "topic": "weather",
            "complexity": "beginner",
            "video_on": False,
            "video_object": None,
            "score": 0.72,
            "feedback": "Good conversation turn.",
            "correction": None,
        }
        apply_turn_progress(state, topic, turn, is_first_turn=True)

        summary = build_post_call_summary(state, topic, [turn])

        self.assertEqual(summary["topic"], "weather")
        self.assertEqual(summary["turn_count"], 1)
        self.assertEqual(summary["average_score"], 0.72)
        self.assertIn("Hace sol hoy", summary["did_well"])
        self.assertIsNone(summary["correction_to_remember"])
        self.assertEqual(summary["phrase_to_review"], "Hace sol.")
        self.assertEqual(summary["confidence_change"], "improved")
        self.assertTrue(summary["ended_at"])

        for index in range(11):
            persisted = persist_post_call_summary(state, {**topic, "session_id": f"session_{index}"}, [turn])

        summaries = conversation_memory(state)["post_call_summaries"]
        self.assertEqual(len(summaries), 10)
        self.assertEqual(summaries[-1], persisted)
        self.assertEqual(summaries[0]["session_id"], "session_1")
        self.assertEqual(language_state(state)["history"][-1]["payload"]["post_call_summary"], persisted)

    def test_conversation_end_scores_and_persists_raw_voice_turns(self):
        with TemporaryDirectory() as tmpdir:
            state_path = str(Path(tmpdir) / "progress.json")
            save_state(Path(state_path), default_state("Spanish"))

            result = conversation_end(
                {
                    "state_path": state_path,
                    "language": "Spanish",
                    "topic": {
                        "topic": "weather",
                        "complexity": "beginner",
                        "support": "Model answer: Hace sol.",
                        "keywords": ["hace", "sol"],
                    },
                    "turns": [{"tutor_text": "¿Que tiempo hace?", "learner_text": "No se"}],
                }
            )

            persisted = load_state(Path(state_path), "Spanish")
            mistake = next(iter(language_state(persisted)["mistake_memory"].values()))
            self.assertTrue(result["ok"])
            self.assertEqual(result["post_call_summary"]["topic"], "weather")
            self.assertEqual(result["post_call_summary"]["turn_count"], 1)
            self.assertEqual(len(conversation_memory(persisted)["post_call_summaries"]), 1)
            self.assertEqual(mistake["incorrect_form"], "No se")
            self.assertEqual(mistake["topic"], "vocabulary")

    def test_conversation_end_empty_transcript_noops_without_summary_write(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "progress.json"
            save_state(path, default_state("Spanish"))

            result = conversation_end({"state_path": str(path), "language": "Spanish", "turns": []})
            persisted = load_state(path, "Spanish")

            self.assertTrue(result["ok"])
            self.assertIsNone(result["post_call_summary"])
            self.assertIn("Call ended with no scored turns.", result["logs"][0])
            self.assertEqual(conversation_memory(persisted)["post_call_summaries"], [])


if __name__ == "__main__":
    unittest.main()
