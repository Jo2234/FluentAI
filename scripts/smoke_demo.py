#!/usr/bin/env python3
"""Offline FluentAI smoke demo used by humans and CI.

Runs one lesson, one text conversation, and one video-object conversation against a
temporary learner profile. No OpenAI key, browser, webcam, or desktop runtime is
required.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fluent_ai.agent import answer_quiz, evaluate_answers, generate_lesson, generate_quiz, update_progress
from fluent_ai.conversation import run_conversation
from fluent_ai.state import default_state, load_state, save_state


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="fluentai-smoke-") as tmp:
        state_path = Path(tmp) / "progress.json"
        state = default_state("Spanish")
        save_state(state_path, state)

        before_xp = state["learner"]["xp"]
        lesson = generate_lesson(state)
        quiz = generate_quiz(state, lesson)
        answers = answer_quiz(quiz, state, "auto")
        results = evaluate_answers(quiz, answers)
        update_progress(state, lesson, results)
        save_state(state_path, state)

        if state["learner"]["xp"] <= before_xp:
            raise SystemExit("lesson smoke did not increase XP")
        if not (5 <= len(quiz) <= 8):
            raise SystemExit(f"quiz smoke expected 5-8 questions, got {len(quiz)}")

        transcript, state, _topic = run_conversation(
            state=load_state(state_path, "Spanish"),
            turns=2,
            mode="auto",
            video_on=False,
            video_object=None,
        )
        if len(transcript) != 2 or not transcript[0].tutor_text:
            raise SystemExit("text conversation smoke failed")
        save_state(state_path, state)

        transcript, state, _topic = run_conversation(
            state=load_state(state_path, "Spanish"),
            turns=2,
            mode="auto",
            video_on=True,
            video_object="apple",
        )
        if "manzana" not in transcript[0].tutor_text.lower():
            raise SystemExit("video-object smoke did not mention manzana")
        save_state(state_path, state)

        final_state = load_state(state_path, "Spanish")
        summary = {
            "ok": True,
            "lesson_topic": lesson["topic"],
            "quiz_questions": len(quiz),
            "xp": final_state["learner"]["xp"],
            "conversation_sessions": final_state["conversation_memory"]["sessions_completed"],
            "conversation_turns": final_state["conversation_memory"]["total_turns"],
            "last_video_object": final_state["conversation_memory"]["last_video_object"],
            "state_path": str(state_path),
        }
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
