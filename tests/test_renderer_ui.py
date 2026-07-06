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

    def test_post_call_summary_card_and_voice_end_wiring_exist(self):
        self.assertIn("postCallSummary", self.html)
        self.assertIn("function postCallSummaryCard", self.html)
        self.assertIn("Post-call summary", self.html)
        self.assertIn("correction_to_remember", self.html)
        self.assertIn("phrase_to_review", self.html)
        self.assertIn("confidenceArrow", self.html)
        self.assertIn("realtimeTurns", self.html)
        self.assertIn("endConversation: (payload) => bridge(\"conversation_end\", payload)", self.html)

    def test_onboarding_overlay_markup_and_copy_exist(self):
        self.assertIn('section class="onboarding-overlay hidden" id="onboardingOverlay"', self.html)
        self.assertIn('div class="onboarding-stage" id="onboardingStage"', self.html)
        self.assertIn('div class="onboarding-progress" id="onboardingProgress"', self.html)
        self.assertIn('form class="onboarding-form" id="onboardingForm"', self.html)
        self.assertIn('div class="placement-stage hidden" id="placementStage"', self.html)
        self.assertIn('div class="placement-items" id="placementItems"', self.html)
        self.assertIn('button id="onboardingNextBtn"', self.html)
        self.assertIn('button class="ghost overlay-secondary" id="placementSkipBtn"', self.html)
        self.assertIn('button id="placementSubmitBtn"', self.html)
        self.assertIn('div class="placement-result-container hidden" id="placementResult"', self.html)
        self.assertIn("Start as beginner instead", self.html)
        self.assertIn("Quick placement check (2 min)", self.html)
        self.assertIn("Your local memory stays here.", self.html)
        self.assertIn("no raw audio or video", self.html)
        self.assertIn("Meet your tutor", self.html)
        self.assertIn(".onboarding-overlay button.overlay-secondary", self.html)
        self.assertIn("color: #f7f8f8", self.html)

    def test_onboarding_renderer_functions_and_startup_path_exist(self):
        for function_name in [
            "initOnboarding",
            "showOnboardingOverlay",
            "renderOnboardingStep",
            "collectOnboardingAnswers",
            "submitOnboarding",
            "startPlacement",
            "renderPlacement",
            "submitPlacement",
            "renderPlacementResult",
            "finishOnboarding",
            "scrollOnboardingToTop",
        ]:
            self.assertIn(f"function {function_name}", self.html)
        self.assertIn("initOnboarding();", self.html)
        self.assertNotIn("refreshStatus().then(ensureLessonStarted);", self.html)
        self.assertIn("if (result.requires_onboarding)", self.html)
        self.assertIn("showOnboardingOverlay(result)", self.html)
        self.assertNotIn('key === "motivation" && !payload.motivation', self.html)
        self.assertIn('answers.display_name = "Learner";', self.html)
        self.assertIn('els.placementItems.classList.add("hidden")', self.html)
        self.assertIn('els.placementResult.replaceChildren(card)', self.html)

    def test_web_fallback_includes_onboarding_bridge_methods(self):
        self.assertIn("onboardingStatus: (payload) => bridge(\"onboarding_status\", payload)", self.html)
        self.assertIn("submitOnboarding: (payload) => bridge(\"onboarding_submit\", payload)", self.html)
        self.assertIn("startPlacement: (payload) => bridge(\"placement_start\", payload)", self.html)
        self.assertIn("submitPlacement: (payload) => bridge(\"placement_submit\", payload)", self.html)


if __name__ == "__main__":
    unittest.main()
