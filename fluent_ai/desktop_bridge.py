from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fluent_ai.agent import (
    QuizResult,
    current_level,
    due_mistake_items,
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
    conversation_topic_to_lesson_topic,
    choose_conversation_topic,
    evaluate_reply_with_metadata,
    evaluate_reply_with_provider,
    persist_post_call_summary,
)
from fluent_ai.openai_provider import OpenAIProvider
from fluent_ai.state import (
    add_event,
    active_language,
    conversation_memory,
    delete_all_memory,
    language_state,
    load_state,
    profile_state,
    recalculate_weak_topics,
    reset_language_state,
    save_state,
    set_skill_score,
    set_topic_score,
    skill_scores,
    review_queue,
    topic_scores,
    utc_now,
)


DEFAULT_PROGRESS_PATH = Path("data/progress.json")
MODEL_FAILURE_MESSAGE = "The tutor model timed out or failed. Your progress is safe — try again."
CHECKPOINT_MAX_AGE = timedelta(hours=24)
SUPPORTED_LANGUAGES = {
    "hindi": "Hindi",
    "spanish": "Spanish",
    "french": "French",
    "francais": "French",
    "français": "French",
}

SPEAKING_COMFORT_SEEDS = {
    "quiet": 0.22,
    "some": 0.35,
    "comfortable": 0.50,
}

def onboarding_status(payload: dict[str, Any]) -> dict[str, Any]:
    path = _path(payload)
    language = _language(payload) if "language" in payload else "Spanish"
    if not path.exists():
        return {
            "ok": True,
            "requires_onboarding": True,
            "is_first_launch": True,
            "requires_placement": True,
            "profile": {},
            "defaults": {"language": "Spanish", "session_minutes": 10, "video_default": "off"},
            "logs": ["[Onboarding Agent] First launch detected."],
        }

    state = load_state(path, language)
    if language and active_language(state) != language:
        state["active_language"] = language
        language_state(state, language)
    learner = state.setdefault("learner", {})
    profile = profile_state(state, language)
    requires_onboarding = not bool(learner.get("onboarded_at"))
    requires_placement = not bool(profile.get("placement_completed_at"))
    if requires_onboarding:
        log = "[Onboarding Agent] Existing learner profile needs onboarding metadata."
    elif requires_placement:
        log = "[Onboarding Agent] Onboarding complete; placement still needed."
    else:
        log = "[Onboarding Agent] Onboarding and placement are complete."
    return {
        "ok": True,
        "recovered": _was_recovered(state),
        "requires_onboarding": requires_onboarding,
        "is_first_launch": False,
        "requires_placement": requires_placement,
        "profile": profile_for(state),
        "defaults": {
            "language": active_language(state),
            "session_minutes": int(state.get("preferences", {}).get("lesson_minutes", 10) or 10),
            "video_default": state.get("preferences", {}).get("video_default", "off"),
        },
        "logs": _recovery_logs(state) + [log],
    }


def onboarding_submit(payload: dict[str, Any]) -> dict[str, Any]:
    language = _language(payload)
    path = _path(payload)
    state = load_state(path, language)
    state["active_language"] = language
    data = language_state(state, language)
    learner = state.setdefault("learner", {})
    profile = data.setdefault("profile", {})
    preferences = state.setdefault("preferences", {})
    privacy = state.setdefault("privacy", {})

    now = _next_timestamp_after(learner.get("last_onboarding_at"))
    display_name = str(payload.get("display_name") or "").strip()
    if display_name:
        learner["display_name"] = display_name
    learner["motivation"] = str(payload.get("motivation") or "").strip()
    goals = _string_list(payload.get("goals"))
    if goals:
        learner["active_goals"] = goals
        profile["learning_goals"] = goals.copy()
    session_minutes = _bounded_int(payload.get("session_minutes"), 5, 15, 10)
    learner["preferred_session_length_minutes"] = session_minutes
    preferences["lesson_minutes"] = session_minutes

    if "voice_default" in payload:
        preferences["voice_default"] = str(payload.get("voice_default") or "").strip() or None
    if "video_default" in payload:
        preferences["video_default"] = "on" if str(payload.get("video_default")).lower() == "on" else "off"

    privacy["local_only"] = bool(payload.get("privacy_local_only", True))
    privacy["store_raw_audio"] = False
    privacy["store_raw_video"] = False
    privacy["store_camera_summaries"] = True
    privacy["local_memory_notice_seen_at"] = now

    profile["target_language"] = language
    self_reported_level = _self_reported_level(payload.get("self_reported_level"))
    profile["self_reported_level"] = self_reported_level
    speaking_comfort = _speaking_comfort(payload.get("speaking_comfort"))
    profile["speaking_comfort"] = speaking_comfort
    conversation_memory(state, language)["speaking_confidence"] = SPEAKING_COMFORT_SEEDS[speaking_comfort]

    learner.setdefault("onboarded_at", now)
    if not learner.get("onboarded_at"):
        learner["onboarded_at"] = now
    learner["last_onboarding_at"] = now

    add_event(
        state,
        {
            "type": "onboarding_completed",
            "source": "onboarding_bridge",
            "summary": f"Completed onboarding for {language}.",
            "occurred_at": now,
            "payload": {
                "language": language,
                "self_reported_level": self_reported_level,
                "speaking_comfort": speaking_comfort,
                "session_minutes": session_minutes,
                "video_default": preferences.get("video_default", "off"),
            },
        },
        language,
    )
    save_state(path, state)
    return {
        "ok": True,
        "profile": profile_for(state),
        "requires_placement": not bool(profile.get("placement_completed_at")),
        "logs": [
            f"[Onboarding Agent] Saved tutor intake for {learner.get('display_name', 'learner')}.",
            "[Memory Agent] Preserved existing learning memory.",
        ],
    }


def placement_start(payload: dict[str, Any]) -> dict[str, Any]:
    language = _language(payload) if "language" in payload else None
    state = load_state(_path(payload), language)
    language = language or active_language(state)
    state["active_language"] = language
    language_state(state, language)
    placement_state = copy.deepcopy(state)
    lesson = generate_lesson(placement_state)
    quiz = generate_quiz(placement_state, lesson)
    items = [copy.deepcopy(item) for item in quiz if item.get("type") != "open_ended"][:5]
    if len(items) < 3:
        items = [copy.deepcopy(item) for item in quiz[:5]]
    written_prompt = {}
    if payload.get("include_written", True):
        written_prompt = _written_prompt_from(quiz, lesson)
    conversation_prompt = {}
    if payload.get("include_conversation", True):
        topic = choose_conversation_topic(placement_state, video_on=False, video_object=None)
        conversation_prompt = {
            "type": "conversation",
            "topic": topic.get("topic"),
            "complexity": topic.get("complexity"),
            "prompt": topic.get("opening"),
            "support": topic.get("support"),
            "keywords": topic.get("keywords", []),
        }
    session = {
        "id": _placement_session_id(),
        "language": language,
        "lesson": lesson,
        "items": items[:5],
        "written_prompt": written_prompt,
        "conversation_prompt": conversation_prompt,
    }
    return {
        "ok": True,
        "session": session,
        "profile": profile_for(state),
        "logs": [f"[Placement Agent] Built a {len(session['items'])}-item adaptive check from the lesson bank."],
    }


def placement_submit(payload: dict[str, Any]) -> dict[str, Any]:
    session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
    language = _language({"language": session.get("language") or payload.get("language") or "Spanish"})
    path = _path(payload)
    state = load_state(path, language)
    state["active_language"] = language
    data = language_state(state, language)
    profile = data.setdefault("profile", {})

    if payload.get("skip_beginner"):
        result = _complete_skip_beginner_placement(state, language)
        save_state(path, state)
        return {
            "ok": True,
            "profile": profile_for(state),
            "placement": result,
            "logs": ["[Placement Agent] Placement skipped; starting as A1 beginner."],
        }

    items = [item for item in session.get("items", []) if isinstance(item, dict)]
    answers = [str(answer).strip() for answer in payload.get("answers", [])]
    while len(answers) < len(items):
        answers.append("")
    results = evaluate_answers(items, answers)
    correct_count = sum(1 for result in results if result.correct)
    quiz_accuracy = correct_count / len(results) if results else 0.0

    written_prompt = session.get("written_prompt") if isinstance(session.get("written_prompt"), dict) else {}
    written_score = None
    written_result = None
    if written_prompt and "written_answer" in payload:
        written_answers = [str(payload.get("written_answer") or "").strip()]
        written_result = evaluate_answers([written_prompt], written_answers)[0]
        written_score = _quiz_result_score(written_result)

    conversation_prompt = session.get("conversation_prompt") if isinstance(session.get("conversation_prompt"), dict) else {}
    conversation_score = None
    if conversation_prompt and "conversation_answer" in payload:
        conversation_topic = {
            "topic": conversation_prompt.get("topic") or "introductions",
            "complexity": conversation_prompt.get("complexity") or "beginner",
            "opening": conversation_prompt.get("prompt") or "",
            "support": conversation_prompt.get("support") or "",
            "keywords": conversation_prompt.get("keywords") if isinstance(conversation_prompt.get("keywords"), list) else [],
        }
        conversation_score, _feedback, _correction, _mistake = evaluate_reply_with_metadata(
            conversation_topic,
            str(payload.get("conversation_answer") or ""),
            state,
        )

    signals = [quiz_accuracy]
    if written_score is not None:
        signals.append(written_score)
    if conversation_score is not None:
        signals.append(conversation_score)
    placement_score = sum(signals) / len(signals)
    judged_level = _judged_level(placement_score)
    self_reported_level = profile.get("self_reported_level")
    level_cap_applied = False
    if self_reported_level in {"new", "A1", "not sure"} and _level_rank(judged_level) > _level_rank("B1"):
        judged_level = "B1"
        level_cap_applied = True
    level_confidence = _placement_confidence(written_score is not None, conversation_score is not None)

    completed_at = utc_now()
    profile["current_level"] = judged_level
    profile["level_confidence"] = level_confidence
    profile["placement_completed_at"] = completed_at
    profile["placement_method"] = "adaptive"
    first_practice_goal = _first_practice_goal(judged_level)
    first_conversation_goal = _first_conversation_goal(judged_level, language)
    profile["first_practice_goal"] = first_practice_goal

    event = add_event(
        state,
        {
            "type": "placement_completed",
            "source": "placement_bridge",
            "summary": f"Completed adaptive placement at {judged_level}.",
            "occurred_at": completed_at,
            "payload": {
                "method": "adaptive",
                "self_reported_level": self_reported_level,
                "judged_level": judged_level,
                "level_cap_applied": level_cap_applied,
                "quiz_score": f"{correct_count}/{len(results)}",
                "written_score": written_score,
                "conversation_score": conversation_score,
                "first_practice_goal": first_practice_goal,
                "first_conversation_goal": first_conversation_goal["instruction"],
            },
        },
        language,
    )
    _apply_placement_seeds(
        state,
        language,
        results,
        written_result,
        written_score,
        conversation_prompt,
        conversation_score,
        event["id"],
    )
    scores = skill_scores(state, language)
    strongest, weakest = _strongest_weakest(scores)
    profile["judged_strengths"] = strongest
    profile["judged_weaknesses"] = weakest
    data["weak_topics"] = recalculate_weak_topics(state, language=language)
    memory = conversation_memory(state, language)
    if conversation_score is not None:
        memory["speaking_confidence"] = _bounded_score(max(float(memory.get("speaking_confidence", 0.30) or 0.30), conversation_score))
    memory["next_speaking_goal"] = first_conversation_goal["instruction"]
    memory["next_conversation_goal"] = first_conversation_goal
    _update_event_payload(state, event["id"], {"strongest_skills": strongest, "weakest_skills": weakest}, language)
    save_state(path, state)

    return {
        "ok": True,
        "profile": profile_for(state),
        "placement": {
            "judged_level": judged_level,
            "level_confidence": level_confidence,
            "strongest_skills": strongest,
            "weakest_skills": weakest,
            "first_practice_goal": first_practice_goal,
            "first_conversation_goal": first_conversation_goal["instruction"],
        },
        "logs": [f"[Placement Agent] Judged starting level {judged_level} from {correct_count}/{len(results)} placement items."],
    }


def status(payload: dict[str, Any]) -> dict[str, Any]:
    state = _load(payload)
    provider = OpenAIProvider()
    return {
        "ok": True,
        "recovered": _was_recovered(state),
        "profile": profile_for(state, provider),
        "logs": _recovery_logs(state) + [
            "[Memory Agent] Loaded local learner profile.",
            f"[OpenAI Model Agent] {provider.status()}",
        ],
    }


def validate_key(payload: dict[str, Any]) -> dict[str, Any]:
    provider = OpenAIProvider()
    if not provider.api_key:
        return {"ok": True, "valid": False, "message": "No OpenAI API key was provided."}
    if provider.health_check():
        return {"ok": True, "valid": True, "message": "OpenAI key validated."}
    return {"ok": True, "valid": False, "message": "That key did not validate. Check it and try again."}


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
    _write_lesson_checkpoint(_path(payload), active_language(state), lesson, quiz, [])
    logs.append("[Session Recovery Agent] Saved lesson checkpoint.")

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
    _delete_checkpoint(_checkpoint_path(_path(payload), "current_lesson.json"))

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
    topic["speaking_confidence_before"] = float(conversation_memory(state).get("speaking_confidence", 0.30) or 0.30)
    fallback = build_opening(topic, state)
    tutor_text, recovery_used = _safe_tutor_reply(provider, payload, topic, state, [], "opening", fallback)
    if not tutor_text:
        return _openai_required(state, provider, f"OpenAI tutor generation failed: {provider.last_error or 'empty model response'}")

    logs = [
        "[Conversation Orchestrator] Starting a live tutor session.",
        f"[Memory Agent] Judged level {current_level(state)}; steering topic to {topic['topic']}.",
        f"[Vision Context Agent] Video {'on' if video_on else 'off'}"
        + (f"; OpenAI vision context: {video_object}." if video_on and video_object else "."),
    ]
    if isinstance(topic.get("goal"), dict) and topic["goal"].get("instruction"):
        logs.append(f"[Conversation Orchestrator] Practicing lesson goal: {topic['goal']['instruction']}")
    logs.append("[OpenAI Model Agent] Generated the tutor opening.")
    if recovery_used:
        logs.append("[Conversation Orchestrator] Used recovery prompt after empty model response.")

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

    score, feedback, correction, mistake = evaluate_reply_with_provider(
        topic,
        learner_text,
        state,
        getattr(provider, "evaluate_conversation_reply", None),
    )
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
        "mistake": mistake,
    }
    turns.append(turn)

    transcript = [_turn_from_dict(item) for item in turns]
    fallback = build_follow_up(topic, learner_text, score, turn_number, state)
    tutor_text, recovery_used = _safe_tutor_reply(provider, payload, topic, state, transcript, "follow_up", fallback)

    apply_conversation_turn_progress(state, topic, turn, is_first_turn=turn_number == 1)
    memory = conversation_memory(state)

    session["turns"] = turns
    reached_goal = len(turns) >= int(session.get("max_turns", 4))
    post_call_summary = None
    if reached_goal and not session.get("post_call_summary"):
        post_call_summary = persist_post_call_summary(state, topic, turns)
        session["post_call_summary"] = post_call_summary
    save_state(_path(payload), state)
    return {
        "ok": True,
        "profile": profile_for(state, provider),
        "session": session,
        "turn": turn,
        "tutor_message": tutor_text,
        "done": reached_goal,
        "post_call_summary": post_call_summary,
        "logs": [
            f"[Fluency Evaluator Agent] Scored turn {turn_number}: {score:.2f}.",
            f"[Speaking Tutor Agent] Next prompt adapts to {topic['complexity']} complexity.",
            f"[Memory Agent] Saved conversation progress. Next goal: {memory['next_speaking_goal']}",
        ] + (["[Conversation Orchestrator] Used recovery prompt after empty model response."] if recovery_used else []),
    }


def conversation_end(payload: dict[str, Any]) -> dict[str, Any]:
    state = _load(payload)
    provider = OpenAIProvider()
    raw_turns = payload.get("turns") if isinstance(payload.get("turns"), list) else []
    topic = _coerce_conversation_topic(payload.get("topic"), state)
    if not raw_turns:
        return {
            "ok": True,
            "profile": profile_for(state, provider),
            "post_call_summary": None,
            "logs": ["[Conversation Orchestrator] Call ended with no scored turns."],
        }

    topic["speaking_confidence_before"] = float(conversation_memory(state).get("speaking_confidence", 0.30) or 0.30)
    turns = []
    for index, raw_turn in enumerate(raw_turns, start=1):
        if not isinstance(raw_turn, dict):
            continue
        learner_text = str(raw_turn.get("learner_text") or raw_turn.get("learner") or "").strip()
        if not learner_text:
            continue
        score = raw_turn.get("score")
        feedback = str(raw_turn.get("feedback") or "")
        correction = raw_turn.get("correction")
        mistake = raw_turn.get("mistake") if isinstance(raw_turn.get("mistake"), dict) else None
        if score is None:
            score, feedback, correction, mistake = evaluate_reply_with_metadata(topic, learner_text, state)
        turns.append(
            {
                "turn_number": _bounded_int(raw_turn.get("turn_number"), 1, 100, index),
                "tutor_text": str(raw_turn.get("tutor_text") or raw_turn.get("tutor") or ""),
                "learner_text": learner_text,
                "topic": str(topic.get("topic") or "voice call"),
                "complexity": str(topic.get("complexity") or "live conversation"),
                "video_on": bool(raw_turn.get("video_on", payload.get("video") == "on")),
                "video_object": raw_turn.get("video_object"),
                "score": float(score),
                "feedback": feedback or "Conversation turn scored from realtime transcript.",
                "correction": correction,
                "mistake": mistake,
            }
        )

    if not turns:
        return {
            "ok": True,
            "profile": profile_for(state, provider),
            "post_call_summary": None,
            "logs": ["[Conversation Orchestrator] Call ended with no scored turns."],
        }

    average_score = sum(float(turn["score"]) for turn in turns) / len(turns)
    apply_turn_progress(
        state,
        topic,
        {
            "turns": turns,
            "score": average_score,
            "aggregate_turns": len(turns),
            "video_on": bool(payload.get("video") == "on"),
            "video_object": payload.get("video_object"),
            "fluency_weight": 0.25,
            "confidence_delta": 0.035 if average_score >= 0.45 else -0.02,
            "speaking_delta": 0.035 if average_score >= 0.45 else -0.015,
        },
        is_first_turn=True,
    )
    summary = persist_post_call_summary(state, topic, turns)
    save_state(_path(payload), state)
    return {
        "ok": True,
        "profile": profile_for(state, provider),
        "post_call_summary": summary,
        "logs": [
            f"[Conversation Orchestrator] Persisted voice call summary for {topic['topic']}.",
            f"[Fluency Evaluator Agent] Scored {len(turns)} realtime turns; average {average_score:.2f}.",
        ],
    }


def home_summary(payload: dict[str, Any]) -> dict[str, Any]:
    state = _load(payload)
    language = active_language(state)
    data = language_state(state, language)
    due_reviews = due_review_items(state)
    due_mistakes = due_mistake_items(state)
    today, log = _today_recommendation(state, due_reviews, due_mistakes)
    counts = {
        "events": len(data.get("history", [])) if isinstance(data.get("history"), list) else 0,
        "mistakes": len(data.get("mistake_memory", {})) if isinstance(data.get("mistake_memory"), dict) else 0,
        "reviews_due": len(due_reviews),
    }
    return {
        "ok": True,
        "recovered": _was_recovered(state),
        "profile": profile_for(state),
        "today": today,
        "review_preview": _review_preview(state, due_reviews, due_mistakes),
        "recent_progress": _recent_progress(state),
        "speaking_confidence": _speaking_confidence_summary(state),
        "memory_counts": counts,
        "session_checkpoints": session_checkpoints(payload).get("checkpoints", {}),
        "logs": _recovery_logs(state) + [log],
    }


def session_checkpoints(payload: dict[str, Any]) -> dict[str, Any]:
    path = _path(payload)
    lesson = _read_checkpoint(_checkpoint_path(path, "current_lesson.json"))
    call = _read_checkpoint(_checkpoint_path(path, "current_call.json"))
    return {
        "ok": True,
        "checkpoints": {
            "lesson": lesson,
            "call": call,
        },
        "logs": ["[Session Recovery Agent] Checked interrupted-session checkpoints."],
    }


def lesson_checkpoint(payload: dict[str, Any]) -> dict[str, Any]:
    path = _path(payload)
    existing = _read_checkpoint(_checkpoint_path(path, "current_lesson.json"), delete_expired=False)
    created_at = existing.get("created_at") if isinstance(existing, dict) else None
    _write_lesson_checkpoint(
        path,
        _language(payload),
        payload.get("lesson") if isinstance(payload.get("lesson"), dict) else {},
        payload.get("quiz") if isinstance(payload.get("quiz"), list) else [],
        payload.get("answers") if isinstance(payload.get("answers"), list) else [],
        created_at=created_at,
    )
    return {"ok": True, "logs": ["[Session Recovery Agent] Saved lesson draft checkpoint."]}


def lesson_checkpoint_discard(payload: dict[str, Any]) -> dict[str, Any]:
    _delete_checkpoint(_checkpoint_path(_path(payload), "current_lesson.json"))
    return {"ok": True, "logs": ["[Session Recovery Agent] Discarded interrupted lesson checkpoint."]}


def call_checkpoint(payload: dict[str, Any]) -> dict[str, Any]:
    path = _path(payload)
    existing = _read_checkpoint(_checkpoint_path(path, "current_call.json"), delete_expired=False)
    created_at = existing.get("created_at") if isinstance(existing, dict) else None
    data = {
        "type": "call",
        "language": _language(payload),
        "topic": payload.get("topic") if isinstance(payload.get("topic"), dict) else {},
        "turns": payload.get("turns") if isinstance(payload.get("turns"), list) else [],
        "video": "on" if payload.get("video") == "on" else "off",
        "video_object": payload.get("video_object"),
        "created_at": created_at or utc_now(),
        "updated_at": utc_now(),
    }
    _write_checkpoint(_checkpoint_path(path, "current_call.json"), data)
    return {"ok": True, "logs": ["[Session Recovery Agent] Saved call transcript checkpoint."]}


def call_checkpoint_discard(payload: dict[str, Any]) -> dict[str, Any]:
    _delete_checkpoint(_checkpoint_path(_path(payload), "current_call.json"))
    return {"ok": True, "logs": ["[Session Recovery Agent] Discarded interrupted call checkpoint."]}


def call_checkpoint_summarize(payload: dict[str, Any]) -> dict[str, Any]:
    path = _path(payload)
    checkpoint = _read_checkpoint(_checkpoint_path(path, "current_call.json"))
    if not checkpoint:
        return {
            "ok": False,
            "error": "No interrupted call checkpoint was found.",
            "logs": ["[Session Recovery Agent] No interrupted call checkpoint to summarize."],
        }
    result = conversation_end(
        {
            **payload,
            "topic": checkpoint.get("topic", {}),
            "turns": checkpoint.get("turns", []),
            "video": checkpoint.get("video", "off"),
            "video_object": checkpoint.get("video_object"),
        }
    )
    if result.get("ok"):
        _delete_checkpoint(_checkpoint_path(path, "current_call.json"))
        result["logs"] = result.get("logs", []) + ["[Session Recovery Agent] Summarized interrupted call checkpoint."]
    return result


def memory_inspect(payload: dict[str, Any]) -> dict[str, Any]:
    state = _load(payload)
    language = active_language(state)
    inspected = _memory_payload(state, language)
    inspected["logs"] = [f"[Memory Inspector Agent] Opened sanitized {language} memory."]
    return inspected


def memory_export(payload: dict[str, Any]) -> dict[str, Any]:
    path = _path(payload)
    language = _language(payload) if payload.get("language") else None
    state = load_state(path, language)
    if language and active_language(state) != language:
        state["active_language"] = language
        language_state(state, language)
    exported_at = utc_now()
    state.setdefault("privacy", {})["last_exported_at"] = exported_at
    save_state(path, state)
    scope = str(payload.get("scope") or "language").strip().lower()
    if scope == "all":
        data = sanitize_memory_payload(
            {
                "schema_version": state.get("schema_version"),
                "active_language": active_language(state),
                "exported_at": exported_at,
                "learner": _learner_payload(state),
                "privacy": _privacy_payload(state),
                "languages": {
                    lang: _language_memory_sections(state, lang)
                    for lang in sorted(state.get("languages", {}))
                    if isinstance(state.get("languages", {}).get(lang), dict)
                },
                "redactions": _redaction_labels(),
            }
        )
    else:
        data = _memory_payload(state, language or active_language(state))
        data["exported_at"] = exported_at
    return {
        "ok": True,
        "filename": f"fluentai-memory-{datetime.now(timezone.utc).strftime('%Y%m%d')}.json",
        "data": data,
        "logs": [f"[Privacy Agent] Prepared sanitized {scope} memory export."],
    }


def memory_reset_language(payload: dict[str, Any]) -> dict[str, Any]:
    language = _language(payload)
    if str(payload.get("confirm") or "") != f"RESET {language}":
        return {
            "ok": False,
            "error": f'Type "RESET {language}" to reset this language.',
            "logs": ["[Privacy Agent] Language reset confirmation did not match."],
    }
    path = _path(payload)
    state = load_state(path, language)
    reset_language_state(state, language)
    add_event(
        state,
        {
            "type": "language_reset",
            "source": "privacy_controls",
            "summary": f"Reset {language} learning memory.",
            "payload": {"language": language},
        },
        language,
    )
    save_state(path, state)
    return {
        "ok": True,
        "profile": profile_for(state),
        "memory": _memory_payload(state, language),
        "logs": [f"[Privacy Agent] Reset {language} memory and preserved other languages."],
    }


def memory_delete_all(payload: dict[str, Any]) -> dict[str, Any]:
    if str(payload.get("confirm") or "") != "DELETE ALL MEMORY":
        return {
            "ok": False,
            "error": 'Type "DELETE ALL MEMORY" to delete all memory.',
            "logs": ["[Privacy Agent] Delete-all confirmation did not match."],
        }
    path = _path(payload)
    language = _language(payload) if payload.get("language") else "Spanish"
    if path.exists():
        try:
            language = active_language(load_state(path, language))
        except (json.JSONDecodeError, OSError):
            pass
    state = delete_all_memory(path, language)
    return {
        "ok": True,
        "profile": profile_for(state),
        "logs": ["[Privacy Agent] Deleted all local memory and restored a fresh profile."],
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
        "level_confidence": profile.get("level_confidence", 0.45),
        "xp": profile.get("xp", 0),
        "streak_days": profile.get("streak_days", 1),
        "weak_topics": data.get("weak_topics", []),
        "learning_goals": profile.get("learning_goals", []),
        "onboarded_at": state["learner"].get("onboarded_at"),
        "last_onboarding_at": state["learner"].get("last_onboarding_at"),
        "self_reported_level": profile.get("self_reported_level"),
        "speaking_comfort": profile.get("speaking_comfort"),
        "placement_completed_at": profile.get("placement_completed_at"),
        "placement_method": profile.get("placement_method"),
        "first_practice_goal": profile.get("first_practice_goal"),
        "judged_strengths": profile.get("judged_strengths", []),
        "judged_weaknesses": profile.get("judged_weaknesses", []),
        "fluency_score": memory.get("fluency_score", 0.30),
        "speaking_confidence": memory.get("speaking_confidence", 0.30),
        "next_speaking_goal": memory.get("next_speaking_goal", ""),
        "next_conversation_goal": memory.get("next_conversation_goal"),
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


def _safe_tutor_reply(
    provider: OpenAIProvider,
    payload: dict[str, Any],
    topic: dict[str, Any],
    state: dict[str, Any],
    transcript: list[ConversationTurn],
    phase: str,
    fallback: str,
) -> tuple[str | None, bool]:
    first = _tutor_reply(provider, payload, topic, state, transcript, phase, fallback)
    if first:
        return first, False
    second = _tutor_reply(provider, payload, topic, state, transcript, phase, fallback)
    if second:
        return second, False
    cleaned = " ".join(str(fallback or "").strip().split())
    if cleaned:
        return cleaned[:500], True
    return None, False


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
        mistake=value.get("mistake") if isinstance(value.get("mistake"), dict) else None,
    )


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    return [text] if text else []


def _self_reported_level(value: Any) -> str:
    raw = str(value or "not sure").strip()
    normalized = raw.lower()
    mapping = {"b1+": "B1+", "a1": "A1", "a2": "A2"}
    if normalized in mapping:
        return mapping[normalized]
    if normalized in {"new", "not sure"}:
        return normalized
    return "not sure"


def _speaking_comfort(value: Any) -> str:
    raw = str(value or "some").strip().lower()
    return raw if raw in SPEAKING_COMFORT_SEEDS else "some"


def _next_timestamp_after(previous: Any) -> str:
    now = utc_now()
    if not previous:
        return now
    try:
        previous_dt = datetime.fromisoformat(str(previous).replace("Z", "+00:00"))
        now_dt = datetime.fromisoformat(now)
    except ValueError:
        return now
    if now_dt <= previous_dt:
        return (previous_dt + timedelta(seconds=1)).replace(microsecond=0).isoformat()
    return now


def _placement_session_id() -> str:
    stamp = datetime.fromisoformat(utc_now()).strftime("%Y%m%d_%H%M%S")
    return f"placement_{stamp}"


def _written_prompt_from(quiz: list[dict[str, Any]], lesson: dict[str, Any]) -> dict[str, Any]:
    for item in quiz:
        if item.get("type") == "open_ended":
            return copy.deepcopy(item)
    return {
        "type": "open_ended",
        "skill": str(lesson.get("focus_skill") or "writing"),
        "topic": str(lesson.get("topic") or "introductions"),
        "prompt": f"Write one short {lesson.get('language', 'Spanish')} sentence about {lesson.get('topic', 'yourself')}.",
        "answer": str((lesson.get("examples") or [["Me llamo Ana."]])[0][0]),
        "acceptable_answers": [str((lesson.get("examples") or [["Me llamo Ana."]])[0][0])],
        "keywords": [str(word).split(" ")[0] for word in (lesson.get("vocabulary") or [["hola"]])[:3]],
    }


def _quiz_result_score(result: QuizResult | None) -> float | None:
    if result is None:
        return None
    if result.correct:
        return 1.0
    if result.actual.strip() and result.error_category in {"unnatural", "word_order"}:
        return 0.62
    if result.actual.strip():
        return 0.35
    return 0.0


def _judged_level(score: float) -> str:
    if score < 0.45:
        return "A1"
    if score <= 0.72:
        return "A2"
    return "B1"


def _placement_confidence(has_written: bool, has_conversation: bool) -> float:
    if has_written and has_conversation:
        return 0.70
    if has_written:
        return 0.60
    return 0.50


def _level_rank(level: str) -> int:
    order = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6}
    return order.get(str(level), 1)


def _first_practice_goal(level: str) -> str:
    if level == "A1":
        return "Build basic introductions and daily phrases."
    if level == "A2":
        return "Practice daily introductions with complete sentences."
    return "Practice opinions and short explanations with clear reasons."


def _first_conversation_goal(level: str, language: str) -> dict[str, Any]:
    if level == "A1":
        topic = "introductions"
        skill = "speaking"
        instruction = f"Answer two simple introduction questions in full {language} sentences."
        reason = "Placement starts beginner conversation practice with names and simple identity."
    elif level == "A2":
        topic = "daily routines"
        skill = "fluency"
        instruction = f"Answer two daily-routine questions in complete {language} sentences."
        reason = "Placement showed readiness for simple connected sentences."
    else:
        topic = "opinions"
        skill = "fluency"
        instruction = f"Give one opinion in {language} and support it with porque or a clear reason."
        reason = "Placement showed readiness for richer conversation topics."
    return {"source": "placement", "topic": topic, "skill": skill, "instruction": instruction, "reason": reason}


def _complete_skip_beginner_placement(state: dict[str, Any], language: str) -> dict[str, Any]:
    data = language_state(state, language)
    profile = data.setdefault("profile", {})
    completed_at = utc_now()
    profile["current_level"] = "A1"
    profile["level_confidence"] = 0.35
    profile["placement_completed_at"] = completed_at
    profile["placement_method"] = "skip_beginner"
    profile["first_practice_goal"] = "Build basic introductions and daily phrases."
    profile["judged_strengths"] = []
    profile["judged_weaknesses"] = ["speaking", "vocabulary"]
    memory = conversation_memory(state, language)
    memory["next_speaking_goal"] = f"Answer two simple introduction questions in full {language} sentences."
    memory["next_conversation_goal"] = _first_conversation_goal("A1", language)
    data["weak_topics"] = recalculate_weak_topics(state, language=language)
    add_event(
        state,
        {
            "type": "placement_completed",
            "source": "placement_bridge",
            "summary": "Placement skipped; learner starts as A1.",
            "occurred_at": completed_at,
            "payload": {
                "method": "skip_beginner",
                "self_reported_level": profile.get("self_reported_level"),
                "judged_level": "A1",
                "level_cap_applied": False,
                "quiz_score": "0/0",
                "written_score": None,
                "conversation_score": None,
                "strongest_skills": [],
                "weakest_skills": profile["judged_weaknesses"],
                "first_practice_goal": profile["first_practice_goal"],
                "first_conversation_goal": memory["next_conversation_goal"]["instruction"],
            },
        },
        language,
    )
    return {
        "judged_level": "A1",
        "level_confidence": 0.35,
        "strongest_skills": [],
        "weakest_skills": profile["judged_weaknesses"],
        "first_practice_goal": profile["first_practice_goal"],
        "first_conversation_goal": memory["next_conversation_goal"]["instruction"],
    }


def _apply_placement_seeds(
    state: dict[str, Any],
    language: str,
    results: list[QuizResult],
    written_result: QuizResult | None,
    written_score: float | None,
    conversation_prompt: dict[str, Any],
    conversation_score: float | None,
    event_id: str,
) -> None:
    base_scores = skill_scores(state, language)
    grouped: dict[str, list[float]] = {}
    for result in results:
        grouped.setdefault(result.skill or "vocabulary", []).append(1.0 if result.correct else 0.0)
    if written_result is not None and written_score is not None:
        grouped.setdefault("writing", []).append(written_score)
        grouped.setdefault(written_result.skill or "writing", []).append(written_score)
    evidence = {"event_id": event_id, "mode": "placement", "note": "Initial placement seed"}
    for skill, values in grouped.items():
        placement_score = sum(values) / len(values)
        seed = 0.18 + placement_score * 0.64
        set_skill_score(state, skill, max(base_scores.get(skill, 0.30), seed), language, evidence={**evidence, "skill": skill})

    if conversation_score is not None:
        for skill in ("speaking", "fluency"):
            seed = 0.18 + conversation_score * 0.64
            set_skill_score(state, skill, max(base_scores.get(skill, 0.30), seed), language, evidence={**evidence, "skill": skill})
        topic_name = str(conversation_prompt.get("topic") or "introductions")
        set_topic_score(
            state,
            topic_name,
            0.18 + conversation_score * 0.64,
            language,
            modality="spoken_use",
            evidence={**evidence, "topic": topic_name},
        )

    topic_base = topic_scores(state, language)
    by_topic: dict[str, list[float]] = {}
    for result in results:
        by_topic.setdefault(result.topic or "placement", []).append(1.0 if result.correct else 0.0)
    for topic, values in by_topic.items():
        placement_score = sum(values) / len(values)
        set_topic_score(
            state,
            topic,
            max(topic_base.get(topic, 0.30), 0.18 + placement_score * 0.64),
            language,
            evidence={**evidence, "topic": topic},
        )


def _strongest_weakest(scores: dict[str, float]) -> tuple[list[str], list[str]]:
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    strongest = [skill for skill, _score in ordered[:2]]
    weakest = [skill for skill, _score in sorted(scores.items(), key=lambda item: item[1])[:2]]
    return strongest, weakest


def _bounded_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = 0.30
    return max(0.05, min(0.99, score))


def _update_event_payload(state: dict[str, Any], event_id: str, payload: dict[str, Any], language: str) -> None:
    for event in state.get("events", []):
        if isinstance(event, dict) and event.get("id") == event_id:
            event.setdefault("payload", {}).update(copy.deepcopy(payload))
    for event in language_state(state, language).get("history", []):
        if isinstance(event, dict) and event.get("id") == event_id:
            event.setdefault("payload", {}).update(copy.deepcopy(payload))


def _coerce_conversation_topic(value: Any, state: dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, dict):
        topic = dict(value)
    else:
        topic_name = str(value or "voice call").strip() or "voice call"
        topic = {"topic": topic_name}
    topic.setdefault("topic", "voice call")
    topic.setdefault("complexity", "live conversation")
    topic.setdefault("support", f"Model answer: {conversation_memory(state).get('next_speaking_goal', 'Answer in a complete sentence.')}")
    topic.setdefault("keywords", [])
    if not isinstance(topic.get("keywords"), list):
        topic["keywords"] = []
    topic["lesson_topic"] = conversation_topic_to_lesson_topic(str(topic.get("topic") or ""))
    return topic


def _today_recommendation(
    state: dict[str, Any],
    due_reviews: list[tuple[datetime, str]],
    due_mistakes: list[tuple[datetime, dict[str, Any]]],
) -> tuple[dict[str, Any], str]:
    profile = profile_state(state)
    memory = conversation_memory(state)
    data = language_state(state)
    if due_reviews:
        topic = due_reviews[0][1]
        return (
            {
                "kind": "due_review",
                "title": "Review due phrases",
                "body": f"{len(due_reviews)} item{'s' if len(due_reviews) != 1 else ''} due; start with {topic}.",
                "cta": "Review due phrases",
                "mode": "lesson",
                "topic": topic,
                "reason": "Due reviews come before fresh lessons.",
            },
            "[Home Agent] Recommended due review before fresh lesson.",
        )
    if due_mistakes:
        mistake = due_mistakes[0][1]
        topic = str(mistake.get("topic") or "a weak topic")
        return (
            {
                "kind": "due_mistake",
                "title": "Practice yesterday's weak topic",
                "body": f"Review the correction for {topic}: {mistake.get('corrected_form') or 'the model phrase'}.",
                "cta": "Practice yesterday's weak topic",
                "mode": "lesson",
                "topic": topic,
                "reason": "Due mistakes come before new material.",
            },
            "[Home Agent] Recommended due mistake practice.",
        )
    if _conversation_neglected(state):
        return (
            {
                "kind": "neglected_conversation",
                "title": "Talk with your tutor",
                "body": "You have practiced lessons without a tutor call recently.",
                "cta": "Start live tutor call",
                "mode": "conversation",
                "topic": "",
                "reason": "You have practiced lessons without a tutor call recently.",
            },
            "[Home Agent] Recommended conversation because tutor calls were neglected.",
        )
    if _lesson_goal_waiting_for_conversation(state):
        goal = memory.get("next_conversation_goal")
        topic = str(goal.get("topic") or "") if isinstance(goal, dict) else ""
        instruction = str(goal.get("instruction") or "Use the last lesson in conversation.") if isinstance(goal, dict) else ""
        return (
            {
                "kind": "lesson_goal_conversation",
                "title": "Use the last lesson out loud",
                "body": instruction,
                "cta": "Use this in conversation",
                "mode": "conversation",
                "topic": topic,
                "reason": "The last lesson created a conversation goal that has not been practiced yet.",
            },
            "[Home Agent] Recommended conversation to use the latest lesson goal.",
        )
    daily_summary = data.get("daily_summary", {}) if isinstance(data.get("daily_summary"), dict) else {}
    if profile.get("first_practice_goal") and int(daily_summary.get("lessons_completed", 0) or 0) == 0:
        return (
            {
                "kind": "first_practice_goal",
                "title": "Start your first practice goal",
                "body": str(profile.get("first_practice_goal")),
                "cta": "Start today's lesson",
                "mode": "lesson",
                "topic": "",
                "reason": "Your placement set this as the first practice goal.",
            },
            "[Home Agent] Recommended first practice goal for today.",
        )
    return (
        {
            "kind": "fresh_lesson",
            "title": "Start today's lesson",
            "body": f"Build the next adaptive {active_language(state)} lesson from your current level and weak topics.",
            "cta": "Start today's lesson",
            "mode": "lesson",
            "topic": "",
            "reason": "No due reviews, due mistakes, or pending conversation goals are ahead of a fresh lesson.",
        },
        "[Home Agent] Recommended a fresh adaptive lesson.",
    )


def _conversation_neglected(state: dict[str, Any]) -> bool:
    history = language_state(state).get("history", [])
    if not isinstance(history, list):
        return False
    last_conversation_index = -1
    lesson_count = 0
    for index, event in enumerate(history):
        if not isinstance(event, dict):
            continue
        if event.get("type") == "conversation_started":
            last_conversation_index = index
        if event.get("type") == "lesson_completed":
            lesson_count += 1
    lessons_since = sum(
        1
        for event in history[last_conversation_index + 1 :]
        if isinstance(event, dict) and event.get("type") == "lesson_completed"
    )
    sessions_completed = int(conversation_memory(state).get("sessions_completed", 0) or 0)
    return lessons_since >= 3 or (sessions_completed == 0 and lesson_count >= 1)


def _lesson_goal_waiting_for_conversation(state: dict[str, Any]) -> bool:
    goal = conversation_memory(state).get("next_conversation_goal")
    if not isinstance(goal, dict) or goal.get("source") != "lesson" or not goal.get("instruction"):
        return False
    history = language_state(state).get("history", [])
    if not isinstance(history, list):
        return True
    last_lesson_index = -1
    last_conversation_index = -1
    for index, event in enumerate(history):
        if not isinstance(event, dict):
            continue
        if event.get("type") == "lesson_completed":
            last_lesson_index = index
        if event.get("type") == "conversation_started":
            last_conversation_index = index
    return last_lesson_index >= 0 and last_conversation_index < last_lesson_index


def _review_preview(
    state: dict[str, Any],
    due_reviews: list[tuple[datetime, str]],
    due_mistakes: list[tuple[datetime, dict[str, Any]]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for due_at, topic in due_reviews[:3]:
        rows.append({"type": "review", "target": topic, "skill": "", "due_at": due_at.isoformat(), "source": "lesson"})
    for due_at, mistake in due_mistakes[:3]:
        rows.append(
            {
                "type": "mistake",
                "target": str(mistake.get("topic") or ""),
                "skill": str(mistake.get("skill") or ""),
                "due_at": due_at.isoformat(),
                "source": str(mistake.get("source") or "mistake_memory"),
            }
        )
    if len(rows) < 3:
        queue = review_queue(state)
        if isinstance(queue, dict):
            for item in queue.values():
                if len(rows) >= 3:
                    break
                if not isinstance(item, dict):
                    continue
                target = str(item.get("target") or item.get("topic") or "")
                if any(row["target"] == target and row["due_at"] == str(item.get("due_at") or "") for row in rows):
                    continue
                rows.append(
                    {
                        "type": str(item.get("item_type") or "review"),
                        "target": target,
                        "skill": str(item.get("skill") or ""),
                        "due_at": str(item.get("due_at") or ""),
                        "source": str(item.get("source") or "lesson"),
                    }
                )
    return rows[:3]


def _recent_progress(state: dict[str, Any]) -> list[dict[str, Any]]:
    meaningful: list[dict[str, Any]] = []
    for event in reversed(language_state(state).get("history", [])):
        if not isinstance(event, dict):
            continue
        sentence = _event_sentence(event)
        if sentence:
            meaningful.append(
                {
                    "id": event.get("id"),
                    "type": event.get("type"),
                    "occurred_at": event.get("occurred_at"),
                    "summary": sentence,
                    "relative_time": _relative_time(event.get("occurred_at")),
                }
            )
        if len(meaningful) >= 5:
            break
    return meaningful


def _event_sentence(event: dict[str, Any]) -> str:
    payload = event.get("payload", {}) if isinstance(event.get("payload"), dict) else {}
    if event.get("type") == "lesson_completed":
        score = payload.get("score")
        topic = payload.get("topic") or "a lesson"
        return f"Completed {topic} with score {score}." if score else str(event.get("summary") or "")
    if event.get("type") == "placement_completed":
        level = payload.get("judged_level") or "A1"
        method = str(payload.get("method") or "placement").replace("_", " ")
        return f"Placement set your starting level to {level} by {method}."
    summary = payload.get("post_call_summary") if isinstance(payload.get("post_call_summary"), dict) else None
    if summary:
        topic = summary.get("topic") or "conversation"
        turns = summary.get("turn_count") or 0
        return f"Finished a {turns}-turn tutor call on {topic}."
    return ""


def _speaking_confidence_summary(state: dict[str, Any]) -> dict[str, Any]:
    memory = conversation_memory(state)
    recent: list[dict[str, Any]] = []
    for event in reversed(language_state(state).get("history", [])):
        if not isinstance(event, dict):
            continue
        payload = event.get("payload", {}) if isinstance(event.get("payload"), dict) else {}
        summary = payload.get("post_call_summary") if isinstance(payload.get("post_call_summary"), dict) else None
        if summary:
            recent.append(
                {
                    "topic": summary.get("topic"),
                    "average_score": summary.get("average_score"),
                    "confidence_change": summary.get("confidence_change"),
                    "ended_at": summary.get("ended_at") or event.get("occurred_at"),
                }
            )
        elif event.get("type") == "learner_replied":
            recent.append(
                {
                    "topic": payload.get("topic"),
                    "average_score": payload.get("score"),
                    "confidence_change": "improved" if float(payload.get("score", 0) or 0) >= 0.45 else "dipped",
                    "ended_at": event.get("occurred_at"),
                }
            )
        if len(recent) >= 5:
            break
    improved = sum(1 for item in recent if item.get("confidence_change") == "improved")
    dipped = sum(1 for item in recent if item.get("confidence_change") == "dipped")
    trend = "up" if improved > dipped else "down" if dipped > improved else "flat"
    return {"score": float(memory.get("speaking_confidence", 0.30) or 0.30), "trend": trend, "recent": list(reversed(recent))}


def _memory_payload(state: dict[str, Any], language: str) -> dict[str, Any]:
    payload = {
        "ok": True,
        "language": language,
        "learner": _learner_payload(state),
        "profile": _profile_payload(state, language),
        **_language_memory_sections(state, language),
        "privacy": _privacy_payload(state),
        "redactions": _redaction_labels(),
    }
    return sanitize_memory_payload(payload)


def _language_memory_sections(state: dict[str, Any], language: str) -> dict[str, Any]:
    data = language_state(state, language)
    memory = conversation_memory(state, language)
    return {
        "skills": [
            {
                "name": name,
                "score": record.get("score"),
                "trend": record.get("trend"),
                "last_practiced": record.get("last_practiced"),
            }
            for name, record in sorted(data.get("skills", {}).items())
            if isinstance(record, dict)
        ],
        "topic_mastery": [
            {
                "topic": topic,
                "recognition": record.get("recognition"),
                "recall": record.get("recall"),
                "spoken_use": record.get("spoken_use"),
                "written_use": record.get("written_use"),
            }
            for topic, record in sorted(data.get("topic_mastery", {}).items())
            if isinstance(record, dict)
        ],
        "mistakes": [
            {
                "incorrect_form": mistake.get("incorrect_form"),
                "corrected_form": mistake.get("corrected_form"),
                "skill": mistake.get("skill"),
                "topic": mistake.get("topic"),
                "frequency": mistake.get("frequency"),
                "next_review": mistake.get("next_review"),
            }
            for mistake in data.get("mistake_memory", {}).values()
            if isinstance(mistake, dict)
        ],
        "review_queue": [
            {
                "id": item.get("id"),
                "target": item.get("target") or item.get("topic"),
                "skill": item.get("skill"),
                "due_at": item.get("due_at"),
                "source": item.get("source"),
            }
            for item in data.get("review_queue", {}).values()
            if isinstance(item, dict)
        ],
        "conversation": {
            "speaking_confidence": memory.get("speaking_confidence"),
            "fluency_score": memory.get("fluency_score"),
            "sessions_completed": memory.get("sessions_completed"),
            "total_turns": memory.get("total_turns"),
            "next_speaking_goal": memory.get("next_speaking_goal"),
            "next_conversation_goal": memory.get("next_conversation_goal"),
            "last_video_context": memory.get("last_video_context"),
            "post_call_summaries": list(memory.get("post_call_summaries", []))[-10:]
            if isinstance(memory.get("post_call_summaries"), list)
            else [],
        },
        "recent_events": [
            {
                "id": event.get("id"),
                "type": event.get("type"),
                "occurred_at": event.get("occurred_at"),
                "summary": event.get("summary"),
            }
            for event in data.get("history", [])[-20:]
            if isinstance(event, dict)
        ],
    }


def _learner_payload(state: dict[str, Any]) -> dict[str, Any]:
    learner = state.get("learner", {}) if isinstance(state.get("learner"), dict) else {}
    return {
        "display_name": learner.get("display_name"),
        "motivation": learner.get("motivation"),
        "active_goals": learner.get("active_goals", []),
        "preferred_session_length_minutes": learner.get("preferred_session_length_minutes"),
        "onboarded_at": learner.get("onboarded_at"),
        "last_onboarding_at": learner.get("last_onboarding_at"),
    }


def _profile_payload(state: dict[str, Any], language: str) -> dict[str, Any]:
    profile = profile_state(state, language)
    return {
        "target_language": profile.get("target_language"),
        "current_level": profile.get("current_level"),
        "level_confidence": profile.get("level_confidence"),
        "learning_goals": profile.get("learning_goals", []),
        "first_practice_goal": profile.get("first_practice_goal"),
        "judged_strengths": profile.get("judged_strengths", []),
        "judged_weaknesses": profile.get("judged_weaknesses", []),
        "placement_completed_at": profile.get("placement_completed_at"),
        "placement_method": profile.get("placement_method"),
    }


def _privacy_payload(state: dict[str, Any]) -> dict[str, Any]:
    privacy = state.get("privacy", {}) if isinstance(state.get("privacy"), dict) else {}
    return {
        "local_only": privacy.get("local_only", True),
        "store_raw_audio": privacy.get("store_raw_audio", False),
        "store_raw_video": privacy.get("store_raw_video", False),
        "store_camera_summaries": privacy.get("store_camera_summaries", True),
        "allow_export": privacy.get("allow_export", True),
        "allow_delete": privacy.get("allow_delete", True),
        "allow_language_reset": privacy.get("allow_language_reset", True),
        "last_exported_at": privacy.get("last_exported_at"),
    }


SECRET_PATTERN = re.compile(
    r"(sk-[A-Za-z0-9_-]{8,}|(?:api[_-]?key|client[_-]?secret|authorization)\s*[:=]\s*['\"]?[A-Za-z0-9._-]{8,})",
    re.IGNORECASE,
)
DATA_URL_PATTERN = re.compile(r"data:image/[^;]+;base64,[A-Za-z0-9+/=\s]+", re.IGNORECASE)
SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "client_secret",
    "realtime_client_secret",
    "raw",
    "raw_audio",
    "raw_video",
    "audio_data",
    "video_data",
    "image",
    "image_data",
    "image_data_url",
    "transcript",
    "raw_transcript",
    "stderr",
    "stdout",
}


def sanitize_memory_payload(value: Any) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            normalized_key = key_text.lower()
            if normalized_key in SENSITIVE_KEYS or normalized_key.endswith("_transcript"):
                continue
            clean[key_text] = sanitize_memory_payload(item)
        return clean
    if isinstance(value, list):
        return [sanitize_memory_payload(item) for item in value]
    if isinstance(value, str):
        if DATA_URL_PATTERN.search(value):
            return "[redacted image data]"
        if SECRET_PATTERN.search(value):
            return SECRET_PATTERN.sub("[redacted secret]", value)
        return value
    return value


def _redaction_labels() -> list[str]:
    return ["raw audio", "raw video", "image data URLs", "API keys"]


def _relative_time(value: Any) -> str:
    parsed = _parse_datetime(value)
    if not parsed:
        return "recently"
    delta = datetime.now(timezone.utc) - parsed
    if delta.days <= 0:
        return "today"
    if delta.days == 1:
        return "yesterday"
    if delta.days < 7:
        return f"{delta.days} days ago"
    weeks = delta.days // 7
    return f"{weeks} week{'s' if weeks != 1 else ''} ago"


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _load(payload: dict[str, Any]) -> dict[str, Any]:
    language = _language(payload) if "language" in payload else None
    path = _path(payload)
    state = load_state(path, language)
    if language and active_language(state) != language:
        state["active_language"] = language
        language_state(state, language)
        save_state(path, state)
    return state


def _was_recovered(state: dict[str, Any]) -> bool:
    return bool(state.get("_recovered_from_corruption"))


def _recovery_logs(state: dict[str, Any]) -> list[str]:
    if not _was_recovered(state):
        return []
    return ["[Memory Agent] Your progress file was damaged; a backup was saved."]


def _language(payload: dict[str, Any]) -> str:
    raw = str(payload.get("language") or "Spanish").strip().lower()
    return SUPPORTED_LANGUAGES.get(raw, "Spanish")


def _path(payload: dict[str, Any]) -> Path:
    return Path(str(payload.get("state_path") or DEFAULT_PROGRESS_PATH))


def _sessions_dir(path: Path) -> Path:
    return path.parent / "sessions"


def _checkpoint_path(path: Path, filename: str) -> Path:
    return _sessions_dir(path) / filename


def _write_checkpoint(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=True), encoding="utf-8")


def _delete_checkpoint(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _read_checkpoint(path: Path, *, delete_expired: bool = True) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    created_at = _parse_timestamp(data.get("created_at"))
    if created_at and datetime.now(timezone.utc) - created_at > CHECKPOINT_MAX_AGE:
        if delete_expired:
            _delete_checkpoint(path)
        return None
    return data


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _write_lesson_checkpoint(
    path: Path,
    language: str,
    lesson: dict[str, Any],
    quiz: list[Any],
    answers: list[Any],
    *,
    created_at: str | None = None,
) -> None:
    data = {
        "type": "lesson",
        "language": language,
        "lesson": lesson,
        "quiz": quiz,
        "answers": [str(answer) for answer in answers],
        "created_at": created_at or utc_now(),
        "updated_at": utc_now(),
    }
    _write_checkpoint(_checkpoint_path(path, "current_lesson.json"), data)


def _provider_has_key(provider: OpenAIProvider) -> bool:
    return bool(getattr(provider, "api_key", None))


def _openai_required(state: dict[str, Any], provider: OpenAIProvider, message: str) -> dict[str, Any]:
    if _provider_has_key(provider) and "OPENAI_API_KEY" not in message:
        message = MODEL_FAILURE_MESSAGE
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
    "onboarding_status": onboarding_status,
    "onboarding_submit": onboarding_submit,
    "placement_start": placement_start,
    "placement_submit": placement_submit,
    "home_summary": home_summary,
    "memory_inspect": memory_inspect,
    "memory_export": memory_export,
    "memory_reset_language": memory_reset_language,
    "memory_delete_all": memory_delete_all,
    "session_checkpoints": session_checkpoints,
    "lesson_checkpoint": lesson_checkpoint,
    "lesson_checkpoint_discard": lesson_checkpoint_discard,
    "call_checkpoint": call_checkpoint,
    "call_checkpoint_discard": call_checkpoint_discard,
    "call_checkpoint_summarize": call_checkpoint_summarize,
    "status": status,
    "validate_key": validate_key,
    "realtime_client_secret": realtime_client_secret,
    "vision_analyze_frame": vision_analyze_frame,
    "lesson_start": lesson_start,
    "lesson_submit": lesson_submit,
    "conversation_start": conversation_start,
    "conversation_reply": conversation_reply,
    "conversation_end": conversation_end,
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
