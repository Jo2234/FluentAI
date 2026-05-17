from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from fluent_ai.agent import (
    current_level,
    evaluate_answers,
    generate_lesson,
    generate_quiz,
    progress_report,
    recommendation,
    snapshot_progress,
    update_progress,
)
from fluent_ai.conversation import (
    ConversationTurn,
    bounded,
    build_follow_up,
    build_opening,
    choose_conversation_topic,
    evaluate_reply,
    next_speaking_goal,
)
from fluent_ai.openai_provider import OpenAIProvider
from fluent_ai.state import load_state, recalculate_weak_topics, save_state, utc_now


DEFAULT_PROGRESS_PATH = Path("data/progress.json")
SUPPORTED_LANGUAGES = {
    "hindi": "Hindi",
    "spanish": "Spanish",
    "french": "French",
    "francais": "French",
    "français": "French",
}


def status(payload: dict[str, Any]) -> dict[str, Any]:
    state = _load(payload)
    provider = OpenAIProvider()
    return {
        "ok": True,
        "profile": profile_for(state, provider),
        "logs": [
            "[Memory Agent] Loaded local learner profile.",
            f"[OpenAI Model Agent] {provider.status()}",
        ],
    }


def realtime_client_secret(payload: dict[str, Any]) -> dict[str, Any]:
    state = _load(payload)
    provider = OpenAIProvider()
    video_on = payload.get("video") == "on"
    video_context = str(payload.get("vision_summary") or "").strip() or None
    result = provider.realtime_client_secret(state, video_on=video_on, video_context=video_context)
    if not result.get("ok"):
        return {
            "ok": False,
            "error": result.get("error", "Could not create OpenAI Realtime client secret."),
            "profile": profile_for(state, provider),
            "logs": ["[OpenAI Voice Agent] Realtime setup failed."],
        }
    result["profile"] = profile_for(state, provider)
    result["logs"] = [
        f"[OpenAI Voice Agent] Created ephemeral Realtime session for {result.get('model', 'gpt-realtime')}.",
        f"[Voice Tutor Agent] Voice: {result.get('voice', 'alloy')}.",
    ]
    return result


def vision_analyze_frame(payload: dict[str, Any]) -> dict[str, Any]:
    state = _load(payload)
    provider = OpenAIProvider()
    image_data_url = str(payload.get("image") or "")
    result = provider.analyze_camera_frame(state, image_data_url)
    if not result.get("ok"):
        return {
            "ok": False,
            "error": result.get("error", "Could not analyze the camera frame."),
            "profile": profile_for(state, provider),
            "logs": ["[Vision Context Agent] Camera frame analysis failed."],
        }
    result["profile"] = profile_for(state, provider)
    result["logs"] = [
        f"[Vision Context Agent] Analyzed camera frame with {result.get('model', 'OpenAI vision')}.",
        f"[Vision Context Agent] Saw: {result.get('summary', 'unclear scene')}.",
    ]
    return result


def lesson_start(payload: dict[str, Any]) -> dict[str, Any]:
    state = _load(payload)
    provider = OpenAIProvider()
    logs = [
        "[Lesson Orchestrator] Starting an interactive lesson.",
        f"[Memory Agent] Loaded level {current_level(state)} with weak topics: {', '.join(state.get('weak_topics', []))}.",
    ]

    lesson = generate_lesson(state)
    if _use_openai(payload) and provider.available:
        enhanced = provider.enhance_lesson(state, lesson)
        if enhanced.get("source") == "openai":
            lesson = enhanced
            logs.append("[OpenAI Model Agent] Enhanced lesson with the OpenAI Responses API.")
        elif provider.last_error:
            logs.append(f"[OpenAI Model Agent] Local fallback after API issue: {provider.last_error}")
    else:
        logs.append("[OpenAI Model Agent] Using deterministic local lesson generator.")

    quiz = generate_quiz(state, lesson)
    logs.append(
        f"[Lesson Generator Agent] Created a {lesson['minutes']}-minute {lesson['level']} lesson on {lesson['topic']}."
    )
    logs.append(f"[Adaptive Quiz Agent] Prepared {len(quiz)} questions for the learner to answer.")

    return {
        "ok": True,
        "profile": profile_for(state, provider),
        "lesson": lesson,
        "quiz": quiz,
        "logs": logs,
    }


def lesson_submit(payload: dict[str, Any]) -> dict[str, Any]:
    state = _load(payload)
    provider = OpenAIProvider()
    before = snapshot_progress(state)
    lesson = payload["lesson"]
    quiz = payload["quiz"]
    answers = [str(answer).strip() for answer in payload.get("answers", [])]

    while len(answers) < len(quiz):
        answers.append("")

    results = evaluate_answers(quiz, answers)
    correct_count = sum(1 for result in results if result.correct)
    state = update_progress(state, lesson, results)
    save_state(_path(payload), state)

    return {
        "ok": True,
        "profile": profile_for(state, provider),
        "results": [result.__dict__ for result in results],
        "summary": {
            "score": f"{correct_count}/{len(results)}",
            "report": progress_report(before, state),
            "recommendation": recommendation(state),
        },
        "logs": [
            f"[Evaluator Agent] Graded quiz: {correct_count}/{len(results)} correct.",
            f"[Memory Agent] Saved progress to {_path(payload)}.",
            f"[Progress Reporter Agent] {progress_report(before, state)}",
        ],
    }


def conversation_start(payload: dict[str, Any]) -> dict[str, Any]:
    state = _load(payload)
    provider = OpenAIProvider()
    video_on = payload.get("video") == "on"
    video_object = str(payload.get("object") or payload.get("vision_summary") or "").strip() or None
    topic = choose_conversation_topic(state, video_on=video_on, video_object=video_object)
    fallback = build_opening(topic, state)
    tutor_text = _tutor_reply(provider, payload, topic, state, [], "opening", fallback)

    logs = [
        "[Conversation Orchestrator] Starting a live tutor session.",
        f"[Memory Agent] Judged level {current_level(state)}; steering topic to {topic['topic']}.",
        f"[Vision Context Agent] Video {'on' if video_on else 'off'}"
        + (f"; OpenAI vision context: {video_object}." if video_on and video_object else "."),
    ]
    if _use_openai(payload) and provider.available:
        logs.append("[OpenAI Model Agent] Generated the tutor opening.")
    else:
        logs.append("[OpenAI Model Agent] Using local tutor opening.")

    session = {
        "topic": topic,
        "turns": [],
        "video_on": video_on,
        "video_object": video_object,
        "max_turns": _bounded_int(payload.get("turns"), 2, 8, 4),
    }

    return {
        "ok": True,
        "profile": profile_for(state, provider),
        "session": session,
        "tutor_message": tutor_text,
        "logs": logs,
    }


def conversation_reply(payload: dict[str, Any]) -> dict[str, Any]:
    state = _load(payload)
    provider = OpenAIProvider()
    session = payload["session"]
    topic = session["topic"]
    turns = list(session.get("turns", []))
    learner_text = str(payload.get("message") or "").strip()
    turn_number = len(turns) + 1

    if not learner_text:
        return {
            "ok": False,
            "error": "Type a reply before sending.",
            "session": session,
            "profile": profile_for(state, provider),
        }

    score, feedback, correction = evaluate_reply(topic, learner_text, state)
    turn = {
        "turn_number": turn_number,
        "tutor_text": str(payload.get("tutor_message") or ""),
        "learner_text": learner_text,
        "topic": topic["topic"],
        "complexity": topic["complexity"],
        "video_on": bool(session.get("video_on")),
        "video_object": session.get("video_object") if session.get("video_on") else None,
        "score": score,
        "feedback": feedback,
        "correction": correction,
    }
    turns.append(turn)

    transcript = [_turn_from_dict(item) for item in turns]
    fallback = build_follow_up(topic, learner_text, score, turn_number, state)
    tutor_text = _tutor_reply(provider, payload, topic, state, transcript, "follow_up", fallback)

    apply_conversation_turn_progress(state, topic, turn, is_first_turn=turn_number == 1)
    save_state(_path(payload), state)

    session["turns"] = turns
    reached_goal = len(turns) >= int(session.get("max_turns", 4))
    return {
        "ok": True,
        "profile": profile_for(state, provider),
        "session": session,
        "turn": turn,
        "tutor_message": tutor_text,
        "done": reached_goal,
        "logs": [
            f"[Fluency Evaluator Agent] Scored turn {turn_number}: {score:.2f}.",
            f"[Speaking Tutor Agent] Next prompt adapts to {topic['complexity']} complexity.",
            f"[Memory Agent] Saved conversation progress. Next goal: {state['conversation_memory']['next_speaking_goal']}",
        ],
    }


def apply_conversation_turn_progress(
    state: dict[str, Any],
    topic: dict[str, Any],
    turn: dict[str, Any],
    is_first_turn: bool,
) -> None:
    score = float(turn["score"])
    memory = state.setdefault("conversation_memory", {})
    if is_first_turn:
        memory["sessions_completed"] = int(memory.get("sessions_completed", 0)) + 1
        memory["recent_topics"] = (memory.get("recent_topics", []) + [topic["topic"]])[-8:]

    memory["total_turns"] = int(memory.get("total_turns", 0)) + 1
    memory["fluency_score"] = bounded(float(memory.get("fluency_score", 0.30)) * 0.85 + score * 0.15)
    memory["speaking_confidence"] = bounded(
        float(memory.get("speaking_confidence", 0.30)) + (0.025 if score >= 0.45 else -0.015)
    )
    memory["last_video_object"] = turn.get("video_object") if turn.get("video_on") else None
    memory["last_session_at"] = utc_now()
    memory["next_speaking_goal"] = next_speaking_goal(state, score, topic)

    if turn.get("correction"):
        memory["missed_phrases"] = (memory.get("missed_phrases", []) + [turn["correction"]])[-8:]

    speaking_delta = 0.025 if score >= 0.45 else -0.01
    state["skills"]["vocabulary"] = bounded(state["skills"].get("vocabulary", 0.30) + speaking_delta)
    state["skills"]["grammar"] = bounded(state["skills"].get("grammar", 0.30) + speaking_delta / 2)
    state["topic_mastery"][topic["topic"]] = bounded(state["topic_mastery"].get(topic["topic"], 0.30) + speaking_delta)
    state["weak_topics"] = recalculate_weak_topics(state)
    state["history"] = (
        state.get("history", [])
        + [
            {
                "mode": "conversation_turn",
                "topic": topic["topic"],
                "complexity": topic["complexity"],
                "score": round(score, 2),
                "video_on": bool(turn.get("video_on")),
                "video_object": turn.get("video_object"),
                "next_speaking_goal": memory["next_speaking_goal"],
            }
        ]
    )[-25:]


def profile_for(state: dict[str, Any], provider: OpenAIProvider | None = None) -> dict[str, Any]:
    memory = state.get("conversation_memory", {})
    provider = provider or OpenAIProvider()
    return {
        "name": state["learner"].get("name", "Demo Learner"),
        "language": state["learner"].get("target_language", "Spanish"),
        "level": current_level(state),
        "xp": state["learner"].get("xp", 0),
        "streak_days": state["learner"].get("streak_days", 1),
        "weak_topics": state.get("weak_topics", []),
        "learning_goals": state["learner"].get("learning_goals", []),
        "fluency_score": memory.get("fluency_score", 0.30),
        "speaking_confidence": memory.get("speaking_confidence", 0.30),
        "next_speaking_goal": memory.get("next_speaking_goal", ""),
        "openai_status": provider.status(),
    }


def _tutor_reply(
    provider: OpenAIProvider,
    payload: dict[str, Any],
    topic: dict[str, Any],
    state: dict[str, Any],
    transcript: list[ConversationTurn],
    phase: str,
    fallback: str,
) -> str:
    if _use_openai(payload) and provider.available:
        generated = provider.conversation_tutor_reply(topic, state, transcript, phase, fallback)
        if generated:
            return generated
    return fallback


def _turn_from_dict(value: dict[str, Any]) -> ConversationTurn:
    return ConversationTurn(
        turn_number=int(value["turn_number"]),
        tutor_text=str(value["tutor_text"]),
        learner_text=str(value["learner_text"]),
        topic=str(value["topic"]),
        complexity=str(value["complexity"]),
        video_on=bool(value["video_on"]),
        video_object=value.get("video_object"),
        score=float(value["score"]),
        feedback=str(value["feedback"]),
        correction=value.get("correction"),
    )


def _load(payload: dict[str, Any]) -> dict[str, Any]:
    language = _language(payload) if "language" in payload else None
    path = _path(payload)
    state = load_state(path, language or "Spanish")
    learner = state.setdefault("learner", {})
    if language and learner.get("target_language") != language:
        learner["target_language"] = language
        memory = state.setdefault("conversation_memory", {})
        memory["next_speaking_goal"] = f"Answer simple questions in full {language} sentences."
        save_state(path, state)
    return state


def _language(payload: dict[str, Any]) -> str:
    raw = str(payload.get("language") or "Spanish").strip().lower()
    return SUPPORTED_LANGUAGES.get(raw, "Spanish")


def _path(payload: dict[str, Any]) -> Path:
    return Path(str(payload.get("state_path") or DEFAULT_PROGRESS_PATH))


def _use_openai(payload: dict[str, Any]) -> bool:
    return bool(payload.get("use_openai", True))


def _bounded_int(value: Any, low: int, high: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(high, parsed))


COMMANDS = {
    "status": status,
    "realtime_client_secret": realtime_client_secret,
    "vision_analyze_frame": vision_analyze_frame,
    "lesson_start": lesson_start,
    "lesson_submit": lesson_submit,
    "conversation_start": conversation_start,
    "conversation_reply": conversation_reply,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="JSON bridge for the FluentAI desktop app.")
    parser.add_argument("command", choices=sorted(COMMANDS))
    args = parser.parse_args()

    try:
        raw_payload = sys.stdin.read().strip()
        payload = json.loads(raw_payload) if raw_payload else {}
        result = COMMANDS[args.command](payload)
    except Exception as exc:  # pragma: no cover - defensive bridge boundary.
        result = {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}

    json.dump(result, sys.stdout, ensure_ascii=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
