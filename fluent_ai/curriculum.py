from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


CURRICULUM_DIR = Path(__file__).parent / "curriculum"

_LANGUAGE_FILES = {
    "spanish": "spanish.json",
    "french": "french.json",
    "hindi": "hindi.json",
}

_ALIASES = {
    "cafe orders": "cafe_orders",
    "cafe_orders": "cafe orders",
    "travel plans": "directions_travel",
    "health symptoms": "health_basics",
    "past weekend": "past_weekend",
    "vocabulary": "core_vocabulary",
    "likes and food": "likes_food",
    "workplace situations": "work_and_goals",
    "work and goals": "work_and_goals",
}

_RAW_CACHE: dict[str, dict[str, Any]] = {}
_BANK_CACHE: dict[str, dict[str, dict[str, Any]]] = {}
_TOPICS_CACHE: dict[str, dict[str, list[str]]] = {}
_CONVERSATION_CACHE: dict[str, dict[str, list[dict[str, Any]]]] = {}


def lesson_bank(language: str) -> dict[str, dict[str, Any]]:
    key = _language_key(language)
    if key not in _BANK_CACHE:
        raw = _load_language(key)
        bank: dict[str, dict[str, Any]] = {}
        for level in raw.get("levels", {}).values():
            topics = level.get("topics", {}) if isinstance(level, dict) else {}
            for topic, details in topics.items():
                if isinstance(details, dict):
                    bank[str(topic)] = _topic_to_lesson(details)
        _BANK_CACHE[key] = _with_aliases(bank)
    return copy.deepcopy(_BANK_CACHE[key])


def topics_by_level(language: str) -> dict[str, list[str]]:
    key = _language_key(language)
    if key not in _TOPICS_CACHE:
        raw = _load_language(key)
        topics: dict[str, list[str]] = {}
        for level, details in raw.get("levels", {}).items():
            order = details.get("topic_order", []) if isinstance(details, dict) else []
            topics[str(level)] = [str(topic) for topic in order]
        _TOPICS_CACHE[key] = topics
    return copy.deepcopy(_TOPICS_CACHE[key])


def conversation_ladder(language: str) -> dict[str, list[dict[str, Any]]]:
    key = _language_key(language)
    if key not in _CONVERSATION_CACHE:
        raw = _load_language(key)
        ladder: dict[str, list[dict[str, Any]]] = {}
        for level, details in raw.get("levels", {}).items():
            entries: list[dict[str, Any]] = []
            explicit_entries = details.get("conversation", []) if isinstance(details, dict) else []
            if explicit_entries:
                for entry in explicit_entries:
                    if isinstance(entry, dict):
                        entries.append(_conversation_entry(entry))
            else:
                topics = details.get("topics", {}) if isinstance(details, dict) else {}
                for topic in details.get("topic_order", []):
                    topic_details = topics.get(topic, {})
                    if not isinstance(topic_details, dict) and _ALIASES.get(str(topic)) in topics:
                        topic_details = topics[_ALIASES[str(topic)]]
                    if isinstance(topic_details, dict):
                        for entry in topic_details.get("conversation", []) or []:
                            if isinstance(entry, dict):
                                entries.append(_conversation_entry(entry))
            if entries:
                ladder[str(level)] = entries
        _CONVERSATION_CACHE[key] = ladder
    return copy.deepcopy(_CONVERSATION_CACHE[key])


def topic_lesson(language: str, level: str, topic: str) -> dict[str, Any] | None:
    key = _language_key(language)
    topic_key = str(topic)
    bank = lesson_bank(key)
    if topic_key in bank:
        return bank[topic_key]

    alias = _ALIASES.get(topic_key)
    if alias and alias in bank:
        return bank[alias]

    raw = _load_language(key)
    level_details = raw.get("levels", {}).get(level, {})
    default_topic = level_details.get("default_topic") if isinstance(level_details, dict) else None
    if default_topic and default_topic in bank:
        return bank[str(default_topic)]

    generic = raw.get("generic")
    if isinstance(generic, dict):
        return _topic_to_lesson(generic)

    if key != "spanish":
        spanish_bank = lesson_bank("Spanish")
        if topic_key in spanish_bank:
            return spanish_bank[topic_key]
        alias = _ALIASES.get(topic_key)
        if alias and alias in spanish_bank:
            return spanish_bank[alias]
    return None


def _load_language(key: str) -> dict[str, Any]:
    if key not in _RAW_CACHE:
        filename = _LANGUAGE_FILES.get(key, _LANGUAGE_FILES["spanish"])
        with (CURRICULUM_DIR / filename).open("r", encoding="utf-8") as handle:
            _RAW_CACHE[key] = json.load(handle)
    return _RAW_CACHE[key]


def _language_key(language: str) -> str:
    return str(language or "Spanish").strip().lower()


def _with_aliases(bank: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    expanded = dict(bank)
    for source, target in _ALIASES.items():
        if source not in expanded and target in expanded:
            expanded[source] = copy.deepcopy(expanded[target])
        if target not in expanded and source in expanded:
            expanded[target] = copy.deepcopy(expanded[source])
    return expanded


def _topic_to_lesson(topic: dict[str, Any]) -> dict[str, Any]:
    lesson = {
        "focus_skill": str(topic.get("focus_skill") or "vocabulary"),
        "vocabulary": _pairs(topic.get("vocabulary")),
        "grammar": str(topic.get("grammar") or ""),
        "examples": _pairs(topic.get("examples")),
        "answers": copy.deepcopy(topic.get("answers") or {}),
    }

    vocabulary_rich = _rich_records(topic.get("vocabulary"))
    examples_rich = _rich_records(topic.get("examples"))
    if vocabulary_rich:
        lesson["vocabulary_rich"] = vocabulary_rich
    if examples_rich:
        lesson["examples_rich"] = examples_rich
    for field in ("pronunciation_hints", "cultural_note"):
        if topic.get(field):
            lesson[field] = copy.deepcopy(topic[field])
    if any(item.get("romanization") for item in vocabulary_rich + examples_rich):
        lesson["romanization_available"] = True

    return lesson


def _conversation_entry(entry: dict[str, Any]) -> dict[str, Any]:
    copied = copy.deepcopy(entry)
    if isinstance(copied.get("topic"), str):
        copied["topic"] = copied["topic"].replace("_", " ")
    return copied


def _pairs(value: Any) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                target = str(item.get("target") or "").strip()
                english = str(item.get("english") or "").strip()
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                target = str(item[0]).strip()
                english = str(item[1]).strip()
            else:
                continue
            if target and english:
                pairs.append((target, english))
    return pairs


def _rich_records(value: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                records.append(copy.deepcopy(item))
    return records
