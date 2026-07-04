from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]

DEFAULT_SKILLS = {
    "vocabulary": 0.34,
    "grammar": 0.28,
    "conjugations": 0.26,
    "reading": 0.32,
    "translation": 0.30,
}

DEFAULT_TOPIC_MASTERY = {
    "cafe orders": 0.34,
    "introductions": 0.36,
    "daily routines": 0.32,
    "past tense": 0.24,
    "conjugations": 0.25,
    "vocabulary": 0.34,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_state(language: str) -> dict[str, Any]:
    return {
        "learner": {
            "name": "Demo Learner",
            "target_language": language,
            "current_level": "A1",
            "level": "A1",
            "xp": 0,
            "streak_days": 1,
            "learning_goals": [
                "Hold a simple 5-minute conversation",
                "Build useful daily vocabulary",
                "Improve conjugation accuracy",
            ],
        },
        "weak_topics": ["past tense", "conjugations", "vocabulary"],
        "skills": DEFAULT_SKILLS.copy(),
        "topic_mastery": DEFAULT_TOPIC_MASTERY.copy(),
        "preferences": {
            "lesson_minutes": 10,
            "daily_quiz_questions": 6,
            "tone": "encouraging and specific",
        },
        "recent_topics": [],
        "review_queue": {},
        "history": [],
        "daily_summary": {
            "last_sent_at": None,
            "lessons_completed": 0,
        },
        "conversation_memory": {
            "sessions_completed": 0,
            "total_turns": 0,
            "fluency_score": 0.30,
            "speaking_confidence": 0.30,
            "recent_topics": [],
            "missed_phrases": [],
            "last_video_object": None,
            "next_speaking_goal": f"Answer simple questions in full {language} sentences.",
        },
        "updated_at": utc_now(),
    }


def load_state(path: Path, language: str) -> dict[str, Any]:
    if not path.exists():
        state = default_state(language)
        save_state(path, state)
        return state

    with path.open("r", encoding="utf-8") as file:
        state = json.load(file)

    return migrate_state(state, language)


def migrate_state(state: dict[str, Any], language: str) -> dict[str, Any]:
    state.setdefault("learner", {})
    learner = state["learner"]
    learner.setdefault("name", "Demo Learner")
    learner.setdefault("target_language", language)
    learner.setdefault("current_level", learner.get("level", "A1"))
    learner.setdefault("level", learner["current_level"])
    learner.setdefault("xp", 0)
    learner.setdefault("streak_days", 1)
    learner.setdefault(
        "learning_goals",
        [
            "Hold a simple 5-minute conversation",
            "Build useful daily vocabulary",
            "Improve conjugation accuracy",
        ],
    )

    state.setdefault("skills", {})
    if "conjugation" in state["skills"]:
        state["skills"]["conjugations"] = state["skills"].pop("conjugation")
    for skill, score in DEFAULT_SKILLS.items():
        state["skills"].setdefault(skill, score)

    state.setdefault("topic_mastery", {})
    for topic, score in DEFAULT_TOPIC_MASTERY.items():
        state["topic_mastery"].setdefault(topic, score)

    state.setdefault("weak_topics", recalculate_weak_topics(state))
    state.setdefault("preferences", {})
    state["preferences"].setdefault("lesson_minutes", 10)
    state["preferences"].setdefault("daily_quiz_questions", 6)
    state["preferences"].setdefault("tone", "encouraging and specific")
    state.setdefault("recent_topics", [])
    state.setdefault("review_queue", {})
    state.setdefault("history", [])
    state.setdefault("daily_summary", {"last_sent_at": None, "lessons_completed": 0})
    state.setdefault("conversation_memory", {})
    conversation_memory = state["conversation_memory"]
    conversation_memory.setdefault("sessions_completed", 0)
    conversation_memory.setdefault("total_turns", 0)
    conversation_memory.setdefault("fluency_score", 0.30)
    conversation_memory.setdefault("speaking_confidence", 0.30)
    conversation_memory.setdefault("recent_topics", [])
    conversation_memory.setdefault("missed_phrases", [])
    conversation_memory.setdefault("last_video_object", None)
    conversation_memory.setdefault(
        "next_speaking_goal",
        f"Answer simple questions in full {learner.get('target_language', language)} sentences.",
    )
    state.setdefault("updated_at", utc_now())
    return state


def recalculate_weak_topics(state: dict[str, Any], limit: int = 4) -> list[str]:
    candidates: list[tuple[str, float]] = []
    candidates.extend(state.get("topic_mastery", {}).items())
    candidates.extend(state.get("skills", {}).items())
    ordered = sorted(candidates, key=lambda item: item[1])

    weak_topics: list[str] = []
    for topic, _score in ordered:
        if topic not in weak_topics:
            weak_topics.append(topic)
        if len(weak_topics) >= limit:
            break
    return weak_topics


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = utc_now()
    with path.open("w", encoding="utf-8") as file:
        json.dump(state, file, indent=2, ensure_ascii=False)
        file.write("\n")
