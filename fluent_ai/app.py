from __future__ import annotations

import argparse
import time
from pathlib import Path

from fluent_ai.agent import (
    answer_quiz,
    current_level,
    evaluate_answers,
    generate_lesson,
    generate_quiz,
    progress_report,
    recommendation,
    snapshot_progress,
    update_progress,
)
from fluent_ai.conversation import run_conversation
from fluent_ai.openai_provider import OpenAIProvider
from fluent_ai.state import load_state, save_state


DEFAULT_PROGRESS_PATH = Path("data/progress.json")


def agent_log(agent_name: str, message: str) -> None:
    print(f"[{agent_name}] {message}")


def run_loop(
    state_path: Path,
    language: str,
    duration_minutes: float,
    interval_seconds: float,
    mode: str,
    max_cycles: int | None,
    once: bool,
) -> None:
    state = load_state(state_path, language)
    provider = OpenAIProvider()
    deadline = time.monotonic() + duration_minutes * 60
    cycle = 1

    agent_log("Orchestrator", "FluentAI always-on tutor started.")
    agent_log("Orchestrator", f"Memory file: {state_path}")
    agent_log("Orchestrator", f"Mode: {mode}")
    agent_log("OpenAI Model Agent", provider.status())
    if once:
        agent_log("Orchestrator", "Running one on-demand lesson cycle.")
    elif max_cycles:
        agent_log("Orchestrator", f"Max cycles: {max_cycles}")

    while True:
        state = load_state(state_path, language)
        before = snapshot_progress(state)
        weak_topics = ", ".join(state.get("weak_topics", []))
        goals = "; ".join(state["learner"].get("learning_goals", []))

        print("\n" + "=" * 72)
        agent_log(
            "Memory Agent",
            f"Loaded level {current_level(state)}, streak {state['learner'].get('streak_days', 1)} days, weak topics: {weak_topics}.",
        )
        agent_log("Memory Agent", f"Learning goals: {goals}")

        lesson = generate_lesson(state)
        if provider.available:
            enhanced_lesson = provider.enhance_lesson(state, lesson)
            if enhanced_lesson.get("source") == "openai":
                lesson = enhanced_lesson
                agent_log("OpenAI Model Agent", "Enhanced the lesson content with the OpenAI Responses API.")
            elif provider.last_error:
                agent_log("OpenAI Model Agent", f"Using local lesson fallback after API issue: {provider.last_error}")
        agent_log(
            "Lesson Generator Agent",
            f"Created a {lesson['minutes']}-minute {lesson['level']} lesson on {lesson['topic']} ({lesson['difficulty']}).",
        )
        print_lesson(lesson)

        agent_log("Notification Agent", f"Lesson ready: {lesson['topic']} practice starts now.")

        quiz = generate_quiz(state, lesson)
        question_types = ", ".join(sorted({question["type"] for question in quiz}))
        agent_log("Adaptive Quiz Agent", f"Generated {len(quiz)} questions: {question_types}.")

        answers = answer_quiz(quiz, state, mode)
        results = evaluate_answers(quiz, answers)

        correct_count = sum(1 for result in results if result.correct)
        agent_log("Evaluator Agent", f"Graded quiz: {correct_count}/{len(results)} correct.")
        print_feedback(results)

        state = update_progress(state, lesson, results)
        save_state(state_path, state)

        agent_log("Progress Reporter Agent", progress_report(before, state))
        agent_log("Evaluator Agent", f"Updated weak topics: {', '.join(state['weak_topics'])}.")
        agent_log("Orchestrator", f"Saved progress. {recommendation(state)}")

        cycle += 1
        if once:
            break
        if max_cycles and cycle > max_cycles:
            break
        if time.monotonic() >= deadline:
            break
        agent_log("Orchestrator", f"Sleeping {interval_seconds:g} seconds before the next autonomous cycle.")
        time.sleep(max(0.0, interval_seconds))

    agent_log("Orchestrator", "FluentAI tutor stopped after completing the demo window.")


def run_conversation_loop(
    state_path: Path,
    language: str,
    turns: int,
    mode: str,
    video: str,
    video_object: str | None,
) -> None:
    video_on = video == "on"
    state = load_state(state_path, language)
    provider = OpenAIProvider()

    agent_log("Conversation Orchestrator", "Starting FaceTime-style Conversation Mode.")
    agent_log("Conversation Orchestrator", f"Memory file: {state_path}")
    agent_log("Conversation Orchestrator", f"Mode: {mode}; video: {video}")
    agent_log("OpenAI Model Agent", provider.status())

    weak_topics = ", ".join(state.get("weak_topics", []))
    agent_log(
        "Memory Agent",
        f"Loaded level {current_level(state)} with weak topics: {weak_topics}.",
    )

    if video_on:
        agent_log("Vision Context Agent", f"Video is on. Visible context: {video_object or 'camera frame unavailable'}.")
    else:
        agent_log("Vision Context Agent", "Video is off. Running audio/text-only conversation.")

    transcript, state, topic = run_conversation(
        state=state,
        turns=turns,
        mode=mode,
        video_on=video_on,
        video_object=video_object,
        tutor_reply_fn=provider.conversation_tutor_reply if provider.available else None,
    )

    agent_log(
        "Speaking Tutor Agent",
        f"AI initiated topic '{topic['topic']}' at {topic['complexity']} complexity.",
    )
    print_conversation(transcript)

    average_score = sum(turn.score for turn in transcript) / max(1, len(transcript))
    agent_log("Fluency Evaluator Agent", f"Average speaking score: {average_score:.2f}.")
    agent_log(
        "Memory Agent",
        f"Next speaking goal: {state['conversation_memory']['next_speaking_goal']}",
    )
    save_state(state_path, state)
    agent_log("Conversation Orchestrator", "Saved conversation progress.")


def print_conversation(transcript: list) -> None:
    print("\nConversation")
    for turn in transcript:
        print(f"- Turn {turn.turn_number} [{turn.complexity}]")
        print(f"  Tutor: {turn.tutor_text}")
        print(f"  Learner: {turn.learner_text}")
        print(f"  Feedback: {turn.feedback}")
        if turn.correction:
            print(f"  Model phrase: {turn.correction}")


def print_lesson(lesson: dict) -> None:
    print("\nLesson")
    print(f"- Language: {lesson['language']}")
    print(f"- Level: {lesson['level']}")
    print(f"- Topic: {lesson['topic']}")
    print(f"- Focus: {lesson['focus_skill']}")
    print("- Vocabulary:")
    for word, meaning in lesson["vocabulary"]:
        print(f"  - {word}: {meaning}")
    print(f"- Grammar: {lesson['grammar_explanation']}")
    print("- Examples:")
    for source, meaning in lesson["examples"]:
        print(f"  - {source} = {meaning}")
    print(f"- Micro task: {lesson['micro_task']}")


def print_feedback(results: list) -> None:
    print("\nFeedback")
    for index, result in enumerate(results, start=1):
        status = "correct" if result.correct else "review"
        print(f"- Q{index} {status} [{result.question_type} / {result.skill}]")
        print(f"  prompt: {result.prompt}")
        print(f"  expected: {result.expected}")
        print(f"  answered: {result.actual}")
        print(f"  feedback: {result.feedback}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the FluentAI always-on tutor loop.")
    parser.add_argument("--product-mode", choices=["lesson", "conversation"], default="lesson")
    parser.add_argument("--state-path", type=Path, default=DEFAULT_PROGRESS_PATH)
    parser.add_argument("--language", default="Spanish")
    parser.add_argument("--duration-minutes", type=float, default=5)
    parser.add_argument("--interval-seconds", type=float, default=60)
    parser.add_argument("--max-cycles", type=int, default=20)
    parser.add_argument("--mode", choices=["auto", "interactive"], default="auto")
    parser.add_argument("--once", action="store_true", help="Run one on-demand lesson cycle.")
    parser.add_argument("--turns", type=int, default=4, help="Conversation turns for Conversation Mode.")
    parser.add_argument("--video", choices=["on", "off"], default="off")
    parser.add_argument("--video-object", default=None, help="Visible object label or image filename for the video demo.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.product_mode == "conversation":
        run_conversation_loop(
            state_path=args.state_path,
            language=args.language,
            turns=args.turns,
            mode=args.mode,
            video=args.video,
            video_object=args.video_object,
        )
        return

    run_loop(
        state_path=args.state_path,
        language=args.language,
        duration_minutes=args.duration_minutes,
        interval_seconds=args.interval_seconds,
        mode=args.mode,
        max_cycles=args.max_cycles,
        once=args.once,
    )


if __name__ == "__main__":
    main()
