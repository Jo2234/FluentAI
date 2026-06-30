#!/usr/bin/env python3
"""Tiny native fallback launcher for FluentAI on macOS.

The primary desktop app is Electron. This Tk fallback keeps the original one-shot
MVP contract alive on machines where a Python-only window is preferable during
local demos. It calls the same desktop bridge functions as the Electron shell and
never requires OpenAI credentials.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter.scrolledtext import ScrolledText

from fluent_ai.desktop_bridge import conversation_start, lesson_start, lesson_submit, status

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "data" / "progress.json"


class FluentAIDesktop(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("FluentAI")
        self.configure(bg="#fff5f5")
        self.attributes("-fullscreen", True)
        self.bind("<Escape>", lambda _event: self.attributes("-fullscreen", False))
        self.bind("<Command-q>", lambda _event: self.destroy())
        self.geometry("1180x760")

        self.language = tk.StringVar(value="Spanish")
        self.turns = tk.IntVar(value=4)
        self.video = tk.StringVar(value="off")
        self.visible_object = tk.StringVar(value="apple")

        self._build_ui()
        self.refresh_status()

    def payload(self) -> dict:
        return {"state_path": str(STATE_PATH), "language": self.language.get()}

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg="#ef4444", padx=18, pady=14)
        header.pack(fill="x")
        tk.Label(header, text="FluentAI", bg="#ef4444", fg="white", font=("Helvetica", 26, "bold")).pack(side="left")
        self.status_label = tk.Label(header, text="Loading...", bg="#ef4444", fg="white", font=("Helvetica", 13))
        self.status_label.pack(side="right")

        controls = tk.Frame(self, bg="#fff5f5", padx=18, pady=12)
        controls.pack(fill="x")
        tk.Label(controls, text="Language", bg="#fff5f5").grid(row=0, column=0, sticky="w")
        tk.OptionMenu(controls, self.language, "Spanish", "Hindi", "French").grid(row=1, column=0, sticky="ew", padx=(0, 10))
        tk.Label(controls, text="Turns", bg="#fff5f5").grid(row=0, column=1, sticky="w")
        tk.Spinbox(controls, from_=2, to=8, textvariable=self.turns, width=8).grid(row=1, column=1, padx=(0, 10))
        tk.Label(controls, text="Video", bg="#fff5f5").grid(row=0, column=2, sticky="w")
        tk.OptionMenu(controls, self.video, "off", "on").grid(row=1, column=2, sticky="ew", padx=(0, 10))
        tk.Label(controls, text="Visible object", bg="#fff5f5").grid(row=0, column=3, sticky="w")
        tk.Entry(controls, textvariable=self.visible_object, width=18).grid(row=1, column=3, padx=(0, 10))
        tk.Button(controls, text="Run Lesson", command=self.run_lesson, bg="#ef4444", fg="white").grid(row=1, column=4, padx=6)
        tk.Button(controls, text="Start Conversation", command=self.run_conversation, bg="#f59e0b").grid(row=1, column=5, padx=6)
        tk.Button(controls, text="Refresh", command=self.refresh_status).grid(row=1, column=6, padx=6)

        self.output = ScrolledText(self, wrap="word", font=("Menlo", 13), padx=14, pady=14)
        self.output.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        self.output.insert("end", "Press Run Lesson or Start Conversation. Escape leaves fullscreen. Command-Q quits.\n")

    def refresh_status(self) -> None:
        result = status(self.payload())
        profile = result.get("profile", {})
        self.status_label.config(
            text=f"{profile.get('language', 'Spanish')} · {profile.get('level', 'A1')} · XP {profile.get('xp', 0)} · OpenAI required"
        )

    def run_lesson(self) -> None:
        start = lesson_start(self.payload())
        answers = [question.get("answer", "") for question in start.get("quiz", [])]
        result = lesson_submit({**self.payload(), "lesson": start.get("lesson"), "quiz": start.get("quiz"), "answers": answers})
        self._write("\n".join(start.get("logs", []) + result.get("logs", [])))
        self._write(f"\nScore: {result.get('summary', {}).get('score')}\n{result.get('summary', {}).get('report')}\n")
        self.refresh_status()

    def run_conversation(self) -> None:
        result = conversation_start(
            {
                **self.payload(),
                "turns": self.turns.get(),
                "video": self.video.get(),
                "object": self.visible_object.get(),
            }
        )
        self._write("\n".join(result.get("logs", [])))
        self._write(f"\nTutor: {result.get('tutor_message')}\n")
        self.refresh_status()

    def _write(self, text: str) -> None:
        self.output.insert("end", text + "\n")
        self.output.see("end")


def main() -> None:
    FluentAIDesktop().mainloop()


if __name__ == "__main__":
    main()
