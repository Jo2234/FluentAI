from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Callable

from fluent_ai.agent import current_level
from fluent_ai.state import recalculate_weak_topics, utc_now


TOPIC_LADDER = {
    "A1": [
        {
            "topic": "introductions",
            "complexity": "beginner",
            "opening": "Hola, yo empiezo. ¿Como te llamas?",
            "support": "Model answer: Me llamo Ana.",
            "keywords": ["me", "llamo", "soy"],
        },
        {
            "topic": "weather",
            "complexity": "beginner",
            "opening": "Hola. ¿Que tiempo hace hoy?",
            "support": "Model answer: Hace sol.",
            "keywords": ["hace", "sol", "llueve", "frio", "calor"],
        },
        {
            "topic": "likes and food",
            "complexity": "beginner",
            "opening": "Hola. A mi me gustan las manzanas. ¿Te gustan las manzanas?",
            "support": "Model answer: Si, me gustan las manzanas.",
            "keywords": ["me", "gusta", "gustan", "manzana", "si", "no"],
        },
    ],
    "A2": [
        {
            "topic": "daily routines",
            "complexity": "early conversation",
            "opening": "Cuéntame: ¿que haces normalmente por la mañana?",
            "support": "Try: Me levanto, desayuno y estudio.",
            "keywords": ["levanto", "desayuno", "trabajo", "estudio", "manana"],
        },
        {
            "topic": "past weekend",
            "complexity": "early conversation",
            "opening": "Yo quiero saber de tu fin de semana. ¿Que hiciste ayer?",
            "support": "Try: Ayer fui al mercado.",
            "keywords": ["ayer", "fui", "comi", "hable", "vi"],
        },
    ],
    "B1": [
        {
            "topic": "opinions",
            "complexity": "intermediate",
            "opening": "Empecemos con una opinion. ¿Prefieres aprender con musica, videos o conversaciones? ¿Por que?",
            "support": "Give a reason with porque.",
            "keywords": ["prefiero", "porque", "creo", "conversaciones", "videos"],
        },
        {
            "topic": "work and goals",
            "complexity": "intermediate",
            "opening": "Hablemos de metas. ¿Como te ayuda el español en tu trabajo o en tu vida?",
            "support": "Try to connect your answer to a goal.",
            "keywords": ["ayuda", "trabajo", "vida", "meta", "quiero"],
        },
    ],
    "B2": [
        {
            "topic": "environment",
            "complexity": "upper-intermediate",
            "opening": "Quiero debatir contigo: ¿cual es el problema ambiental mas importante en tu ciudad?",
            "support": "Use opinion plus evidence.",
            "keywords": ["ambiental", "ciudad", "problema", "contaminacion", "energia"],
        },
        {
            "topic": "culture",
            "complexity": "upper-intermediate",
            "opening": "Hablemos de cultura. ¿Que costumbre de tu pais seria dificil explicar a un extranjero?",
            "support": "Use examples and comparison.",
            "keywords": ["cultura", "costumbre", "pais", "comparado", "extranjero"],
        },
    ],
    "C1": [
        {
            "topic": "politics and civic life",
            "complexity": "advanced",
            "opening": "Analicemos una idea: ¿deberian los gobiernos regular mas la inteligencia artificial?",
            "support": "Balance two sides of the argument.",
            "keywords": ["gobierno", "regular", "inteligencia", "artificial", "riesgo", "beneficio"],
        }
    ],
    "C2": [
        {
            "topic": "environmental policy",
            "complexity": "near-native",
            "opening": "Defiende una postura matizada: ¿como equilibrarias crecimiento economico y proteccion ambiental?",
            "support": "Use nuance, concession, and a concrete policy example.",
            "keywords": ["economico", "ambiental", "matiz", "politica", "equilibrio"],
        }
    ],
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


TutorReplyFn = Callable[[dict[str, Any], dict[str, Any], list[ConversationTurn], str, str], str | None]


def choose_conversation_topic(state: dict[str, Any], video_on: bool, video_object: str | None) -> dict[str, Any]:
    level = current_level(state)
    if video_on and video_object:
        visual = resolve_visible_object(video_object)
        if visual:
            return {
                "topic": f"visible object: {visual['spanish']}",
                "complexity": "visual beginner" if level in {"A1", "A2"} else "visual conversation",
                "opening": visual["prompt"],
                "support": f"Useful sentence: {visual['model']}",
                "keywords": visual["keywords"],
                "visual": visual,
            }

    candidates = TOPIC_LADDER.get(level, TOPIC_LADDER["A1"])
    recent = set(state.get("conversation_memory", {}).get("recent_topics", [])[-3:])
    fresh = [candidate for candidate in candidates if candidate["topic"] not in recent]
    return random.choice(fresh or candidates)


def resolve_visible_object(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    lowered = value.lower()
    for key, details in VISIBLE_OBJECTS.items():
        if key in lowered or details["spanish"] in lowered:
            resolved = details.copy()
            resolved["label"] = key
            return resolved
    return {
        "label": lowered,
        "spanish": lowered,
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
) -> tuple[list[ConversationTurn], dict[str, Any], dict[str, Any]]:
    topic = choose_conversation_topic(state, video_on, video_object)
    transcript: list[ConversationTurn] = []
    fallback_opening = build_opening(topic, state)
    tutor_text = _model_or_fallback(tutor_reply_fn, topic, state, transcript, "opening", fallback_opening)

    for index in range(1, turns + 1):
        learner_text = get_learner_reply(topic, state, index, mode, tutor_text)
        score, feedback, correction = evaluate_reply(topic, learner_text, state)
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
            )
        )
        fallback_follow_up = build_follow_up(topic, learner_text, score, index, state)
        tutor_text = _model_or_fallback(tutor_reply_fn, topic, state, transcript, "follow_up", fallback_follow_up)

    update_conversation_progress(state, topic, transcript, video_on, video_object)
    return transcript, state, topic


def _model_or_fallback(
    tutor_reply_fn: TutorReplyFn | None,
    topic: dict[str, Any],
    state: dict[str, Any],
    transcript: list[ConversationTurn],
    phase: str,
    fallback: str,
) -> str:
    if tutor_reply_fn is None:
        return fallback
    generated = tutor_reply_fn(topic, state, transcript, phase, fallback)
    return generated or fallback


def build_opening(topic: dict[str, Any], state: dict[str, Any]) -> str:
    level = current_level(state)
    if level in {"A1", "A2"}:
        return f"{topic['opening']} ({topic['support']})"
    return topic["opening"]


def get_learner_reply(topic: dict[str, Any], state: dict[str, Any], turn_number: int, mode: str, tutor_text: str) -> str:
    if mode == "interactive":
        print(f"\nTutor: {tutor_text}")
        return input("You: ").strip()
    return simulate_reply(topic, state, turn_number)


def simulate_reply(topic: dict[str, Any], state: dict[str, Any], turn_number: int) -> str:
    level = current_level(state)
    visual = topic.get("visual")
    if visual and level in {"A1", "A2"}:
        return random.choice(
            [
                f"Si, me gusta la {visual['spanish']}.",
                visual["model"],
                f"Es {visual['article']} {visual['spanish']}.",
            ]
        )

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


def evaluate_reply(topic: dict[str, Any], learner_text: str, state: dict[str, Any]) -> tuple[float, str, str | None]:
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
        return score, "Good conversation turn. You answered in a way I can build on.", None

    correction = correction_for(topic)
    return score, "Good attempt. I will simplify and give you a model sentence.", correction


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
    if asks_for_english_help(learner_text):
        correction = correction_for(topic)
        target_language = state.get("learner", {}).get("target_language", "Spanish")
        return (
            f"In English: it means you can answer with a simple phrase like '{correction}'. "
            f"In {target_language}, try: {correction}"
        )

    if score < 0.35:
        correction = correction_for(topic)
        return f"Bien, vamos paso a paso. Repite o adapta: {correction}"

    if topic.get("visual"):
        visual = topic["visual"]
        if turn_number == 1:
            return f"Muy bien. Ahora dime una frase mas: La {visual['spanish']} es..."
        return "Perfecto. Ahora usa esa palabra en una frase sobre ti."

    if level in {"A1", "A2"}:
        follow_ups = [
            "Muy bien. Ahora responde con una frase completa.",
            "Genial. ¿Puedes decir una cosa mas?",
            "Bien. Usa una palabra nueva de hoy.",
        ]
    elif level in {"B1", "B2"}:
        follow_ups = [
            "Interesante. Dame una razon concreta.",
            "Ahora compara esa idea con otra opcion.",
            "Buen punto. ¿Que ejemplo real puedes dar?",
        ]
    else:
        follow_ups = [
            "Desarrolla el matiz: ¿cual seria la objecion mas fuerte?",
            "Ahora responde como si estuvieras en un debate formal.",
            "Concreta una politica o consecuencia.",
        ]
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
    memory = state.setdefault("conversation_memory", {})
    previous_fluency = float(memory.get("fluency_score", 0.30))
    previous_confidence = float(memory.get("speaking_confidence", 0.30))
    memory["sessions_completed"] = int(memory.get("sessions_completed", 0)) + 1
    memory["total_turns"] = int(memory.get("total_turns", 0)) + len(transcript)
    memory["fluency_score"] = bounded(previous_fluency * 0.75 + average_score * 0.25)
    memory["speaking_confidence"] = bounded(previous_confidence + (0.035 if average_score >= 0.45 else -0.02))
    memory["recent_topics"] = (memory.get("recent_topics", []) + [topic["topic"]])[-8:]
    memory["last_video_object"] = video_object if video_on else None
    memory["last_session_at"] = utc_now()
    memory["next_speaking_goal"] = next_speaking_goal(state, average_score, topic)

    missed = [turn.correction for turn in transcript if turn.correction]
    memory["missed_phrases"] = (memory.get("missed_phrases", []) + missed)[-8:]

    speaking_delta = 0.035 if average_score >= 0.45 else -0.015
    state["skills"]["vocabulary"] = bounded(state["skills"].get("vocabulary", 0.30) + speaking_delta)
    state["skills"]["grammar"] = bounded(state["skills"].get("grammar", 0.30) + speaking_delta / 2)
    state["topic_mastery"][topic["topic"]] = bounded(state["topic_mastery"].get(topic["topic"], 0.30) + speaking_delta)
    state["weak_topics"] = recalculate_weak_topics(state)
    state["history"] = (
        state.get("history", [])
        + [
            {
                "mode": "conversation",
                "topic": topic["topic"],
                "complexity": topic["complexity"],
                "turns": len(transcript),
                "average_score": round(average_score, 2),
                "video_on": video_on,
                "video_object": video_object if video_on else None,
                "next_speaking_goal": memory["next_speaking_goal"],
            }
        ]
    )[-25:]


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


def normalize(value: str) -> str:
    return " ".join(value.lower().strip().strip(".,!?;:'\"").split())


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
    ]
    return any(phrase in normalized for phrase in help_phrases)


def bounded(value: float) -> float:
    return round(min(0.99, max(0.05, value)), 3)
