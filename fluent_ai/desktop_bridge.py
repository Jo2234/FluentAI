from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from fluent_ai.agent import (
    QuizResult,
    current_level,
    due_review_items,
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
    apply_turn_progress,
    build_follow_up,
    build_opening,
    choose_conversation_topic,
    evaluate_reply,
)
from fluent_ai.openai_provider import OpenAIProvider
from fluent_ai.state import (
    active_language,
    conversation_memory,
    language_state,
    load_state,
    profile_state,
    review_queue,
    save_state,
)


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
        f"[Memory Agent] Loaded level {current_level(state)} with weak topics: {', '.join(language_state(state).get('weak_topics', []))}.",
    ]

    if not provider.available:
        return _openai_required(state, provider, "Lesson Mode requires OPENAI_API_KEY.")

    lesson = generate_lesson(state)
    enhanced = provider.enhance_lesson(state, lesson)
    if enhanced.get("source") != "openai":
        return _openai_required(state, provider, f"OpenAI lesson generation failed: {provider.last_error or 'empty model response'}")
    lesson = enhanced
    logs.append(f"[Curriculum Agent] Selected {lesson['topic']}: {lesson.get('reason', 'Lesson selected for current progress.')}")
    logs.append("[OpenAI Model Agent] Generated lesson with the OpenAI Responses API.")

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
    if provider.available:
        results = _apply_openai_quiz_grading(provider, state, lesson, quiz, answers, results)
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
            f"[Memory Agent] Scheduled spaced review for {lesson['topic']}.",
            f"[Memory Agent] Saved progress to {_path(payload)}.",
            f"[Progress Reporter Agent] {progress_report(before, state)}",
        ],
    }


def conversation_start(payload: dict[str, Any]) -> dict[str, Any]:
    state = _load(payload)
    provider = OpenAIProvider()
    video_on = payload.get("video") == "on"
    video_object = str(payload.get("object") or payload.get("vision_summary") or "").strip() or None
    if not provider.available:
        return _openai_required(state, provider, "Conversation Mode requires OPENAI_API_KEY.")

    topic = choose_conversation_topic(state, video_on=video_on, video_object=video_object)
    fallback = build_opening(topic, state)
    tutor_text = _tutor_reply(provider, payload, topic, state, [], "opening", fallback)
    if not tutor_text:
        return _openai_required(state, provider, f"OpenAI tutor generation failed: {provider.last_error or 'empty model response'}")

    logs = [
        "[Conversation Orchestrator] Starting a live tutor session.",
        f"[Memory Agent] Judged level {current_level(state)}; steering topic to {topic['topic']}.",
        f"[Vision Context Agent] Video {'on' if video_on else 'off'}"
        + (f"; OpenAI vision context: {video_object}." if video_on and video_object else "."),
    ]
    logs.append("[OpenAI Model Agent] Generated the tutor opening.")

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

    if not provider.available:
        return _openai_required(state, provider, "Conversation Mode requires OPENAI_API_KEY.")

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
    memory = conversation_memory(state)

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
            f"[Memory Agent] Saved conversation progress. Next goal: {memory['next_speaking_goal']}",
        ],
    }


def apply_conversation_turn_progress(
    state: dict[str, Any],
    topic: dict[str, Any],
    turn: dict[str, Any],
    is_first_turn: bool,
) -> None:
    apply_turn_progress(state, topic, turn, is_first_turn)


def profile_for(state: dict[str, Any], provider: OpenAIProvider | None = None) -> dict[str, Any]:
    memory = conversation_memory(state)
    provider = provider or OpenAIProvider()
    profile = profile_state(state)
    data = language_state(state)
    queue = review_queue(state)
    due_reviews = due_review_items(state)
    next_review_topic = due_reviews[0][1] if due_reviews else ""
    if not next_review_topic:
        for item in queue.values():
            if isinstance(item, dict):
                next_review_topic = str(item.get("target") or item.get("topic") or "")
                if next_review_topic:
                    break
    next_review_due_at = ""
    for item in queue.values():
        if isinstance(item, dict) and (item.get("target") or item.get("topic")) == next_review_topic:
            next_review_due_at = str(item.get("due_at") or "")
            break
    return {
        "name": state["learner"].get("display_name", "Demo Learner"),
        "language": active_language(state),
        "level": current_level(state),
        "xp": profile.get("xp", 0),
        "streak_days": profile.get("streak_days", 1),
        "weak_topics": data.get("weak_topics", []),
        "learning_goals": profile.get("learning_goals", []),
        "fluency_score": memory.get("fluency_score", 0.30),
        "speaking_confidence": memory.get("speaking_confidence", 0.30),
        "next_speaking_goal": memory.get("next_speaking_goal", ""),
        "review_count": len(queue),
        "due_review_count": len(due_reviews),
        "next_review_topic": next_review_topic,
        "next_review_due_at": next_review_due_at,
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
) -> str | None:
    if provider.available:
        generated = provider.conversation_tutor_reply(topic, state, transcript, phase, fallback)
        if generated:
            return generated
    return None


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
    state = load_state(path, language)
    if language and active_language(state) != language:
        state["active_language"] = language
        language_state(state, language)
        save_state(path, state)
    return state


def _language(payload: dict[str, Any]) -> str:
    raw = str(payload.get("language") or "Spanish").strip().lower()
    return SUPPORTED_LANGUAGES.get(raw, "Spanish")


def _path(payload: dict[str, Any]) -> Path:
    return Path(str(payload.get("state_path") or DEFAULT_PROGRESS_PATH))


def _openai_required(state: dict[str, Any], provider: OpenAIProvider, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": message,
        "profile": profile_for(state, provider),
        "logs": [f"[OpenAI Model Agent] {provider.status()}", f"[Orchestrator] {message}"],
    }


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


def _apply_openai_quiz_grading(
    provider: OpenAIProvider,
    state: dict[str, Any],
    lesson: dict[str, Any],
    quiz: list[dict[str, Any]],
    answers: list[str],
    local_results: list[QuizResult],
) -> list[QuizResult]:
    graded = list(local_results)
    grader = getattr(provider, "evaluate_quiz_answers", None)
    if not callable(grader):
        return graded
    items = [
        {
            "index": index,
            "question": question,
            "answer": answers[index],
        }
        for index, question in enumerate(quiz)
        if question.get("type") != "multiple_choice" and index < len(graded)
    ]
    if not items:
        return graded
    provider_results = grader(state, lesson, items)
    if not isinstance(provider_results, list) or len(provider_results) != len(items):
        return graded
    for item, provider_result in zip(items, provider_results):
        index = int(item["index"])
        question = quiz[index]
        if not isinstance(provider_result, dict):
            continue
        expected = str(question.get("answer") or "")
        category = provider_result.get("error_category")
        corrected = provider_result.get("corrected_form")
        if provider_result.get("correct") and category == "unnatural":
            corrected = corrected or expected
        elif provider_result.get("correct"):
            corrected = None
        else:
            corrected = corrected or expected
        graded[index] = QuizResult(
            prompt=str(question.get("prompt") or ""),
            expected=expected,
            actual=answers[index],
            skill=str(question.get("skill") or ""),
            topic=str(question.get("topic") or lesson.get("topic") or ""),
            question_type=str(question.get("type") or ""),
            correct=bool(provider_result["correct"]),
            feedback=str(provider_result["feedback"]),
            error_category=category,
            corrected_form=corrected,
            severity=str(provider_result.get("severity") or "medium"),
            confidence=float(provider_result.get("confidence") or 0.0),
        )
    return graded


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
