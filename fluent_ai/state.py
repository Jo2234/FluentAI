from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]

DEFAULT_SKILLS = {
    "vocabulary": 0.34,
    "grammar": 0.28,
    "conjugations": 0.26,
    "listening": 0.30,
    "speaking": 0.30,
    "pronunciation": 0.30,
    "reading": 0.32,
    "writing": 0.30,
    "translation": 0.30,
    "fluency": 0.30,
}

DEFAULT_TOPIC_MASTERY = {
    "cafe orders": 0.34,
    "introductions": 0.36,
    "daily routines": 0.32,
    "past tense": 0.24,
    "conjugations": 0.25,
    "vocabulary": 0.34,
}

DEFAULT_GOALS = [
    "Hold a simple 5-minute conversation",
    "Build useful daily vocabulary",
    "Improve conjugation accuracy",
]

def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_state(language: str) -> dict[str, Any]:
    return _default_v2_state(language)


def load_state(path: Path, language: str | None = None) -> dict[str, Any]:
    default_language = language or "Spanish"
    if not path.exists():
        state = default_state(default_language)
        save_state(path, state)
        return state

    with path.open("r", encoding="utf-8") as file:
        state = json.load(file)

    return migrate_state(state, default_language)


def migrate_state(state: dict[str, Any], language: str) -> dict[str, Any]:
    if state.get("schema_version") == 2 and isinstance(state.get("languages"), dict):
        return _normalize_v2_state(state, language)
    return _migrate_v1_to_v2(state, language)


def active_language(state: dict[str, Any]) -> str:
    language = state.get("active_language")
    if isinstance(language, str) and language.strip():
        return language
    return "Spanish"


def language_state(state: dict[str, Any], language: str | None = None) -> dict[str, Any]:
    language = language or active_language(state)
    state.setdefault("languages", {})
    if language not in state["languages"] or not isinstance(state["languages"][language], dict):
        state["languages"][language] = _default_language_state(language)
    return _normalize_language_state(state["languages"][language], language, state.get("updated_at"))


def profile_state(state: dict[str, Any], language: str | None = None) -> dict[str, Any]:
    return language_state(state, language)["profile"]


def skill_scores(state: dict[str, Any], language: str | None = None) -> dict[str, float]:
    return {
        skill: _as_float(record.get("score"), DEFAULT_SKILLS.get(skill, 0.30))
        for skill, record in language_state(state, language).get("skills", {}).items()
        if isinstance(record, dict)
    }


def set_skill_score(
    state: dict[str, Any],
    skill: str,
    score: float,
    language: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> None:
    skill = "conjugations" if skill == "conjugation" else skill
    language_data = language_state(state, language)
    skills = language_data.setdefault("skills", {})
    record = _skill_record(skills.get(skill, DEFAULT_SKILLS.get(skill, 0.30)))
    previous = _as_float(record.get("score"), DEFAULT_SKILLS.get(skill, 0.30))
    bounded = _bounded_score(score)
    record["score"] = bounded
    if bounded > previous:
        record["trend"] = "up"
    elif bounded < previous:
        record["trend"] = "down"
    else:
        record["trend"] = "flat"
    record["last_practiced"] = utc_now()
    if evidence:
        record["evidence"] = (record.get("evidence", []) + [copy.deepcopy(evidence)])[-8:]
    else:
        record.setdefault("evidence", [])
    skills[skill] = record
    language_data["updated_at"] = utc_now()


def topic_scores(state: dict[str, Any], language: str | None = None) -> dict[str, float]:
    return {
        topic: _as_float(record.get("recognition"), DEFAULT_TOPIC_MASTERY.get(topic, 0.30))
        for topic, record in language_state(state, language).get("topic_mastery", {}).items()
        if isinstance(record, dict)
    }


def set_topic_score(
    state: dict[str, Any],
    topic: str,
    score: float,
    language: str | None = None,
    modality: str = "recognition",
    evidence: dict[str, Any] | None = None,
) -> None:
    language_data = language_state(state, language)
    topics = language_data.setdefault("topic_mastery", {})
    record = _topic_record(topics.get(topic, DEFAULT_TOPIC_MASTERY.get(topic, 0.30)))
    record[modality] = _bounded_score(score)
    if evidence:
        record["evidence"] = (record.get("evidence", []) + [copy.deepcopy(evidence)])[-8:]
    else:
        record.setdefault("evidence", [])
    topics[topic] = record
    language_data["updated_at"] = utc_now()


def conversation_memory(state: dict[str, Any], language: str | None = None) -> dict[str, Any]:
    return language_state(state, language)["conversation_memory"]


def review_queue(state: dict[str, Any], language: str | None = None) -> dict[str, Any]:
    return language_state(state, language)["review_queue"]


def append_history_event(state: dict[str, Any], event: dict[str, Any], language: str | None = None) -> None:
    add_event(state, event, language)


def record_mistake(state: dict[str, Any], mistake: dict[str, Any], language: str | None = None) -> dict[str, Any]:
    language_data = language_state(state, language)
    mistake_memory = language_data.setdefault("mistake_memory", {})
    incorrect = str(mistake.get("incorrect_form", ""))
    corrected = str(mistake.get("corrected_form", ""))
    skill = str(mistake.get("skill", "other") or "other")
    topic = str(mistake.get("topic", "general") or "general")
    mistake_id = mistake.get("id") or f"mistake_{_slugify('_'.join([incorrect, corrected, skill, topic]))}"
    now = utc_now()
    existing = mistake_memory.get(mistake_id, {})
    next_review = mistake.get("next_review", existing.get("next_review"))
    if not next_review:
        next_review = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0).isoformat()
    record = {
        "id": mistake_id,
        "incorrect_form": incorrect,
        "corrected_form": corrected,
        "context": str(mistake.get("context", existing.get("context", ""))),
        "skill": skill,
        "topic": topic,
        "error_category": str(mistake.get("error_category", existing.get("error_category", "other"))),
        "first_seen": existing.get("first_seen", now),
        "last_seen": now,
        "frequency": int(existing.get("frequency", 0) or 0) + 1,
        "severity": str(mistake.get("severity", existing.get("severity", "medium"))),
        "blocked_meaning": bool(mistake.get("blocked_meaning", existing.get("blocked_meaning", False))),
        "speech_recurrence": bool(mistake.get("speech_recurrence", existing.get("speech_recurrence", False))),
        "next_review": next_review,
    }
    if "source" in mistake:
        record["source"] = mistake["source"]
    mistake_memory[mistake_id] = record
    review_id = f"review_{mistake_id}"
    queue = language_data.setdefault("review_queue", {})
    existing_review = queue.get(review_id, {}) if isinstance(queue.get(review_id), dict) else {}
    queue[review_id] = {
        "id": review_id,
        "item_type": "mistake",
        "target": topic,
        "topic": topic,
        "skill": skill,
        "source": record.get("source", "mistake_memory"),
        "due_at": next_review,
        "mistake_id": mistake_id,
        "created_at": existing_review.get("created_at", now),
        "updated_at": now,
    }
    language_data["updated_at"] = now
    return record


def add_event(state: dict[str, Any], event: dict[str, Any], language: str | None = None) -> dict[str, Any]:
    language = language or active_language(state)
    language_data = language_state(state, language)
    event_record = copy.deepcopy(event)
    event_record.setdefault("type", "progress_updated")
    event_record.setdefault("language", language)
    event_record.setdefault("occurred_at", utc_now())
    event_record.setdefault("source", "state")
    event_record.setdefault("payload", {})
    event_record.setdefault("id", _next_event_id(state))

    language_data.setdefault("history", []).append(copy.deepcopy(event_record))
    language_data["history"] = language_data["history"][-300:]
    state.setdefault("events", []).append(copy.deepcopy(event_record))
    state["events"] = state["events"][-1000:]
    return event_record


def recalculate_weak_topics(state: dict[str, Any], limit: int = 4, language: str | None = None) -> list[str]:
    candidates: list[tuple[str, float]] = []
    candidates.extend((topic, _as_float(score, 0.30)) for topic, score in topic_scores(state, language).items())
    candidates.extend((skill, _as_float(score, 0.30)) for skill, score in skill_scores(state, language).items())
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
    language_state(state)["updated_at"] = state["updated_at"]
    _normalize_event_counter(state)
    _cap_events(state)
    with path.open("w", encoding="utf-8") as file:
        json.dump(state, file, indent=2, ensure_ascii=False)
        file.write("\n")


def _default_v2_state(language: str) -> dict[str, Any]:
    now = utc_now()
    return {
        "schema_version": 2,
        "learner": {
            "id": "local-demo-learner",
            "display_name": "Demo Learner",
            "native_language": None,
            "motivation": "",
            "active_goals": DEFAULT_GOALS.copy(),
            "preferred_session_length_minutes": 10,
            "preferred_correction_style": "gentle",
            "preferred_tutor_tone": "encouraging and specific",
            "accessibility": {"transliteration": False, "larger_text": False, "reduced_motion": False},
            "created_at": now,
        },
        "active_language": language,
        "languages": {language: _default_language_state(language, now)},
        "preferences": {
            "lesson_minutes": 10,
            "daily_quiz_questions": 6,
            "tone": "encouraging and specific",
            "voice": "alloy",
            "video_default": "off",
        },
        "privacy": {
            "local_only": True,
            "store_raw_audio": False,
            "store_raw_video": False,
            "store_camera_summaries": True,
            "allow_export": True,
            "allow_delete": True,
            "allow_language_reset": True,
            "last_exported_at": None,
        },
        "events": [],
        "event_counter": 0,
        "updated_at": now,
    }


def _default_language_state(language: str, now: str | None = None) -> dict[str, Any]:
    now = now or utc_now()
    return {
        "profile": {
            "target_language": language,
            "current_level": "A1",
            "level_confidence": 0.45,
            "xp": 0,
            "streak_days": 1,
            "learning_goals": DEFAULT_GOALS.copy(),
            "last_session_at": None,
        },
        "skills": {skill: _skill_record(score) for skill, score in DEFAULT_SKILLS.items()},
        "topic_mastery": {topic: _topic_record(score) for topic, score in DEFAULT_TOPIC_MASTERY.items()},
        "weak_topics": ["past tense", "conjugations", "vocabulary"],
        "recent_topics": [],
        "review_queue": {},
        "conversation_memory": _default_conversation_memory(language),
        "mistake_memory": {},
        "history": [],
        "daily_summary": {"last_sent_at": None, "lessons_completed": 0},
        "updated_at": now,
    }


def _default_conversation_memory(language: str) -> dict[str, Any]:
    return {
        "sessions_completed": 0,
        "total_turns": 0,
        "fluency_score": 0.30,
        "speaking_confidence": 0.30,
        "recent_topics": [],
        "missed_phrases": [],
        "last_video_context": {"summary": None, "primary_object": None, "confidence": None, "used_at": None},
        "next_speaking_goal": f"Answer simple questions in full {language} sentences.",
        "next_conversation_goal": None,
        "post_call_summaries": [],
    }


def _normalize_v2_state(state: dict[str, Any], language: str) -> dict[str, Any]:
    default = _default_v2_state(state.get("active_language") or language)
    for key in ("skills", "topic_mastery", "weak_topics", "recent_topics", "review_queue", "conversation_memory", "history", "daily_summary"):
        state.pop(key, None)
    for key, value in default.items():
        if key not in state:
            state[key] = copy.deepcopy(value)
    state["schema_version"] = 2
    state.setdefault("active_language", language)
    state.setdefault("languages", {})
    for lang, lang_state in list(state["languages"].items()):
        if isinstance(lang_state, dict):
            state["languages"][lang] = _normalize_language_state(lang_state, lang, state.get("updated_at"))
    if state["active_language"] not in state["languages"]:
        state["languages"][state["active_language"]] = _default_language_state(state["active_language"], state.get("updated_at"))
    learner = state.setdefault("learner", {})
    for key in ("name", "target_language", "current_level", "level", "xp", "streak_days", "learning_goals"):
        learner.pop(key, None)
    for key, value in default["learner"].items():
        learner.setdefault(key, copy.deepcopy(value))
    learner.setdefault("created_at", state.get("updated_at") or utc_now())
    preferences = state.setdefault("preferences", {})
    for key, value in default["preferences"].items():
        preferences.setdefault(key, copy.deepcopy(value))
    privacy = state.setdefault("privacy", {})
    for key, value in default["privacy"].items():
        privacy.setdefault(key, copy.deepcopy(value))
    state.setdefault("events", [])
    _normalize_event_counter(state)
    return state


def _normalize_language_state(language_data: dict[str, Any], language: str, updated_at: str | None = None) -> dict[str, Any]:
    default = _default_language_state(language, updated_at)
    for key, value in default.items():
        language_data.setdefault(key, copy.deepcopy(value))
    profile = language_data.setdefault("profile", {})
    for key, value in default["profile"].items():
        profile.setdefault(key, copy.deepcopy(value))
    profile.setdefault("target_language", language)

    skills = language_data.setdefault("skills", {})
    if "conjugation" in skills:
        skills["conjugations"] = skills.pop("conjugation")
    for skill, score in DEFAULT_SKILLS.items():
        skills[skill] = _skill_record(skills.get(skill, score))
    for skill, record in list(skills.items()):
        skills[skill] = _skill_record(record)

    topics = language_data.setdefault("topic_mastery", {})
    for topic, score in DEFAULT_TOPIC_MASTERY.items():
        topics[topic] = _topic_record(topics.get(topic, score))
    for topic, record in list(topics.items()):
        topics[topic] = _topic_record(record)

    memory = language_data.setdefault("conversation_memory", {})
    default_memory = _default_conversation_memory(language)
    for key, value in default_memory.items():
        memory.setdefault(key, copy.deepcopy(value))
    if "last_video_object" in memory:
        memory.setdefault("last_video_context", copy.deepcopy(default_memory["last_video_context"]))
        memory["last_video_context"]["primary_object"] = memory.get("last_video_object")

    language_data.setdefault("mistake_memory", {})
    language_data.setdefault("review_queue", {})
    language_data.setdefault("history", [])
    language_data.setdefault("daily_summary", copy.deepcopy(default["daily_summary"]))
    return language_data


def _migrate_v1_to_v2(v1_state: dict[str, Any], language: str) -> dict[str, Any]:
    source = copy.deepcopy(v1_state)
    learner = source.get("learner", {}) if isinstance(source.get("learner"), dict) else {}
    preferences = source.get("preferences", {}) if isinstance(source.get("preferences"), dict) else {}
    target_language = learner.get("target_language") or language
    updated_at = source.get("updated_at") or utc_now()
    v2 = _default_v2_state(target_language)
    v2["updated_at"] = updated_at
    v2["active_language"] = target_language

    v2["learner"]["display_name"] = learner.get("name", v2["learner"]["display_name"])
    v2["learner"]["active_goals"] = copy.deepcopy(learner.get("learning_goals", v2["learner"]["active_goals"]))
    v2["learner"]["preferred_session_length_minutes"] = preferences.get("lesson_minutes", v2["learner"]["preferred_session_length_minutes"])
    v2["learner"]["preferred_tutor_tone"] = preferences.get("tone", v2["learner"]["preferred_tutor_tone"])
    v2["learner"]["created_at"] = updated_at

    language_data = v2["languages"][target_language]
    profile = language_data["profile"]
    profile["target_language"] = target_language
    profile["current_level"] = learner.get("current_level") or learner.get("level", "A1")
    profile["xp"] = int(learner.get("xp", 0) or 0)
    profile["streak_days"] = int(learner.get("streak_days", 1) or 1)
    profile["learning_goals"] = copy.deepcopy(learner.get("learning_goals", DEFAULT_GOALS))

    skills = source.get("skills", {}) if isinstance(source.get("skills"), dict) else {}
    if "conjugation" in skills and "conjugations" not in skills:
        skills["conjugations"] = skills["conjugation"]
    for skill, score in skills.items():
        if skill == "conjugation":
            continue
        language_data["skills"][skill] = _skill_record(score)

    topics = source.get("topic_mastery", {}) if isinstance(source.get("topic_mastery"), dict) else {}
    for topic, score in topics.items():
        language_data["topic_mastery"][topic] = _topic_record(score)

    language_data["weak_topics"] = copy.deepcopy(source.get("weak_topics", language_data["weak_topics"]))
    language_data["recent_topics"] = copy.deepcopy(source.get("recent_topics", []))
    language_data["daily_summary"] = copy.deepcopy(source.get("daily_summary", language_data["daily_summary"]))
    language_data["updated_at"] = updated_at

    v2["preferences"]["lesson_minutes"] = preferences.get("lesson_minutes", v2["preferences"]["lesson_minutes"])
    v2["preferences"]["daily_quiz_questions"] = preferences.get("daily_quiz_questions", v2["preferences"]["daily_quiz_questions"])
    v2["preferences"]["tone"] = preferences.get("tone", v2["preferences"]["tone"])

    _migrate_review_queue(source, language_data)
    _migrate_conversation_memory(source, language_data, target_language)
    _migrate_history(source, v2, target_language)

    recognized = {
        "learner",
        "weak_topics",
        "skills",
        "topic_mastery",
        "preferences",
        "recent_topics",
        "review_queue",
        "history",
        "daily_summary",
        "conversation_memory",
        "updated_at",
    }
    legacy_extra = {key: copy.deepcopy(value) for key, value in source.items() if key not in recognized}
    if legacy_extra:
        language_data["legacy_extra"] = legacy_extra

    return _normalize_v2_state(v2, target_language)


def _migrate_review_queue(source: dict[str, Any], language_data: dict[str, Any]) -> None:
    queue = source.get("review_queue", {}) if isinstance(source.get("review_queue"), dict) else {}
    for topic, value in queue.items():
        review_id = f"review_topic_{_slugify(topic)}"
        record = copy.deepcopy(value) if isinstance(value, dict) else {"value": value}
        record.update(
            {
                "id": review_id,
                "item_type": "topic",
                "target": topic,
                "topic": record.get("topic", topic),
                "source": "lesson",
            }
        )
        if "focus_skill" in record and "skill" not in record:
            record["skill"] = record["focus_skill"]
        language_data.setdefault("review_queue", {})[review_id] = record


def _migrate_conversation_memory(source: dict[str, Any], language_data: dict[str, Any], language: str) -> None:
    old_memory = source.get("conversation_memory", {}) if isinstance(source.get("conversation_memory"), dict) else {}
    memory = language_data["conversation_memory"]
    for key in ("sessions_completed", "total_turns", "fluency_score", "speaking_confidence", "recent_topics", "missed_phrases", "next_speaking_goal"):
        if key in old_memory:
            memory[key] = copy.deepcopy(old_memory[key])
    if "last_video_object" in old_memory:
        memory["last_video_context"]["primary_object"] = old_memory.get("last_video_object")
    if "last_session_at" in old_memory:
        memory["last_session_at"] = old_memory["last_session_at"]
        language_data["profile"]["last_session_at"] = old_memory["last_session_at"]
    if "fluency_score" in old_memory and "fluency" not in source.get("skills", {}):
        language_data["skills"]["fluency"] = _skill_record(old_memory.get("fluency_score", 0.30))
    for phrase in old_memory.get("missed_phrases", []) if isinstance(old_memory.get("missed_phrases"), list) else []:
        record_mistake(
            {"schema_version": 2, "active_language": language, "languages": {language: language_data}},
            {
                "incorrect_form": "",
                "corrected_form": str(phrase),
                "context": "Legacy missed phrase from v1 conversation memory.",
                "skill": "speaking",
                "topic": "conversation",
                "error_category": "other",
                "source": "legacy_missed_phrase",
            },
            language,
        )


def _migrate_history(source: dict[str, Any], v2: dict[str, Any], language: str) -> None:
    history = source.get("history", []) if isinstance(source.get("history"), list) else []
    for item in history:
        legacy = copy.deepcopy(item)
        if isinstance(item, dict):
            mode = item.get("mode")
            if mode == "conversation":
                event_type = "conversation_started"
            elif mode == "conversation_turn":
                event_type = "learner_replied"
            else:
                event_type = "lesson_completed"
            summary = _history_summary(item, event_type)
        else:
            event_type = "progress_updated"
            summary = "Migrated legacy history item."
        add_event(
            v2,
            {
                "type": event_type,
                "occurred_at": source.get("updated_at") or utc_now(),
                "language": language,
                "source": "legacy_migration",
                "summary": summary,
                "payload": {"legacy": legacy},
            },
            language,
        )


def _history_summary(item: dict[str, Any], event_type: str) -> str:
    topic = item.get("topic", "unknown topic")
    if event_type == "conversation_started":
        return f"Migrated conversation on {topic}."
    if event_type == "learner_replied":
        return f"Migrated conversation turn on {topic}."
    return f"Migrated lesson on {topic}."


def _legacy_history_event_type(item: Any) -> str:
    if isinstance(item, dict):
        if item.get("mode") == "conversation":
            return "conversation_started"
        if item.get("mode") == "conversation_turn":
            return "learner_replied"
        return "lesson_completed"
    return "progress_updated"


def _looks_like_event(item: Any) -> bool:
    return isinstance(item, dict) and {"id", "type", "occurred_at", "payload"}.issubset(item)


def _skill_record(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        record = copy.deepcopy(value)
        record["score"] = _bounded_score(record.get("score", 0.30))
        record.setdefault("trend", "flat")
        record.setdefault("last_practiced", None)
        record.setdefault("evidence", [])
        record["evidence"] = list(record["evidence"])[-8:] if isinstance(record["evidence"], list) else []
        return record
    return {"score": _bounded_score(value), "trend": "flat", "last_practiced": None, "evidence": []}


def _topic_record(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        base = _bounded_score(value.get("recognition", 0.30))
        record = copy.deepcopy(value)
    else:
        base = _bounded_score(value)
        record = {}
    record.setdefault("recognition", base)
    record["recognition"] = _bounded_score(record["recognition"])
    for key in ("recall", "spoken_use", "written_use", "listening"):
        record.setdefault(key, base)
        record[key] = _bounded_score(record[key])
    record.setdefault("review_interval_days", 1)
    record.setdefault("last_success", None)
    record.setdefault("last_failure", None)
    record.setdefault("evidence", [])
    record["evidence"] = list(record["evidence"])[-8:] if isinstance(record["evidence"], list) else []
    return record


def _bounded_score(value: Any) -> float:
    return max(0.05, min(0.99, _as_float(value, 0.30)))


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _slugify(value: Any) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
    return slug or "item"


def _next_event_id(state: dict[str, Any]) -> str:
    _normalize_event_counter(state)
    state["event_counter"] = int(state.get("event_counter", 0) or 0) + 1
    return f"evt_{datetime.now(timezone.utc).strftime('%Y%m%d')}_{state['event_counter']:06d}"


def _normalize_event_counter(state: dict[str, Any]) -> None:
    events = state.get("events", [])
    count = len(events) if isinstance(events, list) else 0
    if isinstance(events, list):
        suffixes = []
        for event in events:
            if not isinstance(event, dict):
                continue
            event_id = str(event.get("id") or "")
            match = re.search(r"_(\d{6})$", event_id)
            if match:
                suffixes.append(int(match.group(1)))
        count = max([count, *suffixes] or [0])
    try:
        current = int(state.get("event_counter", count) or 0)
    except (TypeError, ValueError):
        current = count
    state["event_counter"] = max(current, count)


def _cap_events(state: dict[str, Any]) -> None:
    if isinstance(state.get("events"), list):
        state["events"] = state["events"][-1000:]
    for lang, lang_state in state.get("languages", {}).items():
        if isinstance(lang_state, dict) and isinstance(lang_state.get("history"), list):
            lang_state["history"] = lang_state["history"][-300:]
