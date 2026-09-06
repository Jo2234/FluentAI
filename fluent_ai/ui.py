from __future__ import annotations

from pathlib import Path

from fluent_ai.agent import evaluate_answers, generate_lesson, generate_quiz, progress_report, snapshot_progress, update_progress
from fluent_ai.app import DEFAULT_PROGRESS_PATH
from fluent_ai.conversation import run_conversation, update_conversation_progress
from fluent_ai.openai_provider import OpenAIProvider
from fluent_ai.state import active_language, state_transaction, conversation_memory, load_state


def build_lesson_text(lesson: dict, quiz: list[dict]) -> str:
    vocabulary = "\n".join(f"- {word}: {meaning}" for word, meaning in lesson["vocabulary"])
    examples = "\n".join(f"- {source} = {meaning}" for source, meaning in lesson["examples"])
    questions = "\n".join(f"{index}. [{question['type']}] {question['prompt']}" for index, question in enumerate(quiz, start=1))
    return (
        "# FluentAI Daily Lesson\n\n"
        f"Level: {lesson['level']}\n\n"
        f"Topic: {lesson['topic']}\n\n"
        f"Focus: {lesson['focus_skill']}\n\n"
        f"## Vocabulary\n{vocabulary}\n\n"
        f"## Grammar\n{lesson['grammar_explanation']}\n\n"
        f"## Examples\n{examples}\n\n"
        f"## Quiz\n{questions}\n\n"
        "Type one answer per line below."
    )


def launch_ui(state_path: Path = DEFAULT_PROGRESS_PATH, language: str = "Spanish") -> None:
    try:
        import gradio as gr
    except ImportError:
        print("Gradio is not installed. Falling back to the console demo:")
        print("python -m fluent_ai.app --once --mode interactive")
        return

    state = load_state(state_path, language)
    provider = OpenAIProvider()
    lesson = generate_lesson(state)
    if provider.available:
        lesson = provider.enhance_lesson(state, lesson)
    quiz = generate_quiz(state, lesson)
    lesson_generation = state["memory_generation"]
    lesson_language = active_language(state)

    def submit_answers(answer_text: str) -> tuple[str, str]:
        latest_state = load_state(state_path, language)
        answers = [line.strip() for line in answer_text.splitlines() if line.strip()]
        while len(answers) < len(quiz):
            answers.append("")
        results = evaluate_answers(quiz, answers[: len(quiz)])
        with state_transaction(state_path, lesson_language, generation=lesson_generation) as latest_state:
            before = snapshot_progress(latest_state)
            update_progress(latest_state, lesson, results)

        feedback_lines = [progress_report(before, latest_state), ""]
        for index, result in enumerate(results, start=1):
            status = "Correct" if result.correct else "Review"
            feedback_lines.append(f"{index}. {status}: {result.feedback}")
        return "\n".join(feedback_lines), build_lesson_text(lesson, quiz)

    def start_conversation(turns: int, video_enabled: bool, visible_object: str) -> str:
        latest_state = load_state(state_path, language)
        conversation_language = active_language(latest_state)
        transcript, updated_state, topic = run_conversation(
            state=latest_state,
            turns=int(turns),
            mode="auto",
            video_on=bool(video_enabled),
            video_object=visible_object.strip() or None,
            tutor_reply_fn=provider.conversation_tutor_reply if provider.available else None,
            conversation_grade_fn=getattr(provider, "evaluate_conversation_reply", None) if provider.available else None,
        )
        with state_transaction(state_path, conversation_language, generation=latest_state["memory_generation"]) as updated_state:
            update_conversation_progress(updated_state, topic, transcript, bool(video_enabled), visible_object.strip() or None)

        lines = [
            f"Topic: {topic['topic']}",
            f"Complexity: {topic['complexity']}",
            f"Next speaking goal: {conversation_memory(updated_state)['next_speaking_goal']}",
            "",
        ]
        for turn in transcript:
            lines.append(f"Turn {turn.turn_number}")
            lines.append(f"Tutor: {turn.tutor_text}")
            lines.append(f"Learner: {turn.learner_text}")
            lines.append(f"Feedback: {turn.feedback}")
            if turn.correction:
                lines.append(f"Model phrase: {turn.correction}")
            lines.append("")
        return "\n".join(lines)

    with gr.Blocks(title="FluentAI") as demo:
        with gr.Tab("Lesson Mode"):
            gr.Markdown(build_lesson_text(lesson, quiz))
            answers = gr.Textbox(label="Answers", lines=8, placeholder="One answer per line")
            submit = gr.Button("Submit answers")
            feedback = gr.Textbox(label="Feedback", lines=10)
            lesson_state = gr.Markdown("")
            submit.click(submit_answers, inputs=answers, outputs=[feedback, lesson_state])
        with gr.Tab("Conversation Mode"):
            gr.Markdown("FaceTime-style tutor simulation. The AI starts and adapts the topic from memory.")
            turns = gr.Slider(2, 8, value=4, step=1, label="Conversation turns")
            video_enabled = gr.Checkbox(label="Video on")
            visible_object = gr.Textbox(label="Visible object", placeholder="apple, book, cup")
            start = gr.Button("Start conversation")
            transcript = gr.Textbox(label="Transcript", lines=18)
            start.click(start_conversation, inputs=[turns, video_enabled, visible_object], outputs=transcript)

    demo.launch()


def main() -> None:
    launch_ui()


if __name__ == "__main__":
    main()
