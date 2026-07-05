from __future__ import annotations

import copy
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fluent_ai.state import LEVELS, recalculate_weak_topics, utc_now


TOPICS_BY_LEVEL = {
    "A1": ["introductions", "cafe orders", "daily routines", "past tense", "conjugations", "vocabulary"],
    "A2": ["past tense", "shopping", "travel plans", "health symptoms", "object pronouns"],
    "B1": ["opinions", "workplace situations", "news summaries", "storytelling", "future plans"],
    "B2": ["debate", "professional goals", "culture", "problem solving", "hypotheticals"],
    "C1": ["nuance", "persuasion", "academic discussion", "idioms", "register"],
    "C2": ["subtle humor", "literary analysis", "specialized vocabulary", "rhetoric", "native-speed synthesis"],
}

LESSON_BANK = {
    "introductions": {
        "focus_skill": "vocabulary",
        "vocabulary": [
            ("me llamo", "my name is"),
            ("soy de", "I am from"),
            ("encantado", "delighted"),
            ("mucho gusto", "nice to meet you"),
            ("a que te dedicas", "what do you do"),
        ],
        "grammar": "Use 'ser' for identity and origin: 'Soy Ana' and 'Soy de Singapur.'",
        "examples": [
            ("Me llamo Ana.", "My name is Ana."),
            ("Soy de Singapur.", "I am from Singapore."),
            ("Mucho gusto.", "Nice to meet you."),
        ],
        "answers": {
            "mc": "Nice to meet you.",
            "fill_prompt": "___ de Singapur.",
            "fill": "Soy",
            "open": "Me llamo Ana.",
            "translation": "Soy de Singapur.",
        },
    },
    "cafe orders": {
        "focus_skill": "vocabulary",
        "vocabulary": [
            ("quisiera", "I would like"),
            ("un cafe", "a coffee"),
            ("un te", "a tea"),
            ("la cuenta", "the bill"),
            ("por favor", "please"),
        ],
        "grammar": "Use 'Quisiera...' for a polite request. Put 'por favor' at the end to soften the order.",
        "examples": [
            ("Quisiera un cafe, por favor.", "I would like a coffee, please."),
            ("La cuenta, por favor.", "The bill, please."),
            ("Me gustaria un te.", "I would like a tea."),
        ],
        "answers": {
            "mc": "the bill",
            "fill_prompt": "___ un cafe, por favor.",
            "fill": "Quisiera",
            "open": "Quisiera un cafe, por favor.",
            "translation": "Un te, por favor.",
        },
    },
    "daily routines": {
        "focus_skill": "grammar",
        "vocabulary": [
            ("me levanto", "I get up"),
            ("trabajo", "I work"),
            ("estudio", "I study"),
            ("todos los dias", "every day"),
            ("por la manana", "in the morning"),
        ],
        "grammar": "For daily routines, use present-tense verbs with time phrases: 'Estudio por la noche.'",
        "examples": [
            ("Me levanto a las siete.", "I get up at seven."),
            ("Trabajo todos los dias.", "I work every day."),
            ("Estudio por la noche.", "I study at night."),
        ],
        "answers": {
            "mc": "in the morning",
            "fill_prompt": "___ por la noche.",
            "fill": "Estudio",
            "open": "Trabajo todos los dias.",
            "translation": "Me levanto a las siete.",
        },
    },
    "past tense": {
        "focus_skill": "conjugations",
        "vocabulary": [
            ("ayer", "yesterday"),
            ("fui", "I went"),
            ("comi", "I ate"),
            ("hable", "I spoke"),
            ("vi", "I saw"),
        ],
        "grammar": "For completed past actions, use the preterite: 'hable', 'comi', 'fui', and 'vi.'",
        "examples": [
            ("Ayer fui al mercado.", "Yesterday I went to the market."),
            ("Comi con mi familia.", "I ate with my family."),
            ("Hable con mi amigo.", "I spoke with my friend."),
        ],
        "answers": {
            "mc": "yesterday",
            "fill_prompt": "Ayer ___ al mercado.",
            "fill": "fui",
            "open": "Ayer fui al mercado.",
            "translation": "Hable con mi amigo.",
        },
    },
    "conjugations": {
        "focus_skill": "conjugations",
        "vocabulary": [
            ("yo hablo", "I speak"),
            ("tu hablas", "you speak"),
            ("ella habla", "she speaks"),
            ("nosotros hablamos", "we speak"),
            ("ellos hablan", "they speak"),
        ],
        "grammar": "Regular -ar verbs change endings by subject: hablo, hablas, habla, hablamos, hablan.",
        "examples": [
            ("Yo hablo espanol.", "I speak Spanish."),
            ("Ella habla ingles.", "She speaks English."),
            ("Nosotros hablamos cada dia.", "We speak every day."),
        ],
        "answers": {
            "mc": "I speak",
            "fill_prompt": "Yo ___ espanol.",
            "fill": "hablo",
            "open": "Yo hablo espanol.",
            "translation": "Ella habla ingles.",
        },
    },
    "vocabulary": {
        "focus_skill": "vocabulary",
        "vocabulary": [
            ("casa", "house"),
            ("trabajo", "work"),
            ("comida", "food"),
            ("tiempo", "time"),
            ("amigo", "friend"),
        ],
        "grammar": "Pair new nouns with short sentences so vocabulary is learned in context.",
        "examples": [
            ("Mi casa es pequena.", "My house is small."),
            ("Tengo trabajo hoy.", "I have work today."),
            ("Mi amigo come comida rica.", "My friend eats tasty food."),
        ],
        "answers": {
            "mc": "friend",
            "fill_prompt": "Mi ___ es pequena.",
            "fill": "casa",
            "open": "Mi amigo come comida rica.",
            "translation": "Tengo trabajo hoy.",
        },
    },
}


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


def snapshot_progress(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "skills": copy.deepcopy(state.get("skills", {})),
        "topic_mastery": copy.deepcopy(state.get("topic_mastery", {})),
        "xp": state.get("learner", {}).get("xp", 0),
        "level": current_level(state),
    }


def current_level(state: dict[str, Any]) -> str:
    learner = state.get("learner", {})
    return learner.get("current_level") or learner.get("level", "A1")


def weakest_skill(state: dict[str, Any]) -> str:
    return min(state["skills"], key=state["skills"].get)


def performance_band(state: dict[str, Any]) -> str:
    history = state.get("history", [])[-3:]
    if not history:
        return "steady"

    scores = []
    for item in history:
        correct = item.get("correct_count", 0)
        total = max(1, item.get("total_questions", 1))
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
    queue = state.get("review_queue", {})
    if not isinstance(queue, dict):
        return due_items

    for topic, item in queue.items():
        if topic not in LESSON_BANK or not isinstance(item, dict):
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


def choose_topic(state: dict[str, Any]) -> str:
    due_review = next_due_review_topic(state)
    if due_review:
        return due_review

    level = current_level(state)
    level_topics = TOPICS_BY_LEVEL.get(level, TOPICS_BY_LEVEL["A1"])
    weak_topics = state.get("weak_topics", [])
    recent = set(state.get("recent_topics", [])[-3:])

    for topic in weak_topics:
        if topic in LESSON_BANK and topic not in recent:
            return topic

    fresh_topics = [topic for topic in level_topics if topic not in recent]
    return random.choice(fresh_topics or level_topics)


def generate_lesson(state: dict[str, Any]) -> dict[str, Any]:
    language = state["learner"]["target_language"]
    level = current_level(state)
    topic = choose_topic(state)
    bank = LESSON_BANK.get(topic, _generic_lesson_bank(language, topic)) if language == "Spanish" else _generic_lesson_bank(language, topic)
    focus_skill = bank["focus_skill"]
    difficulty = performance_band(state)

    return {
        "language": language,
        "level": level,
        "topic": topic,
        "focus_skill": focus_skill,
        "difficulty": difficulty,
        "minutes": state["preferences"].get("lesson_minutes", 10),
        "learning_goals": state["learner"].get("learning_goals", []),
        "vocabulary": bank["vocabulary"],
        "grammar_explanation": bank["grammar"],
        "examples": bank["examples"],
        "micro_task": f"Use one {language} sentence about {topic} before the next cycle.",
    }


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

    bank = LESSON_BANK.get(topic, _generic_lesson_bank(lesson["language"], topic))
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

    avg_skill = sum(state["skills"].values()) / len(state["skills"])
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
        correct = is_correct(question, answer)
        expected = question["answer"]
        feedback = feedback_for(question, answer, correct)
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


def feedback_for(question: dict[str, Any], answer: str, correct: bool) -> str:
    if correct:
        return f"Good retrieval. Keep using '{question['answer']}' in short personal sentences."

    if question["type"] == "fill_blank":
        return f"Close. The missing form was '{question['answer']}'. Review the pattern before the next round."
    if question["type"] == "open_ended":
        return f"Nice attempt. Include one lesson keyword or model phrase, such as '{question['answer']}'."
    return f"Review this item: the best answer was '{question['answer']}'."


def normalize(value: str) -> str:
    cleaned = value.lower().strip().rstrip(".!?")
    return " ".join(_normalize_word(word) for word in cleaned.split())


def _normalize_word(value: str) -> str:
    return value.lower().strip(".,!?;:'\"")


def update_progress(state: dict[str, Any], lesson: dict[str, Any], results: list[QuizResult]) -> dict[str, Any]:
    correct_count = sum(1 for result in results if result.correct)
    total = max(1, len(results))

    missed_topics: list[str] = []
    for result in results:
        skill_delta = 0.045 if result.correct else -0.025
        topic_delta = 0.050 if result.correct else -0.035
        state["skills"][result.skill] = _bounded_score(state["skills"].get(result.skill, 0.30) + skill_delta)
        state["topic_mastery"][result.topic] = _bounded_score(state["topic_mastery"].get(result.topic, 0.30) + topic_delta)
        if not result.correct and result.topic not in missed_topics:
            missed_topics.append(result.topic)

    learner = state["learner"]
    learner["xp"] = int(learner.get("xp", 0) + correct_count * 10 + 5)
    learner["current_level"] = level_from_mastery(sum(state["skills"].values()) / len(state["skills"]))
    learner["level"] = learner["current_level"]

    state["weak_topics"] = recalculate_weak_topics(state)
    for topic in reversed(missed_topics):
        if topic in state["weak_topics"]:
            state["weak_topics"].remove(topic)
        state["weak_topics"].insert(0, topic)
    state["weak_topics"] = state["weak_topics"][:4]

    state["recent_topics"] = (state.get("recent_topics", []) + [lesson["topic"]])[-8:]
    update_review_schedule(state, lesson, correct_count, total)
    state.setdefault("daily_summary", {})
    state["daily_summary"]["lessons_completed"] = int(state["daily_summary"].get("lessons_completed", 0) + 1)
    state["daily_summary"]["last_sent_at"] = utc_now()
    state["history"].append(
        {
            "topic": lesson["topic"],
            "focus_skill": lesson["focus_skill"],
            "difficulty": lesson["difficulty"],
            "correct_count": correct_count,
            "total_questions": total,
            "score": f"{correct_count}/{total}",
            "level_after": learner["current_level"],
            "weak_topics_after": state["weak_topics"],
            "adaptation": recommendation(state),
        }
    )
    state["history"] = state["history"][-25:]
    return state


def update_review_schedule(state: dict[str, Any], lesson: dict[str, Any], correct_count: int, total: int) -> None:
    queue = state.setdefault("review_queue", {})
    topic = lesson["topic"]
    score = correct_count / max(1, total)
    existing = queue.get(topic, {}) if isinstance(queue.get(topic), dict) else {}

    if score >= 0.85:
        previous_interval = int(existing.get("interval_days", 1) or 1)
        interval_days = min(30, max(2, previous_interval * 2))
        missed_count = 0
    else:
        interval_days = 1
        missed_count = int(existing.get("missed_count", 0) or 0) + 1

    due_at = datetime.now(timezone.utc) + timedelta(days=interval_days)
    queue[topic] = {
        "topic": topic,
        "focus_skill": lesson["focus_skill"],
        "due_at": due_at.replace(microsecond=0).isoformat(),
        "interval_days": interval_days,
        "missed_count": missed_count,
        "last_score": f"{correct_count}/{total}",
        "updated_at": utc_now(),
    }


def _bounded_score(score: float) -> float:
    return round(min(0.99, max(0.05, score)), 3)


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
    weak_topics = ", ".join(state.get("weak_topics", [])[:2])
    return f"Next cycle should stay at {level} and focus on {weak_topics or weakest_skill(state)}."


def progress_report(before: dict[str, Any], state: dict[str, Any]) -> str:
    skill_changes = []
    for skill, after_score in state.get("skills", {}).items():
        before_score = before.get("skills", {}).get(skill, after_score)
        skill_changes.append((skill, after_score - before_score))
    best_skill, best_delta = max(skill_changes, key=lambda item: item[1])
    percent = round(best_delta * 100)
    streak = state["learner"].get("streak_days", 1)
    completed = state.get("daily_summary", {}).get("lessons_completed", 0)
    if percent > 0:
        change = f"You improved {percent}% in {best_skill} this cycle."
    else:
        change = f"You protected your {best_skill} progress and found what to review next."
    return f"{change} Streak: {streak} days. Lessons completed: {completed}."
