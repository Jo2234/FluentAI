from __future__ import annotations

import copy
import random
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fluent_ai import curriculum
from fluent_ai.state import (
    LEVELS,
    active_language,
    add_event,
    conversation_memory,
    language_state,
    profile_state,
    recalculate_weak_topics,
    record_mistake,
    record_practice_session,
    review_queue,
    set_skill_score,
    set_topic_score,
    skill_scores,
    topic_scores,
    utc_now,
)


TOPICS_BY_LEVEL = curriculum.topics_by_level("Spanish")
LESSON_BANK = curriculum.lesson_bank("Spanish")


ALLOWED_ERROR_CATEGORIES = {
    "vocabulary_missing",
    "wrong_conjugation",
    "wrong_tense",
    "word_order",
    "comprehension",
    "too_short",
    "unnatural",
}

ERROR_SEVERITY = {
    "too_short": "high",
    "comprehension": "high",
    "vocabulary_missing": "medium",
    "wrong_conjugation": "medium",
    "wrong_tense": "medium",
    "word_order": "medium",
    "unnatural": "low",
}


@dataclass
class TopicSelection:
    topic: str
    source: str
    details: dict[str, Any]


@dataclass
class QuizResult:
    prompt: str
    expected: str
    actual: str
    skill: str
    topic: str
    question_type: str
    correct: bool
    feedback: str
    error_category: str | None = None
    corrected_form: str | None = None
    severity: str = "low"
    confidence: float = 1.0


def snapshot_progress(state: dict[str, Any]) -> dict[str, Any]:
    profile = profile_state(state)
    return {
        "skills": copy.deepcopy(skill_scores(state)),
        "topic_mastery": copy.deepcopy(topic_scores(state)),
        "xp": profile.get("xp", 0),
        "level": current_level(state),
    }


def current_level(state: dict[str, Any]) -> str:
    return str(profile_state(state).get("current_level") or "A1")


def weakest_skill(state: dict[str, Any]) -> str:
    scores = skill_scores(state)
    return min(scores, key=scores.get)


def performance_band(state: dict[str, Any]) -> str:
    history = [
        event
        for event in language_state(state).get("history", [])
        if isinstance(event, dict) and event.get("type") == "lesson_completed"
    ][-3:]
    if not history:
        return "steady"

    scores = []
    for event in history:
        payload = event.get("payload", {}) if isinstance(event.get("payload"), dict) else {}
        legacy = payload.get("legacy", {}) if isinstance(payload.get("legacy"), dict) else {}
        correct = payload.get("correct_count", legacy.get("correct_count", 0))
        total = max(1, payload.get("total_questions", legacy.get("total_questions", 1)))
        scores.append(correct / total)

    average = sum(scores) / len(scores)
    if average >= 0.8:
        return "harder"
    if average <= 0.5:
        return "easier"
    return "steady"


def due_review_items(state: dict[str, Any], now: datetime | None = None) -> list[tuple[datetime, str]]:
    """Return valid due review topics ordered by oldest due date first."""
    now = now or datetime.now(timezone.utc)
    due_items: list[tuple[datetime, str]] = []
    queue = review_queue(state)
    if not isinstance(queue, dict):
        return due_items

    for key, item in queue.items():
        if not isinstance(item, dict):
            continue
        if item.get("item_type") and item.get("item_type") != "topic":
            continue
        topic = str(item.get("target") or item.get("topic") or key)
        bank = _lesson_bank_for_language(active_language(state))
        if topic not in bank and topic not in LESSON_BANK:
            continue
        due_at = _parse_due_at(item.get("due_at"))
        if due_at and due_at <= now:
            due_items.append((due_at, topic))
    due_items.sort(key=lambda item: item[0])
    return due_items


def next_due_review_topic(state: dict[str, Any], now: datetime | None = None) -> str | None:
    due_items = due_review_items(state, now)
    if not due_items:
        return None
    return due_items[0][1]


def _due_review_selection(state: dict[str, Any], now: datetime | None = None) -> TopicSelection | None:
    due_items = due_review_items(state, now)
    if not due_items:
        return None

    due_at, topic = due_items[0]
    review_id = f"review_topic_{_slugify(topic)}"
    item = review_queue(state).get(review_id, {})
    if not isinstance(item, dict):
        item = {}
        for candidate in review_queue(state).values():
            if isinstance(candidate, dict) and str(candidate.get("target") or candidate.get("topic") or "") == topic:
                item = candidate
                break
    return TopicSelection(
        topic=topic,
        source="due_review",
        details={
            "due_at": due_at.isoformat(),
            "last_score": str(item.get("last_score") or "not recorded"),
            "interval_days": int(item.get("interval_days", item.get("review_interval_days", 1)) or 1),
        },
    )


def _parse_due_at(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def due_mistake_items(state: dict[str, Any], now: datetime | None = None) -> list[tuple[datetime, dict[str, Any]]]:
    now = now or datetime.now(timezone.utc)
    items: list[tuple[datetime, dict[str, Any]]] = []
    mistakes = language_state(state).get("mistake_memory", {})
    if not isinstance(mistakes, dict):
        return items

    for mistake in mistakes.values():
        if not isinstance(mistake, dict):
            continue
        topic = str(mistake.get("topic") or "").strip()
        if not topic:
            continue
        due_at = _parse_due_at(mistake.get("next_review"))
        if due_at and due_at <= now:
            items.append((due_at, mistake))
    items.sort(key=lambda item: (item[0], str(item[1].get("id") or "")))
    return items


def _mistake_memory_selection(state: dict[str, Any], now: datetime | None = None) -> TopicSelection | None:
    for due_at, mistake in due_mistake_items(state, now):
        topic = str(mistake.get("topic") or "").strip()
        if not topic:
            continue
        return TopicSelection(
            topic=topic,
            source="mistake_memory",
            details={
                "due_at": due_at.isoformat(),
                "mistake": copy.deepcopy(mistake),
            },
        )
    return None


def choose_topic_with_reason(state: dict[str, Any]) -> TopicSelection:
    due_review = _due_review_selection(state)
    if due_review:
        return due_review

    due_mistake = _mistake_memory_selection(state)
    if due_mistake:
        return due_mistake

    level = current_level(state)
    language = active_language(state)
    topics_for_language = curriculum.topics_by_level(language)
    level_topics = topics_for_language.get(level, topics_for_language.get("A1", TOPICS_BY_LEVEL["A1"]))
    bank = _lesson_bank_for_language(language)
    data = language_state(state)
    weak_topics = data.get("weak_topics", [])
    recent = set(data.get("recent_topics", [])[-3:])

    for topic in weak_topics:
        if topic in bank and topic not in recent:
            return TopicSelection(topic=topic, source="weak_topic", details={"topic": topic})

    fresh_topics = [topic for topic in level_topics if topic not in recent]
    topic = random.choice(fresh_topics or level_topics)
    return TopicSelection(topic=topic, source="rotation", details={"level": level})


def choose_topic(state: dict[str, Any]) -> str:
    return choose_topic_with_reason(state).topic


def lesson_reason_for(state: dict[str, Any], selection: TopicSelection) -> str:
    if selection.source == "due_review":
        score = selection.details.get("last_score") or "not recorded"
        interval = int(selection.details.get("interval_days", 1) or 1)
        day_word = "day" if interval == 1 else "days"
        return f"This is due for review because the last score was {score} and the interval is {interval} {day_word}."
    if selection.source == "mistake_memory":
        mistake = selection.details.get("mistake", {}) if isinstance(selection.details.get("mistake"), dict) else {}
        incorrect = str(mistake.get("incorrect_form") or "an earlier answer")
        corrected = str(mistake.get("corrected_form") or "the corrected form")
        source = str(mistake.get("source") or "practice").replace("_", " ")
        return f"You missed '{incorrect}' -> '{corrected}' in {source}, so this lesson practices {selection.topic}."
    if selection.source == "weak_topic":
        return f"Your weakest current topic is {selection.topic} based on recent lesson and conversation evidence."
    return f"This avoids repeating recent topics while staying at level {current_level(state)}."


def generate_lesson(state: dict[str, Any]) -> dict[str, Any]:
    language = active_language(state)
    level = current_level(state)
    selection = choose_topic_with_reason(state)
    topic = selection.topic
    bank = curriculum.topic_lesson(language, level, topic) or _generic_lesson_bank(language, topic)
    focus_skill = bank["focus_skill"]
    difficulty = performance_band(state)
    reason = lesson_reason_for(state, selection)

    lesson = {
        "language": language,
        "level": level,
        "topic": topic,
        "reason": reason,
        "selection_source": selection.source,
        "focus_skill": focus_skill,
        "difficulty": difficulty,
        "minutes": state["preferences"].get("lesson_minutes", 10),
        "learning_goals": profile_state(state).get("learning_goals", []),
        "vocabulary": bank["vocabulary"],
        "grammar_explanation": bank["grammar"],
        "examples": bank["examples"],
        "micro_task": f"Use one {language} sentence about {topic} before the next cycle.",
    }
    for field in ("vocabulary_rich", "examples_rich", "pronunciation_hints", "cultural_note", "romanization_available"):
        if field in bank:
            lesson[field] = copy.deepcopy(bank[field])
    return lesson


def generate_quiz(state: dict[str, Any], lesson: dict[str, Any]) -> list[dict[str, Any]]:
    requested_count = int(state["preferences"].get("daily_quiz_questions", 6))
    if lesson["difficulty"] == "easier":
        question_count = min(requested_count, 5)
    elif lesson["difficulty"] == "harder":
        question_count = max(requested_count, 8)
    else:
        question_count = requested_count
    question_count = min(8, max(5, question_count))

    topic = lesson["topic"]
    if lesson.get("source") == "openai" or lesson.get("language") != "Spanish":
        return _lesson_driven_quiz(lesson, question_count)

    bank = curriculum.topic_lesson(str(lesson.get("language") or "Spanish"), str(lesson.get("level") or "A1"), topic) or _generic_lesson_bank(lesson["language"], topic)
    answers = bank["answers"]
    vocab = bank["vocabulary"]
    first_word, first_meaning = vocab[0]

    questions = [
        {
            "type": "multiple_choice",
            "skill": "vocabulary",
            "topic": topic,
            "prompt": f"What does '{first_word}' mean?",
            "answer": first_meaning,
            "choices": _choices(first_meaning, ["friend", "the bill", "yesterday", "I speak"]),
        },
        {
            "type": "fill_blank",
            "skill": bank["focus_skill"],
            "topic": topic,
            "prompt": f"Fill in the blank: {answers['fill_prompt']}",
            "answer": answers["fill"],
            "acceptable_answers": [answers["fill"]],
        },
        {
            "type": "open_ended",
            "skill": bank["focus_skill"],
            "topic": topic,
            "prompt": f"Write one short sentence about {topic}.",
            "answer": answers["open"],
            "acceptable_answers": [answers["open"]],
            "keywords": _keywords(answers["open"]),
        },
        {
            "type": "multiple_choice",
            "skill": "grammar",
            "topic": topic,
            "prompt": "Which option best matches today's grammar pattern?",
            "answer": answers["translation"],
            "choices": _choices(answers["translation"], ["Cafe yo.", "Me Singapur.", "Ayer mercado yo."]),
        },
        {
            "type": "fill_blank",
            "skill": "vocabulary",
            "topic": topic,
            "prompt": f"Fill in the meaning: '{first_word}' means ___.",
            "answer": first_meaning,
            "acceptable_answers": [first_meaning],
        },
        {
            "type": "open_ended",
            "skill": "translation",
            "topic": topic,
            "prompt": f"Translate or reuse this idea in {lesson['language']}: '{answers['translation']}'",
            "answer": answers["translation"],
            "acceptable_answers": [answers["translation"]],
            "keywords": _keywords(answers["translation"]),
        },
        {
            "type": "multiple_choice",
            "skill": "reading",
            "topic": topic,
            "prompt": f"In the example '{bank['examples'][0][0]}', what is the main meaning?",
            "answer": bank["examples"][0][1],
            "choices": _choices(bank["examples"][0][1], ["I need a ticket.", "It is too expensive.", "She reads a book."]),
        },
        {
            "type": "open_ended",
            "skill": bank["focus_skill"],
            "topic": topic,
            "prompt": "Write a tiny personal answer using one lesson word.",
            "answer": answers["open"],
            "acceptable_answers": [answers["open"]],
            "keywords": [item[0].split(" ")[0] for item in vocab[:3]],
        },
    ]
    return questions[:question_count]


def _lesson_driven_quiz(lesson: dict[str, Any], question_count: int) -> list[dict[str, Any]]:
    language = str(lesson.get("language") or "Spanish")
    topic = str(lesson.get("topic") or "practice")
    focus_skill = str(lesson.get("focus_skill") or "vocabulary")
    vocab = _pair_items(lesson.get("vocabulary"), _generic_lesson_bank(language, topic)["vocabulary"])
    examples = _pair_items(lesson.get("examples"), _generic_lesson_bank(language, topic)["examples"])
    first_word, first_meaning = vocab[0]
    second_word, second_meaning = vocab[1] if len(vocab) > 1 else vocab[0]
    model_sentence, model_meaning = examples[0]
    second_sentence, _ = examples[1] if len(examples) > 1 else examples[0]

    questions = [
        {
            "type": "multiple_choice",
            "skill": "vocabulary",
            "topic": topic,
            "prompt": f"What does '{first_word}' mean?",
            "answer": first_meaning,
            "choices": _choices(first_meaning, ["friend", "the bill", "yesterday", "I speak"]),
        },
        {
            "type": "fill_blank",
            "skill": focus_skill,
            "topic": topic,
            "prompt": f"Fill in the {language} phrase for '{first_meaning}': ___.",
            "answer": first_word,
            "acceptable_answers": [first_word],
        },
        {
            "type": "open_ended",
            "skill": focus_skill,
            "topic": topic,
            "prompt": f"Write one short {language} sentence about {topic}.",
            "answer": model_sentence,
            "acceptable_answers": [model_sentence],
            "keywords": _keywords(model_sentence) or [first_word],
        },
        {
            "type": "multiple_choice",
            "skill": "reading",
            "topic": topic,
            "prompt": f"Which option is a natural {language} sentence from today's lesson?",
            "answer": second_sentence,
            "choices": _choices(second_sentence, [first_meaning, second_meaning, "I am not sure."]),
        },
        {
            "type": "fill_blank",
            "skill": "vocabulary",
            "topic": topic,
            "prompt": f"Fill in the meaning: '{second_word}' means ___.",
            "answer": second_meaning,
            "acceptable_answers": [second_meaning],
        },
        {
            "type": "open_ended",
            "skill": "translation",
            "topic": topic,
            "prompt": f"Translate or reuse this idea in {language}: '{model_meaning}'",
            "answer": model_sentence,
            "acceptable_answers": [model_sentence],
            "keywords": _keywords(model_sentence) or [first_word],
        },
        {
            "type": "multiple_choice",
            "skill": "grammar",
            "topic": topic,
            "prompt": f"In the example '{model_sentence}', what is the main meaning?",
            "answer": model_meaning,
            "choices": _choices(model_meaning, ["I need a ticket.", "It is too expensive.", "She reads a book."]),
        },
        {
            "type": "open_ended",
            "skill": focus_skill,
            "topic": topic,
            "prompt": "Write a tiny personal answer using one lesson word.",
            "answer": model_sentence,
            "acceptable_answers": [model_sentence],
            "keywords": [item[0].split(" ")[0] for item in vocab[:3]],
        },
    ]
    return questions[:question_count]


def _pair_items(value: Any, fallback: list[tuple[str, str]]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                first = str(item[0]).strip()
                second = str(item[1]).strip()
                if first and second:
                    pairs.append((first, second))
    return pairs or fallback


def _lesson_bank_for_language(language: str) -> dict[str, dict[str, Any]]:
    return curriculum.lesson_bank(language)


def _generic_lesson_bank(language: str, topic: str) -> dict[str, Any]:
    if language == "Hindi":
        return {
            "focus_skill": "vocabulary",
            "vocabulary": [
                ("नमस्ते", "hello"),
                ("मेरा नाम", "my name"),
                ("मुझे पसंद है", "I like"),
                ("पानी", "water"),
                ("आज", "today"),
            ],
            "grammar": f"Practice short Hindi phrases about {topic}. Use simple subject plus phrase patterns.",
            "examples": [
                ("नमस्ते, मेरा नाम जोहान है।", "Hello, my name is Johan."),
                ("मुझे पानी पसंद है।", "I like water."),
                ("आज मैं अभ्यास करता हूँ।", "Today I practice."),
            ],
            "answers": {
                "mc": "hello",
                "fill_prompt": "___, मेरा नाम जोहान है।",
                "fill": "नमस्ते",
                "open": "मुझे पानी पसंद है।",
                "translation": "आज मैं अभ्यास करता हूँ।",
            },
        }
    if language == "French":
        return {
            "focus_skill": "vocabulary",
            "vocabulary": [
                ("bonjour", "hello"),
                ("je m'appelle", "my name is"),
                ("j'aime", "I like"),
                ("l'eau", "water"),
                ("aujourd'hui", "today"),
            ],
            "grammar": f"Practice short French phrases about {topic}. Use simple present-tense sentence frames.",
            "examples": [
                ("Bonjour, je m'appelle Johan.", "Hello, my name is Johan."),
                ("J'aime l'eau.", "I like water."),
                ("Aujourd'hui, je pratique.", "Today I practice."),
            ],
            "answers": {
                "mc": "hello",
                "fill_prompt": "___, je m'appelle Johan.",
                "fill": "Bonjour",
                "open": "J'aime l'eau.",
                "translation": "Aujourd'hui, je pratique.",
            },
        }
    return {
        "focus_skill": "vocabulary",
        "vocabulary": [
            ("frase util", "useful phrase"),
            ("practica", "practice"),
            ("respuesta", "answer"),
            ("objetivo", "goal"),
            ("progreso", "progress"),
        ],
        "grammar": f"Practice {language} {topic} with one useful phrase and one short response.",
        "examples": [
            ("Esta es una frase util.", "This is a useful phrase."),
            ("Mi objetivo es practicar.", "My goal is to practice."),
            ("Veo mi progreso.", "I see my progress."),
        ],
        "answers": {
            "mc": "useful phrase",
            "fill_prompt": "___ es una frase util.",
            "fill": "Esta",
            "open": "Esta es una frase util.",
            "translation": "Mi objetivo es practicar.",
        },
    }


def _choices(answer: str, distractors: list[str]) -> list[str]:
    choices = [answer]
    for distractor in distractors:
        if distractor != answer and distractor not in choices:
            choices.append(distractor)
        if len(choices) == 4:
            break
    random.shuffle(choices)
    return choices


def _keywords(answer: str) -> list[str]:
    words = [_normalize_word(word) for word in answer.split()]
    return [word for word in words if len(word) >= 3][:4]


def answer_quiz(quiz: list[dict[str, Any]], state: dict[str, Any], mode: str) -> list[str]:
    if mode == "interactive":
        answers = []
        for index, question in enumerate(quiz, start=1):
            print(f"\nQ{index} [{question['type']}]. {question['prompt']}")
            for choice_index, choice in enumerate(question.get("choices", []), start=1):
                print(f"  {choice_index}. {choice}")
            answers.append(input("Your answer: ").strip())
        return answers

    scores = skill_scores(state)
    avg_skill = sum(scores.values()) / len(scores)
    correct_probability = min(0.9, max(0.35, avg_skill + 0.22))
    answers = []
    for question in quiz:
        if random.random() <= correct_probability:
            answers.append(question["answer"])
            continue

        if question["type"] == "multiple_choice":
            wrong_choices = [choice for choice in question.get("choices", []) if choice != question["answer"]]
            answers.append(random.choice(wrong_choices or ["I am not sure."]))
        elif question["type"] == "fill_blank":
            answers.append("no se")
        else:
            answers.append("No entiendo todavia.")
    return answers


def evaluate_answers(quiz: list[dict[str, Any]], answers: list[str]) -> list[QuizResult]:
    results = []
    for question, answer in zip(quiz, answers):
        category = categorize_error(question, answer)
        correct = is_correct(question, answer)
        expected = question["answer"]
        corrected_form = expected if (not correct or category == "unnatural") else None
        severity = ERROR_SEVERITY.get(category or "", "low")
        confidence = _category_confidence(category) if category else 1.0
        feedback = feedback_for(question, answer, correct, category, corrected_form)
        results.append(
            QuizResult(
                prompt=question["prompt"],
                expected=expected,
                actual=answer,
                skill=question["skill"],
                topic=question["topic"],
                question_type=question["type"],
                correct=correct,
                feedback=feedback,
                error_category=category,
                corrected_form=corrected_form,
                severity=severity,
                confidence=confidence,
            )
        )
    return results


def is_correct(question: dict[str, Any], answer: str) -> bool:
    normalized = normalize(answer)
    accepted = [normalize(value) for value in question.get("acceptable_answers", [question["answer"]])]
    if normalized in accepted:
        return True

    if question["type"] == "open_ended":
        keywords = [normalize(keyword) for keyword in question.get("keywords", [])]
        return bool(normalized) and any(keyword in normalized for keyword in keywords)

    return False


def categorize_error(question: dict[str, Any], answer: str) -> str | None:
    if _is_exactly_accepted(question, answer):
        return None

    question_type = str(question.get("type") or "")
    if question_type == "multiple_choice":
        return "vocabulary_missing"

    normalized = normalize(answer)
    expected = normalize(str(question.get("answer") or ""))
    answer_tokens = normalized.split()
    expected_tokens = expected.split()
    prompt = normalize(str(question.get("prompt") or ""))
    topic = normalize(str(question.get("topic") or ""))
    skill = normalize(str(question.get("skill") or ""))

    if question_type == "open_ended" and len(answer_tokens) < 2:
        return "too_short"
    if question_type == "fill_blank" and skill == "conjugations":
        return "wrong_conjugation"
    if "past tense" in f"{prompt} {topic}" and not _has_past_tense_marker(normalized, expected):
        return "wrong_tense"
    if _same_tokens_different_order(answer_tokens, expected_tokens):
        return "word_order"
    if question_type == "open_ended":
        keyword_overlap = _keyword_overlap(question, normalized)
        if keyword_overlap:
            return "unnatural"
        return "comprehension"
    return "vocabulary_missing"


def _is_exactly_accepted(question: dict[str, Any], answer: str) -> bool:
    normalized = normalize(answer)
    accepted = [normalize(value) for value in question.get("acceptable_answers", [question["answer"]])]
    return normalized in accepted


def _has_past_tense_marker(normalized_answer: str, normalized_expected: str) -> bool:
    markers = {"ayer", "fui", "comi", "comio", "hable", "vi", "pasado"}
    expected_markers = {token for token in normalized_expected.split() if token in markers}
    if expected_markers:
        return bool(expected_markers.intersection(normalized_answer.split()))
    return any(token in markers for token in normalized_answer.split())


def _same_tokens_different_order(answer_tokens: list[str], expected_tokens: list[str]) -> bool:
    if len(answer_tokens) < 2 or len(expected_tokens) < 2:
        return False
    if answer_tokens == expected_tokens:
        return False
    answer_set = set(answer_tokens)
    expected_set = set(expected_tokens)
    return answer_set == expected_set


def _keyword_overlap(question: dict[str, Any], normalized_answer: str) -> bool:
    keywords = [normalize(keyword) for keyword in question.get("keywords", [])]
    if not keywords:
        keywords = [token for token in normalize(str(question.get("answer") or "")).split() if len(token) >= 3]
    return any(keyword and keyword in normalized_answer for keyword in keywords)


def _category_confidence(category: str | None) -> float:
    return {
        "too_short": 0.99,
        "vocabulary_missing": 0.95,
        "wrong_conjugation": 0.92,
        "wrong_tense": 0.90,
        "word_order": 0.88,
        "comprehension": 0.86,
        "unnatural": 0.78,
    }.get(category or "", 0.75)


def feedback_for(
    question: dict[str, Any],
    answer: str,
    correct: bool,
    error_category: str | None = None,
    corrected_form: str | None = None,
) -> str:
    if correct:
        if error_category == "unnatural":
            corrected = corrected_form or str(question["answer"])
            return f"Understandable! A native speaker might say: '{corrected}'."
        return f"Good retrieval. Keep using '{question['answer']}' in short personal sentences."

    corrected = corrected_form or str(question["answer"])
    if error_category == "too_short":
        return f"Almost. Add a complete answer. A good model is '{corrected}'."
    if error_category == "vocabulary_missing":
        return f"Review the key word here. The best answer was '{corrected}'."
    if error_category == "wrong_conjugation":
        return f"Almost. The verb form changes here. Use '{corrected}'."
    if error_category == "wrong_tense":
        return f"Almost. This prompt needs the past-tense form. Use '{corrected}'."
    if error_category == "word_order":
        return f"Close. The words are familiar, but the order should be '{corrected}'."
    if error_category == "comprehension":
        return f"Not quite. The answer should show the meaning of the prompt, such as '{corrected}'."
    if error_category == "unnatural":
        return f"Good keyword, but make the full phrase natural: '{corrected}'."
    if question["type"] == "fill_blank":
        return f"Close. The missing form was '{question['answer']}'. Review the pattern before the next round."
    if question["type"] == "open_ended":
        return f"Nice attempt. Include one lesson keyword or model phrase, such as '{question['answer']}'."
    return f"Review this item: the best answer was '{question['answer']}'."


def normalize(value: str) -> str:
    cleaned = value.lower().strip().rstrip(".!?")
    return " ".join(_normalize_word(word) for word in cleaned.split())


def _normalize_word(value: str) -> str:
    stripped = value.lower().strip(".,!?;:'\"¿¡।")
    return _strip_latin_accents(stripped)


def _strip_latin_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    output: list[str] = []
    last_base_was_latin = False
    for char in normalized:
        if unicodedata.combining(char):
            if last_base_was_latin:
                continue
            output.append(char)
            continue
        output.append(char)
        last_base_was_latin = "LATIN" in unicodedata.name(char, "")
    return unicodedata.normalize("NFC", "".join(output))


def update_progress(state: dict[str, Any], lesson: dict[str, Any], results: list[QuizResult]) -> dict[str, Any]:
    correct_count = sum(1 for result in results if result.correct)
    total = max(1, len(results))
    language = active_language(state)
    data = language_state(state, language)
    memory = conversation_memory(state, language)
    profile = profile_state(state, language)
    before_skills = skill_scores(state, language)
    before_topics = topic_scores(state, language)

    missed_topics: list[str] = []
    skill_updates = dict(before_skills)
    topic_updates = dict(before_topics)
    outcomes = []
    for result in results:
        skill_delta = 0.045 if result.correct else -0.025
        topic_delta = 0.050 if result.correct else -0.035
        skill = "conjugations" if result.skill == "conjugation" else result.skill
        skill_updates[skill] = _bounded_score(skill_updates.get(skill, 0.30) + skill_delta)
        topic_updates[result.topic] = _bounded_score(topic_updates.get(result.topic, 0.30) + topic_delta)
        if not result.correct and result.topic not in missed_topics:
            missed_topics.append(result.topic)
        outcomes.append(
            {
                "prompt": result.prompt,
                "expected": result.expected,
                "actual": result.actual,
                "skill": skill,
                "topic": result.topic,
                "question_type": result.question_type,
                "correct": result.correct,
                "feedback": result.feedback,
                "error_category": result.error_category,
                "corrected_form": result.corrected_form,
                "severity": result.severity,
                "confidence": result.confidence,
            }
        )
        if not result.correct:
            next_review = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0).isoformat()
            record_mistake(
                state,
                {
                    "incorrect_form": result.actual,
                    "corrected_form": result.corrected_form or result.expected,
                    "error_category": result.error_category or "other",
                    "skill": skill,
                    "topic": result.topic,
                    "context": result.prompt,
                    "severity": result.severity,
                    "source": "lesson_practice",
                    "next_review": next_review,
                },
                language,
            )

    next_conversation_goal = _derive_next_conversation_goal(results)
    if next_conversation_goal:
        memory["next_conversation_goal"] = next_conversation_goal
    elif isinstance(memory.get("next_conversation_goal"), dict) and memory["next_conversation_goal"].get("source") == "lesson":
        memory["next_conversation_goal"] = None

    next_xp = int(profile.get("xp", 0) + correct_count * 10 + 5)
    next_level = level_from_mastery(sum(skill_updates.values()) / len(skill_updates))
    profile["xp"] = next_xp
    profile["current_level"] = next_level

    lesson_event = add_event(
        state,
        {
            "type": "lesson_completed",
            "source": "lesson_mode",
            "summary": f"Completed {lesson['topic']} lesson with score {correct_count}/{total}.",
            "payload": {
                "topic": lesson["topic"],
                "focus_skill": lesson["focus_skill"],
                "difficulty": lesson["difficulty"],
                "correct_count": correct_count,
                "total_questions": total,
                "score": f"{correct_count}/{total}",
                "level_after": next_level,
                "question_outcomes": outcomes,
            },
        },
        language,
    )
    for skill, after_score in skill_updates.items():
        before_score = before_skills.get(skill, 0.30)
        if after_score != before_score:
            set_skill_score(
                state,
                skill,
                after_score,
                language,
                evidence={
                    "event_id": lesson_event["id"],
                    "mode": "lesson",
                    "topic": lesson["topic"],
                    "delta": round(after_score - before_score, 3),
                    "note": f"Quiz result {correct_count}/{total}",
                },
            )
    for topic, after_score in topic_updates.items():
        before_score = before_topics.get(topic, 0.30)
        if after_score != before_score:
            set_topic_score(
                state,
                topic,
                after_score,
                language,
                evidence={
                    "event_id": lesson_event["id"],
                    "mode": "lesson",
                    "topic": topic,
                    "delta": round(after_score - before_score, 3),
                    "note": f"Quiz result {correct_count}/{total}",
                },
            )

    data["weak_topics"] = recalculate_weak_topics(state, language=language)
    for topic in reversed(missed_topics):
        if topic in data["weak_topics"]:
            data["weak_topics"].remove(topic)
        data["weak_topics"].insert(0, topic)
    data["weak_topics"] = data["weak_topics"][:4]

    data["recent_topics"] = (data.get("recent_topics", []) + [lesson["topic"]])[-8:]
    update_review_schedule(state, lesson, correct_count, total)
    update_mistake_review_schedule(state, lesson, results, language)
    record_practice_session(state, language)
    daily_summary = data.setdefault("daily_summary", {})
    daily_summary["lessons_completed"] = int(daily_summary.get("lessons_completed", 0) + 1)
    daily_summary["last_sent_at"] = utc_now()
    add_event(
        state,
        {
            "type": "progress_updated",
            "source": "lesson_mode",
            "summary": f"Progress updated after {lesson['topic']} lesson.",
            "payload": {
                "topic": lesson["topic"],
                "xp_after": next_xp,
                "level_after": next_level,
                "weak_topics_after": data["weak_topics"],
                "skill_deltas": {
                    skill: round(skill_updates[skill] - before_skills.get(skill, 0.30), 3)
                    for skill in skill_updates
                    if skill_updates[skill] != before_skills.get(skill, 0.30)
                },
                "topic_deltas": {
                    topic: round(topic_updates[topic] - before_topics.get(topic, 0.30), 3)
                    for topic in topic_updates
                    if topic_updates[topic] != before_topics.get(topic, 0.30)
                },
                "adaptation": recommendation(state),
                "next_conversation_goal": memory.get("next_conversation_goal"),
            },
        },
        language,
    )
    return state


def _derive_next_conversation_goal(results: list[QuizResult]) -> dict[str, Any] | None:
    misses = [result for result in results if not result.correct]
    if not misses:
        return None

    counts: dict[tuple[str, str], int] = {}
    first_seen: dict[tuple[str, str], QuizResult] = {}
    for result in misses:
        category = result.error_category or "other"
        topic = result.topic
        key = (category, topic)
        counts[key] = counts.get(key, 0) + 1
        first_seen.setdefault(key, result)

    category, topic = max(counts, key=lambda key: (counts[key], -list(first_seen).index(key)))
    result = first_seen[(category, topic)]
    skill = "conjugations" if result.skill == "conjugation" else result.skill
    return {
        "topic": topic,
        "skill": skill,
        "error_category": category,
        "instruction": _conversation_goal_instruction(category, topic, skill),
        "source": "lesson",
        "set_at": utc_now(),
    }


def _conversation_goal_instruction(error_category: str, topic: str, skill: str) -> str:
    if error_category == "wrong_conjugation" and topic == "daily routines":
        return "Ask simple daily-routine questions that force first-person present tense."
    if error_category == "vocabulary_missing" and topic == "cafe orders":
        return "Use cafe-order phrases in a short role-play."
    if error_category == "wrong_tense" or topic == "past tense":
        return "Ask about yesterday or last weekend so the learner practices past-tense answers."
    if error_category == "wrong_conjugation" or skill == "conjugations":
        return "Ask short questions that require the learner to choose the right verb form."
    if error_category == "word_order":
        return f"Ask short {topic} questions and model natural word order after each answer."
    if error_category == "too_short":
        return f"Prompt for complete-sentence answers about {topic}."
    if error_category == "comprehension":
        return f"Use very simple questions about {topic} and check meaning before moving on."
    if error_category == "vocabulary_missing" or skill == "vocabulary":
        return f"Recycle key {topic} vocabulary in a short role-play."
    return f"Steer the next conversation toward {topic} and correct the missed pattern gently."


def update_review_schedule(state: dict[str, Any], lesson: dict[str, Any], correct_count: int, total: int) -> None:
    queue = review_queue(state)
    topic = lesson["topic"]
    review_id = f"review_topic_{_slugify(topic)}"
    score = correct_count / max(1, total)
    existing = queue.get(review_id, {}) if isinstance(queue.get(review_id), dict) else {}

    if score >= 0.85:
        previous_interval = int(existing.get("interval_days", 1) or 1)
        interval_days = min(30, max(2, previous_interval * 2))
        missed_count = 0
    else:
        interval_days = 1
        missed_count = int(existing.get("missed_count", 0) or 0) + 1

    due_at = datetime.now(timezone.utc) + timedelta(days=interval_days)
    now = utc_now()
    queue[review_id] = {
        "id": review_id,
        "item_type": "topic",
        "target": topic,
        "topic": topic,
        "skill": lesson["focus_skill"],
        "focus_skill": lesson["focus_skill"],
        "source": "lesson",
        "due_at": due_at.replace(microsecond=0).isoformat(),
        "interval_days": interval_days,
        "missed_count": missed_count,
        "success_count": int(existing.get("success_count", 0) or 0) + (1 if score >= 0.85 else 0),
        "last_score": f"{correct_count}/{total}",
        "created_at": existing.get("created_at", now),
        "updated_at": now,
    }
    add_event(
        state,
        {
            "type": "review_scheduled",
            "source": "lesson_mode",
            "summary": f"Scheduled review for {topic}.",
            "payload": {
                "review_id": review_id,
                "topic": topic,
                "focus_skill": lesson["focus_skill"],
                "due_at": queue[review_id]["due_at"],
                "interval_days": interval_days,
                "last_score": f"{correct_count}/{total}",
            },
        },
    )


def update_mistake_review_schedule(
    state: dict[str, Any],
    lesson: dict[str, Any],
    results: list[QuizResult],
    language: str | None = None,
) -> None:
    if lesson.get("selection_source") != "mistake_memory":
        return

    lesson_topic = str(lesson.get("topic") or "").strip()
    if not lesson_topic:
        return

    language_data = language_state(state, language)
    mistakes = language_data.get("mistake_memory", {})
    if not isinstance(mistakes, dict):
        return

    related_results = [result for result in results if result.topic == lesson_topic]
    if not related_results:
        related_results = results
    related_total = max(1, len(related_results))
    related_correct = sum(1 for result in related_results if result.correct)
    practiced_successfully = related_correct > related_total / 2

    now_dt = datetime.now(timezone.utc).replace(microsecond=0)
    next_review = (now_dt + timedelta(days=1)).isoformat() if practiced_successfully else now_dt.isoformat()
    queue = review_queue(state, language)
    updated_at = utc_now()

    for mistake in mistakes.values():
        if not isinstance(mistake, dict):
            continue
        if str(mistake.get("topic") or "").strip() != lesson_topic:
            continue
        mistake["next_review"] = next_review
        mistake["last_practiced_at"] = updated_at
        mistake["last_practice_score"] = f"{related_correct}/{related_total}"
        review_id = f"review_{mistake.get('id')}"
        if isinstance(queue.get(review_id), dict):
            queue[review_id]["due_at"] = next_review
            queue[review_id]["updated_at"] = updated_at


def _bounded_score(score: float) -> float:
    return round(min(0.99, max(0.05, score)), 3)


def _slugify(value: Any) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
    return slug or "item"


def level_from_mastery(avg_skill: float) -> str:
    if avg_skill >= 0.92:
        return "C2"
    if avg_skill >= 0.82:
        return "C1"
    if avg_skill >= 0.70:
        return "B2"
    if avg_skill >= 0.58:
        return "B1"
    if avg_skill >= 0.45:
        return "A2"
    return "A1"


def recommendation(state: dict[str, Any]) -> str:
    level = current_level(state)
    weak_topics = ", ".join(language_state(state).get("weak_topics", [])[:2])
    return f"Next cycle should stay at {level} and focus on {weak_topics or weakest_skill(state)}."


def progress_report(before: dict[str, Any], state: dict[str, Any]) -> str:
    skill_changes = []
    for skill, after_score in skill_scores(state).items():
        before_score = before.get("skills", {}).get(skill, after_score)
        skill_changes.append((skill, after_score - before_score))
    best_skill, best_delta = max(skill_changes, key=lambda item: item[1])
    percent = round(best_delta * 100)
    data = language_state(state)
    streak = profile_state(state).get("streak_days", 1)
    completed = data.get("daily_summary", {}).get("lessons_completed", 0)
    if percent > 0:
        change = f"You improved {percent}% in {best_skill} this cycle."
    else:
        change = f"You protected your {best_skill} progress and found what to review next."
    return f"{change} Streak: {streak} days. Lessons completed: {completed}."
