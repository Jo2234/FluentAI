from __future__ import annotations

import random
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fluent_ai import curriculum
from fluent_ai.agent import current_level
from fluent_ai.state import (
    active_language,
    add_event,
    conversation_memory,
    language_state,
    recalculate_weak_topics,
    record_mistake,
    set_skill_score,
    set_topic_score,
    skill_scores,
    topic_scores,
    utc_now,
)


TOPIC_LADDER = curriculum.conversation_ladder("Spanish")
LANGUAGE_TOPIC_OVERRIDES = {
    "French": curriculum.conversation_ladder("French"),
    "Hindi": curriculum.conversation_ladder("Hindi"),
}

VISIBLE_OBJECTS = {
    "apple": {
        "spanish": "manzana",
        "article": "una",
        "model": "Esto es una manzana.",
        "prompt": "Veo una manzana. Esto es una manzana. ¿Te gusta la manzana?",
        "keywords": ["manzana", "gusta", "roja", "verde", "comer"],
    },
    "banana": {
        "spanish": "platano",
        "article": "un",
        "model": "Esto es un platano.",
        "prompt": "Veo un platano. Esto es un platano. ¿De que color es?",
        "keywords": ["platano", "amarillo", "gusta", "comer"],
    },
    "book": {
        "spanish": "libro",
        "article": "un",
        "model": "Esto es un libro.",
        "prompt": "Veo un libro. Esto es un libro. ¿Lees mucho?",
        "keywords": ["libro", "leo", "leer", "mucho", "poco"],
    },
    "cup": {
        "spanish": "taza",
        "article": "una",
        "model": "Esto es una taza.",
        "prompt": "Veo una taza. Esto es una taza. ¿Que bebes normalmente?",
        "keywords": ["taza", "bebo", "cafe", "te", "agua"],
    },
}


VISIBLE_OBJECT_TRANSLATIONS = {
    "French": {
        "apple": {"target_word": "pomme", "article": "une", "model": "C'est une pomme.", "prompt": "Je vois une pomme. C'est une pomme. Est-ce que tu aimes les pommes ?", "keywords": ["pomme", "aime", "rouge", "verte", "manger"]},
        "banana": {"target_word": "banane", "article": "une", "model": "C'est une banane.", "prompt": "Je vois une banane. C'est une banane. De quelle couleur est-elle ?", "keywords": ["banane", "jaune", "aime", "manger"]},
        "book": {"target_word": "livre", "article": "un", "model": "C'est un livre.", "prompt": "Je vois un livre. C'est un livre. Est-ce que tu lis beaucoup ?", "keywords": ["livre", "lis", "lire", "beaucoup", "peu"]},
        "cup": {"target_word": "tasse", "article": "une", "model": "C'est une tasse.", "prompt": "Je vois une tasse. C'est une tasse. Qu'est-ce que tu bois normalement ?", "keywords": ["tasse", "bois", "cafe", "the", "eau"]},
    },
    "Hindi": {
        "apple": {"target_word": "सेब", "article": "एक", "model": "यह एक सेब है।", "prompt": "मैं एक सेब देखता हूँ। यह एक सेब है। क्या आपको सेब पसंद है?", "keywords": ["सेब", "पसंद", "लाल", "हरा", "खाना"]},
        "banana": {"target_word": "केला", "article": "एक", "model": "यह एक केला है।", "prompt": "मैं एक केला देखता हूँ। यह एक केला है। यह किस रंग का है?", "keywords": ["केला", "पीला", "पसंद", "खाना"]},
        "book": {"target_word": "किताब", "article": "एक", "model": "यह एक किताब है।", "prompt": "मैं एक किताब देखता हूँ। यह एक किताब है। क्या आप बहुत पढ़ते हैं?", "keywords": ["किताब", "पढ़ता", "पढ़ना", "बहुत", "थोड़ा"]},
        "cup": {"target_word": "कप", "article": "एक", "model": "यह एक कप है।", "prompt": "मैं एक कप देखता हूँ। यह एक कप है। आप आम तौर पर क्या पीते हैं?", "keywords": ["कप", "पीता", "कॉफी", "चाय", "पानी"]},
    },
}


FOLLOW_UP_SCAFFOLDS = {
    "Spanish": {
        "low_score": "Bien, vamos paso a paso. Repite o adapta: {correction}",
        "visual_first": "Muy bien. Ahora dime una frase mas: La {target_word} es...",
        "visual_next": "Perfecto. Ahora usa esa palabra en una frase sobre ti.",
        "beginner": [
            "Muy bien. Ahora responde con una frase completa.",
            "Genial. ¿Puedes decir una cosa mas?",
            "Bien. Usa una palabra nueva de hoy.",
        ],
        "intermediate": [
            "Interesante. Dame una razon concreta.",
            "Ahora compara esa idea con otra opcion.",
            "Buen punto. ¿Que ejemplo real puedes dar?",
        ],
        "advanced": [
            "Desarrolla el matiz: ¿cual seria la objecion mas fuerte?",
            "Ahora responde como si estuvieras en un debate formal.",
            "Concreta una politica o consecuencia.",
        ],
    },
    "French": {
        "low_score": "Très bien, allons pas à pas. Répète ou adapte : {correction}",
        "visual_first": "Très bien. Maintenant, dis une phrase de plus : La {target_word} est...",
        "visual_next": "Parfait. Maintenant, utilise ce mot dans une phrase sur toi.",
        "beginner": [
            "Très bien. Maintenant, réponds avec une phrase complète.",
            "Super. Est-ce que tu peux dire une chose de plus ?",
            "Bien. Utilise un mot nouveau d'aujourd'hui.",
        ],
        "intermediate": [
            "Intéressant. Donne-moi une raison concrète.",
            "Maintenant, compare cette idée avec une autre option.",
            "Bon point. Quel exemple réel peux-tu donner ?",
        ],
        "advanced": [
            "Développe la nuance : quelle serait l'objection la plus forte ?",
            "Maintenant, réponds comme dans un débat formel.",
            "Donne une politique ou une conséquence concrète.",
        ],
    },
    "Hindi": {
        "low_score": "अच्छा, धीरे-धीरे चलते हैं। दोहराइए या बदलिए: {correction}",
        "visual_first": "बहुत अच्छा। अब एक और वाक्य कहिए: {target_word} ... है।",
        "visual_next": "बिलकुल सही। अब इस शब्द को अपने बारे में एक वाक्य में इस्तेमाल कीजिए।",
        "beginner": [
            "बहुत अच्छा। अब पूरा वाक्य बोलिए।",
            "शानदार। क्या आप एक और बात कह सकते हैं?",
            "अच्छा। आज का एक नया शब्द इस्तेमाल कीजिए।",
        ],
        "intermediate": [
            "दिलचस्प। एक ठोस कारण दीजिए।",
            "अब इस विचार की तुलना किसी दूसरे विकल्प से कीजिए।",
            "अच्छी बात। कोई वास्तविक उदाहरण दीजिए।",
        ],
        "advanced": [
            "थोड़ा और गहराई से बताइए: सबसे मजबूत आपत्ति क्या होगी?",
            "अब ऐसे जवाब दीजिए जैसे आप औपचारिक बहस में हों।",
            "कोई ठोस नीति या परिणाम बताइए।",
        ],
    },
}


class TutorGenerationError(RuntimeError):
    """Raised when the required OpenAI tutor response is unavailable."""


@dataclass
class ConversationTurn:
    turn_number: int
    tutor_text: str
    learner_text: str
    topic: str
    complexity: str
    video_on: bool
    video_object: str | None
    score: float
    feedback: str
    correction: str | None
    mistake: dict[str, Any] | None = None


TutorReplyFn = Callable[[dict[str, Any], dict[str, Any], list[ConversationTurn], str, str], str | None]
ConversationGradeFn = Callable[[dict[str, Any], dict[str, Any], str], dict[str, Any] | None]

ALLOWED_CONVERSATION_ERROR_CATEGORIES = {
    "vocabulary_missing",
    "wrong_conjugation",
    "wrong_tense",
    "word_order",
    "comprehension",
    "too_short",
    "unnatural",
}


def choose_conversation_topic(state: dict[str, Any], video_on: bool, video_object: str | None) -> dict[str, Any]:
    level = current_level(state)
    if video_on and video_object:
        visual = resolve_visible_object(video_object, active_language(state))
        if visual:
            return {
                "topic": f"visible object: {visual['target_word']}",
                "complexity": "visual beginner" if level in {"A1", "A2"} else "visual conversation",
                "opening": visual["prompt"],
                "support": f"Useful sentence: {visual['model']}",
                "keywords": visual["keywords"],
                "visual": visual,
            }

    goal = conversation_memory(state).get("next_conversation_goal")
    if isinstance(goal, dict) and goal.get("instruction"):
        goal_topic = _topic_for_conversation_goal(state, goal, level)
        if goal_topic:
            selected = dict(goal_topic)
            selected["goal"] = dict(goal)
            return selected

    candidates = conversation_topics_for(state, level)
    recent = set(conversation_memory(state).get("recent_topics", [])[-3:])
    fresh = [candidate for candidate in candidates if candidate["topic"] not in recent]
    return dict(random.choice(fresh or candidates))


def conversation_topics_for(state: dict[str, Any], level: str) -> list[dict[str, Any]]:
    language = active_language(state)
    ladder = curriculum.conversation_ladder(language)
    return ladder.get(level) or TOPIC_LADDER.get(level, TOPIC_LADDER["A1"])


def _topic_for_conversation_goal(state: dict[str, Any], goal: dict[str, Any], level: str) -> dict[str, Any] | None:
    goal_topic = normalize(str(goal.get("topic") or ""))
    current_level_topics = conversation_topics_for(state, level)
    for candidate in current_level_topics:
        if normalize(str(candidate.get("topic") or "")) == goal_topic:
            return candidate

    for candidate in _all_conversation_topics_for_language(state):
        if normalize(str(candidate.get("topic") or "")) == goal_topic:
            return candidate

    fallback_topic = _goal_fallback_topic_name(goal)
    if fallback_topic:
        for candidate in current_level_topics:
            if normalize(str(candidate.get("topic") or "")) == normalize(fallback_topic):
                return candidate
        for candidate in _all_conversation_topics_for_language(state):
            if normalize(str(candidate.get("topic") or "")) == normalize(fallback_topic):
                return candidate
    return None


def _all_conversation_topics_for_language(state: dict[str, Any]) -> list[dict[str, Any]]:
    language = active_language(state)
    ladder = curriculum.conversation_ladder(language)
    topics: list[dict[str, Any]] = []
    for level in LEVEL_ORDER:
        topics.extend(ladder.get(level) or TOPIC_LADDER.get(level, []))
    return topics


LEVEL_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"]


def _goal_fallback_topic_name(goal: dict[str, Any]) -> str | None:
    topic = normalize(str(goal.get("topic") or ""))
    skill = normalize(str(goal.get("skill") or ""))
    category = normalize(str(goal.get("error_category") or ""))
    explicit = {
        "cafe orders": "likes and food",
        "conjugations": "daily routines",
        "past tense": "past weekend",
        "vocabulary": "likes and food",
    }
    if topic in explicit:
        return explicit[topic]
    if skill == "conjugations" or category in {"wrong_conjugation", "wrong_tense"}:
        return "daily routines"
    if skill == "vocabulary" or category == "vocabulary_missing":
        return "likes and food"
    if category == "too_short":
        return "introductions"
    return None


def resolve_visible_object(value: str | None, language: str = "Spanish") -> dict[str, Any] | None:
    if not value:
        return None
    lowered = value.lower()
    for key, details in VISIBLE_OBJECTS.items():
        if key in lowered or details["spanish"] in lowered:
            resolved = details.copy()
            localized = VISIBLE_OBJECT_TRANSLATIONS.get(language, {}).get(key, {})
            resolved.update(localized)
            resolved["label"] = key
            resolved.setdefault("target_word", resolved["spanish"])
            return resolved
    return {
        "label": lowered,
        "spanish": lowered,
        "target_word": lowered,
        "article": "un",
        "model": f"Esto es {lowered}.",
        "prompt": f"Veo {lowered}. ¿Como se dice esto en español?",
        "keywords": [lowered],
    }


def run_conversation(
    state: dict[str, Any],
    turns: int,
    mode: str,
    video_on: bool,
    video_object: str | None,
    tutor_reply_fn: TutorReplyFn | None = None,
    conversation_grade_fn: ConversationGradeFn | None = None,
) -> tuple[list[ConversationTurn], dict[str, Any], dict[str, Any]]:
    confidence_before = float(conversation_memory(state).get("speaking_confidence", 0.30) or 0.30)
    topic = choose_conversation_topic(state, video_on, video_object)
    topic["speaking_confidence_before"] = confidence_before
    transcript: list[ConversationTurn] = []
    fallback_opening = build_opening(topic, state)
    tutor_text = _model_or_raise(tutor_reply_fn, topic, state, transcript, "opening", fallback_opening)

    for index in range(1, turns + 1):
        learner_text = get_learner_reply(topic, state, index, mode, tutor_text)
        score, feedback, correction, mistake = evaluate_reply_with_provider(
            topic,
            learner_text,
            state,
            conversation_grade_fn,
        )
        transcript.append(
            ConversationTurn(
                turn_number=index,
                tutor_text=tutor_text,
                learner_text=learner_text,
                topic=topic["topic"],
                complexity=topic["complexity"],
                video_on=video_on,
                video_object=video_object if video_on else None,
                score=score,
                feedback=feedback,
                correction=correction,
                mistake=mistake,
            )
        )
        fallback_follow_up = build_follow_up(topic, learner_text, score, index, state)
        tutor_text = _model_or_raise(tutor_reply_fn, topic, state, transcript, "follow_up", fallback_follow_up)

    update_conversation_progress(state, topic, transcript, video_on, video_object)
    return transcript, state, topic


def _model_or_raise(
    tutor_reply_fn: TutorReplyFn | None,
    topic: dict[str, Any],
    state: dict[str, Any],
    transcript: list[ConversationTurn],
    phase: str,
    fallback: str,
) -> str:
    if tutor_reply_fn is None:
        raise TutorGenerationError("OpenAI tutor generation is required for Conversation Mode.")
    generated = tutor_reply_fn(topic, state, transcript, phase, fallback)
    if not generated:
        raise TutorGenerationError("OpenAI tutor generation returned an empty response.")
    return generated


def build_opening(topic: dict[str, Any], state: dict[str, Any]) -> str:
    level = current_level(state)
    goal_guidance = _goal_guidance(topic)
    suffix = f" Tutor guidance: {goal_guidance}" if goal_guidance else ""
    if level in {"A1", "A2"}:
        return f"{topic['opening']} ({topic['support']}){suffix}"
    return f"{topic['opening']}{suffix}"


def get_learner_reply(topic: dict[str, Any], state: dict[str, Any], turn_number: int, mode: str, tutor_text: str) -> str:
    if mode == "interactive":
        print(f"\nTutor: {tutor_text}")
        return input("You: ").strip()
    return simulate_reply(topic, state, turn_number)


def simulate_reply(topic: dict[str, Any], state: dict[str, Any], turn_number: int) -> str:
    level = current_level(state)
    visual = topic.get("visual")
    if visual and level in {"A1", "A2"}:
        return random.choice(visual_reply_options(visual, state))

    if level == "A1":
        replies = ["Me llamo Ana.", "Hace sol hoy.", "Si, me gustan las manzanas.", "No se todavia."]
    elif level == "A2":
        replies = ["Ayer fui al mercado.", "Por la manana estudio español.", "Me gusta hablar de comida."]
    elif level in {"B1", "B2"}:
        replies = [
            "Prefiero conversaciones porque puedo practicar respuestas reales.",
            "Creo que la contaminacion es un problema importante en mi ciudad.",
            "Mi meta es hablar con mas confianza en reuniones.",
        ]
    else:
        replies = [
            "Depende del contexto: la regulacion puede proteger a la gente, pero tambien puede frenar la innovacion.",
            "Equilibraria la economia y el ambiente con incentivos claros y reglas graduales.",
        ]
    return replies[(turn_number - 1) % len(replies)]


def visual_reply_options(visual: dict[str, Any], state: dict[str, Any]) -> list[str]:
    language = active_language(state)
    target_word = visual["target_word"]
    article = visual["article"]
    if language == "French":
        return [
            f"Oui, j'aime la {target_word}.",
            visual["model"],
            f"C'est {article} {target_word}.",
        ]
    if language == "Hindi":
        return [
            f"हाँ, मुझे {target_word} पसंद है।",
            visual["model"],
            f"यह {article} {target_word} है।",
        ]
    return [
        f"Si, me gusta la {target_word}.",
        visual["model"],
        f"Es {article} {target_word}.",
    ]


def evaluate_reply(topic: dict[str, Any], learner_text: str, state: dict[str, Any]) -> tuple[float, str, str | None]:
    score, feedback, correction, _mistake = evaluate_reply_with_metadata(topic, learner_text, state)
    return score, feedback, correction


def evaluate_reply_with_metadata(topic: dict[str, Any], learner_text: str, state: dict[str, Any]) -> tuple[float, str, str | None, dict[str, Any] | None]:
    normalized = normalize(learner_text)
    keywords = [normalize(keyword) for keyword in topic.get("keywords", [])]
    keyword_hits = sum(1 for keyword in keywords if keyword and keyword in normalized)
    length_bonus = min(0.25, len(normalized.split()) / 40)
    level = current_level(state)
    target = 0.35 if level in {"A1", "A2"} else 0.55

    if not normalized or "no se" in normalized or "dont know" in normalized:
        score = 0.20
    else:
        score = min(0.95, 0.30 + keyword_hits * 0.18 + length_bonus)

    if score >= target:
        return score, "Good conversation turn. You answered in a way I can build on.", None, None

    correction = correction_for(topic)
    topic_name = str(topic.get("topic") or "conversation")
    mistake = {
        "incorrect_form": _trim_mistake_text(learner_text),
        "corrected_form": correction,
        "error_category": "other",
        "skill": "speaking",
        "topic": topic_name,
        "blocked_meaning": score < 0.30,
    }
    return score, "Good attempt. I will simplify and give you a model sentence.", correction, mistake


def evaluate_reply_with_provider(
    topic: dict[str, Any],
    learner_text: str,
    state: dict[str, Any],
    conversation_grade_fn: ConversationGradeFn | None,
) -> tuple[float, str, str | None, dict[str, Any] | None]:
    if conversation_grade_fn is not None:
        try:
            grade = conversation_grade_fn(state, topic, learner_text)
        except Exception:
            grade = None
        provider_result = _provider_grade_to_metadata(topic, learner_text, grade)
        if provider_result is not None:
            return provider_result
    return evaluate_reply_with_metadata(topic, learner_text, state)


def _provider_grade_to_metadata(
    topic: dict[str, Any],
    learner_text: str,
    grade: dict[str, Any] | None,
) -> tuple[float, str, str | None, dict[str, Any] | None] | None:
    if not isinstance(grade, dict):
        return None
    required = {
        "score",
        "understandable",
        "correction",
        "incorrect_form",
        "corrected_form",
        "error_category",
        "feedback",
        "blocked_meaning",
    }
    if set(grade) != required:
        return None
    score = grade.get("score")
    feedback = grade.get("feedback")
    blocked_meaning = grade.get("blocked_meaning")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= float(score) <= 1:
        return None
    if not isinstance(feedback, str) or not feedback.strip() or not isinstance(blocked_meaning, bool):
        return None

    category = grade.get("error_category")
    if category is not None:
        if not isinstance(category, str):
            return None
        category = category.strip().lower()
        if category not in ALLOWED_CONVERSATION_ERROR_CATEGORIES:
            return None

    correction = _clean_optional(grade.get("correction"), 260)
    incorrect = _clean_optional(grade.get("incorrect_form"), 120)
    corrected = _clean_optional(grade.get("corrected_form"), 120)
    if grade.get("correction") is not None and correction is None:
        return None
    if grade.get("incorrect_form") is not None and incorrect is None:
        return None
    if grade.get("corrected_form") is not None and corrected is None:
        return None

    if not any([correction, incorrect, corrected, category]):
        return float(score), " ".join(feedback.strip().split())[:260], None, None
    if not category or not correction:
        return None

    topic_name = str(topic.get("topic") or "conversation")
    mistake = {
        "incorrect_form": incorrect or _trim_mistake_text(learner_text),
        "corrected_form": corrected or correction,
        "error_category": category,
        "skill": _skill_for_conversation_error(category),
        "topic": topic_name,
        "blocked_meaning": blocked_meaning,
    }
    return float(score), " ".join(feedback.strip().split())[:260], correction, mistake


def _clean_optional(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.strip().split())
    return cleaned[:limit] if cleaned else None


def _skill_for_conversation_error(category: str) -> str:
    if category in {"wrong_conjugation", "wrong_tense"}:
        return "conjugations"
    if category == "vocabulary_missing":
        return "vocabulary"
    if category in {"word_order", "unnatural"}:
        return "grammar"
    return "speaking"


def correction_for(topic: dict[str, Any]) -> str:
    visual = topic.get("visual")
    if visual:
        return visual["model"]
    support = topic.get("support", "")
    if "Model answer:" in support:
        return support.replace("Model answer:", "").strip()
    if "Try:" in support:
        return support.replace("Try:", "").strip()
    return "Puedes responder con una frase corta y clara."


def build_follow_up(topic: dict[str, Any], learner_text: str, score: float, turn_number: int, state: dict[str, Any]) -> str:
    level = current_level(state)
    target_language = active_language(state)
    scaffold = FOLLOW_UP_SCAFFOLDS.get(target_language, FOLLOW_UP_SCAFFOLDS["Spanish"])
    if asks_for_english_help(learner_text):
        correction = correction_for(topic)
        return (
            f"In English: it means you can answer with a simple phrase like '{correction}'. "
            f"In {target_language}, try: {correction}"
        )

    if score < 0.35:
        correction = correction_for(topic)
        return scaffold["low_score"].format(correction=correction)

    if topic.get("visual"):
        visual = topic["visual"]
        if turn_number == 1:
            return scaffold["visual_first"].format(target_word=visual["target_word"])
        return scaffold["visual_next"]

    if level in {"A1", "A2"}:
        follow_ups = scaffold["beginner"]
    elif level in {"B1", "B2"}:
        follow_ups = scaffold["intermediate"]
    else:
        follow_ups = scaffold["advanced"]
    return follow_ups[(turn_number - 1) % len(follow_ups)]


def update_conversation_progress(
    state: dict[str, Any],
    topic: dict[str, Any],
    transcript: list[ConversationTurn],
    video_on: bool,
    video_object: str | None,
) -> None:
    if not transcript:
        return

    average_score = sum(turn.score for turn in transcript) / len(transcript)
    apply_turn_progress(
        state,
        topic,
        {
            "turns": [
                {
                    "turn_number": turn.turn_number,
                    "tutor_text": turn.tutor_text,
                    "learner_text": turn.learner_text,
                    "topic": turn.topic,
                    "complexity": turn.complexity,
                    "video_on": video_on,
                    "video_object": video_object if video_on else None,
                    "score": turn.score,
                    "feedback": turn.feedback,
                    "correction": turn.correction,
                    "mistake": turn.mistake,
                }
                for turn in transcript
            ],
            "score": average_score,
            "aggregate_turns": len(transcript),
            "video_on": video_on,
            "video_object": video_object if video_on else None,
            "fluency_weight": 0.25,
            "confidence_delta": 0.035 if average_score >= 0.45 else -0.02,
            "speaking_delta": 0.035 if average_score >= 0.45 else -0.015,
        },
        is_first_turn=True,
    )


def apply_turn_progress(
    state: dict[str, Any],
    topic: dict[str, Any],
    turn_dict: dict[str, Any],
    is_first_turn: bool,
) -> None:
    language = active_language(state)
    data = language_state(state, language)
    memory = conversation_memory(state, language)
    score = float(turn_dict["score"])
    topic_name = str(topic.get("topic") or turn_dict.get("topic") or "conversation")
    turn_events = turn_dict.get("turns") if isinstance(turn_dict.get("turns"), list) else [turn_dict]
    aggregate_turns = int(turn_dict.get("aggregate_turns", len(turn_events)) or len(turn_events))

    if is_first_turn:
        memory["sessions_completed"] = int(memory.get("sessions_completed", 0)) + 1
        memory["recent_topics"] = (memory.get("recent_topics", []) + [topic_name])[-8:]
        add_event(
            state,
            {
                "type": "conversation_started",
                "source": "conversation_mode",
                "summary": f"Started conversation on {topic_name}.",
                "payload": {
                    "topic": topic_name,
                    "complexity": topic.get("complexity"),
                    "video_on": bool(turn_dict.get("video_on")),
                    "video_object": turn_dict.get("video_object") if turn_dict.get("video_on") else None,
                },
            },
            language,
        )

    memory["total_turns"] = int(memory.get("total_turns", 0)) + aggregate_turns
    fluency_weight = float(turn_dict.get("fluency_weight", 0.15) or 0.15)
    memory["fluency_score"] = bounded(float(memory.get("fluency_score", 0.30)) * (1 - fluency_weight) + score * fluency_weight)
    confidence_delta = turn_dict.get("confidence_delta")
    if confidence_delta is None:
        confidence_delta = 0.025 if score >= 0.45 else -0.015
    memory["speaking_confidence"] = bounded(float(memory.get("speaking_confidence", 0.30)) + float(confidence_delta))
    context = memory.setdefault("last_video_context", {"summary": None, "primary_object": None, "confidence": None, "used_at": None})
    if turn_dict.get("video_on"):
        context["summary"] = turn_dict.get("video_object")
        context["primary_object"] = turn_dict.get("video_object")
        context["used_at"] = utc_now()
    else:
        context["summary"] = None
        context["primary_object"] = None
        context["confidence"] = None
        context["used_at"] = None
    memory["last_session_at"] = utc_now()
    memory["next_speaking_goal"] = next_speaking_goal(state, score, topic)

    corrections = [turn.get("correction") for turn in turn_events if isinstance(turn, dict) and turn.get("correction")]
    if corrections:
        memory["missed_phrases"] = (memory.get("missed_phrases", []) + corrections)[-8:]
    for turn in turn_events:
        if not isinstance(turn, dict) or not turn.get("correction"):
            continue
        mistake = turn.get("mistake") if isinstance(turn.get("mistake"), dict) else {}
        lesson_topic = conversation_topic_to_lesson_topic(str(mistake.get("topic") or topic_name))
        next_review = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        record_mistake(
            state,
            {
                "incorrect_form": str(mistake.get("incorrect_form") or turn.get("learner_text") or "")[:80],
                "corrected_form": str(mistake.get("corrected_form") or turn.get("correction")),
                "context": f"Conversation turn on {topic_name}.",
                "skill": str(mistake.get("skill") or "speaking"),
                "topic": lesson_topic,
                "error_category": str(mistake.get("error_category") or "other"),
                "blocked_meaning": bool(mistake.get("blocked_meaning", float(turn.get("score", score) or score) < 0.30)),
                "source": "conversation",
                "next_review": next_review,
            },
            language,
        )

    scores = skill_scores(state, language)
    topics = topic_scores(state, language)
    speaking_delta = float(turn_dict.get("speaking_delta", 0.025 if score >= 0.45 else -0.01))
    event = None
    for turn in turn_events:
        if not isinstance(turn, dict):
            continue
        event = add_event(
            state,
            {
                "type": "learner_replied",
                "source": "conversation_mode",
                "summary": f"Learner replied on {topic_name}.",
                "payload": {
                    "turn_number": turn.get("turn_number"),
                    "topic": topic_name,
                    "complexity": topic.get("complexity"),
                    "score": round(float(turn.get("score", score) or score), 2),
                    "feedback": turn.get("feedback"),
                    "correction": turn.get("correction"),
                    "video_on": bool(turn.get("video_on")),
                    "video_object": turn.get("video_object") if turn.get("video_on") else None,
                    "next_speaking_goal": memory["next_speaking_goal"],
                },
            },
            language,
        )
    event_id = event["id"] if event else None
    set_skill_score(
        state,
        "vocabulary",
        bounded(scores.get("vocabulary", 0.30) + speaking_delta),
        language,
        evidence={"event_id": event_id, "mode": "conversation", "topic": topic_name, "delta": speaking_delta, "note": "Conversation turn"},
    )
    set_skill_score(
        state,
        "grammar",
        bounded(scores.get("grammar", 0.30) + speaking_delta / 2),
        language,
        evidence={
            "event_id": event_id,
            "mode": "conversation",
            "topic": topic_name,
            "delta": round(speaking_delta / 2, 3),
            "note": "Conversation turn",
        },
    )
    set_topic_score(
        state,
        topic_name,
        bounded(topics.get(topic_name, 0.30) + speaking_delta),
        language,
        evidence={"event_id": event_id, "mode": "conversation", "topic": topic_name, "delta": speaking_delta, "note": "Conversation turn"},
    )
    data["weak_topics"] = recalculate_weak_topics(state, language=language)


def conversation_topic_to_lesson_topic(topic_name: str) -> str:
    normalized = normalize(topic_name)
    mapping = {
        "introductions": "introductions",
        "daily routines": "daily routines",
        "cafe orders": "cafe orders",
        "past weekend": "past tense",
        "past tense": "past tense",
        "likes and food": "vocabulary",
        "weather": "vocabulary",
    }
    if normalized.startswith("visible object"):
        return "vocabulary"
    return mapping.get(normalized, "vocabulary")


def build_post_call_summary(state: dict[str, Any], topic: dict[str, Any], turns: list[Any]) -> dict[str, Any]:
    scored_turns = [turn for turn in turns if _turn_score(turn) is not None]
    ended_at = utc_now()
    topic_name = str(topic.get("topic") or (scored_turns and _turn_value(scored_turns[0], "topic")) or "conversation")
    average_score = sum(float(_turn_score(turn) or 0.0) for turn in scored_turns) / max(1, len(scored_turns))
    best_turn = max(scored_turns, key=lambda turn: float(_turn_score(turn) or 0.0), default=None)
    correction = None
    for turn in reversed(scored_turns):
        correction = _turn_value(turn, "correction")
        if correction:
            break

    memory = conversation_memory(state)
    missed = memory.get("missed_phrases", []) if isinstance(memory.get("missed_phrases"), list) else []
    confidence_before = topic.get("speaking_confidence_before")
    try:
        confidence_delta = float(memory.get("speaking_confidence", 0.30)) - float(confidence_before)
    except (TypeError, ValueError):
        confidence_delta = 0.0
    if confidence_delta > 0.005:
        confidence_change = "improved"
    elif confidence_delta < -0.005:
        confidence_change = "dipped"
    else:
        confidence_change = "steady"

    next_goal = memory.get("next_conversation_goal")
    if isinstance(next_goal, dict) and next_goal.get("instruction"):
        next_practice = str(next_goal["instruction"])
    elif correction:
        next_practice = f"Review the model phrase '{correction}' in the next conversation."
    else:
        next_practice = str(memory.get("next_speaking_goal") or f"Keep practicing {topic_name}.")

    return {
        "session_id": str(topic.get("session_id") or f"conversation_{ended_at.replace(':', '').replace('-', '')}"),
        "topic": topic_name,
        "turn_count": len(scored_turns),
        "average_score": round(average_score, 3),
        "did_well": _did_well_sentence(best_turn, topic_name),
        "correction_to_remember": str(correction) if correction else None,
        "phrase_to_review": str(missed[-1]) if missed else correction_for(topic),
        "next_speaking_goal": str(memory.get("next_speaking_goal") or ""),
        "confidence_change": confidence_change,
        "next_conversation_should_practice": next_practice,
        "ended_at": ended_at,
    }


def persist_post_call_summary(state: dict[str, Any], topic: dict[str, Any], turns: list[Any]) -> dict[str, Any] | None:
    if not turns:
        return None
    summary = build_post_call_summary(state, topic, turns)
    memory = conversation_memory(state)
    memory["post_call_summaries"] = (memory.get("post_call_summaries", []) + [summary])[-10:]
    add_event(
        state,
        {
            "type": "progress_updated",
            "source": "conversation_mode",
            "summary": f"Post-call summary for {summary['topic']}: {summary['turn_count']} turns.",
            "payload": {
                "post_call_summary": summary,
            },
        },
    )
    return summary


def next_speaking_goal(state: dict[str, Any], average_score: float, topic: dict[str, Any]) -> str:
    level = current_level(state)
    if average_score < 0.35 and level in {"A1", "A2"}:
        return "Answer with one complete sentence using the model phrase."
    if average_score < 0.45:
        return f"Review useful phrases for {topic['topic']} before the next conversation."
    if level in {"A1", "A2"}:
        return "Add one extra detail after each basic answer."
    if level in {"B1", "B2"}:
        return "Give an opinion plus one reason in the next conversation."
    return "Use nuance, concession, and a concrete example in the next discussion."


def _goal_guidance(topic: dict[str, Any]) -> str:
    goal = topic.get("goal")
    if isinstance(goal, dict) and goal.get("instruction"):
        return f"Today, steer toward: {goal['instruction']}"
    return ""


def _trim_mistake_text(value: str) -> str:
    return " ".join(str(value or "").strip().split())[:80]


def _turn_score(turn: Any) -> float | None:
    value = _turn_value(turn, "score")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _turn_value(turn: Any, key: str, default: Any = None) -> Any:
    if isinstance(turn, dict):
        return turn.get(key, default)
    return getattr(turn, key, default)


def _did_well_sentence(turn: Any, topic_name: str) -> str:
    if turn is None:
        return f"You stayed engaged with the {topic_name} conversation."
    learner_text = str(_turn_value(turn, "learner_text", "") or "").strip()
    if learner_text:
        return f"You did well when you said '{learner_text[:80]}' because the tutor could build on it."
    return f"You did well by completing a turn on {topic_name}."


def normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.lower())
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    cleaned = "".join(char if char.isalnum() or char.isspace() else " " for char in ascii_text)
    return " ".join(cleaned.split())


def asks_for_english_help(value: str) -> bool:
    normalized = normalize(value)
    help_phrases = [
        "what does that mean",
        "what does it mean",
        "what does this mean",
        "in english",
        "translate",
        "translation",
        "i dont understand",
        "i do not understand",
        "dont understand",
        "do not understand",
        "what mean",
        "que significa",
        "no entiendo",
        "sorry what was that",
        "what was that",
        "say that again",
        "can you repeat",
        "could you repeat",
        "repeat that",
        "repite",
        "puedes repetir",
        "otra vez",
    ]
    return any(phrase in normalized for phrase in help_phrases)


def bounded(value: float) -> float:
    return round(min(0.99, max(0.05, value)), 3)
