from pathlib import Path
import unittest


RENDERER = Path(__file__).resolve().parents[1] / "desktop" / "electron" / "renderer.html"


class RendererUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = RENDERER.read_text(encoding="utf-8")

    def test_agent_decisions_expand_as_side_rail_not_floating_square(self):
        self.assertIn(".workspace.logs-open", self.html)
        self.assertIn("grid-template-columns: minmax(0, 1fr) minmax(320px, 390px)", self.html)
        self.assertIn("grid-column: 2", self.html)
        self.assertNotIn("position: fixed;\n      right: 22px;\n      bottom: 22px;", self.html)

    def test_lesson_questions_mark_as_answered_immediately(self):
        self.assertIn("function markQuestionAnswered", self.html)
        self.assertIn("question.classList.toggle(\"answered\", answered)", self.html)
        self.assertIn("answered ? \"Answered\" : \"Try it\"", self.html)

    def test_lesson_has_interactive_phrase_lab_and_sticky_left_rail(self):
        self.assertIn("phraseLabBlock(lesson)", self.html)
        self.assertIn("Phrase Lab", self.html)
        self.assertIn("position: sticky", self.html)

    def test_lesson_reason_and_error_category_feedback_render(self):
        self.assertIn("lesson.reason", self.html)
        self.assertIn("Why this lesson:", self.html)
        self.assertIn("lesson-reason", self.html)
        self.assertIn("function errorCategoryLabel", self.html)
        self.assertIn("error-chip", self.html)
        self.assertIn("error-chip.advisory", self.html)
        self.assertIn('result.correct ? " advisory" : ""', self.html)
        self.assertIn("Corrected form:", self.html)
        self.assertIn("conjugation slip", self.html)

    def test_voice_controls_do_not_overlap_video_context_card(self):
        self.assertIn("grid-area: controls", self.html)
        self.assertIn("grid-template-areas", self.html)
        self.assertIn(".video-context-card", self.html)


if __name__ == "__main__":
    unittest.main()
