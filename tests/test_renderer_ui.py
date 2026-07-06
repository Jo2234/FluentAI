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

    def test_lesson_listen_buttons_and_hint_cards_render(self):
        for marker in [
            "phraseAudio: (payload) => bridge(\"phrase_audio\", payload)",
            "phraseAudioElement",
            "lessonHintCards(lesson)",
            "Pronunciation",
            "Culture",
            "Listening notes",
            "listenButton(word)",
            "listenButton(source)",
            "function playPhraseAudio",
            "data:${result.mime_type || \"audio/mpeg\"};base64,${result.audio_base64}",
            "Could not generate phrase audio.",
            ".listen-btn",
            ".lesson-hint-card",
        ]:
            self.assertIn(marker, self.html)

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

    def test_lesson_quiz_uses_light_text_on_aurora_cards(self):
        for marker in [
            ".quiz-column h3,\n    .question .question-prompt",
            "color: #eef2ff;",
            ".choice:hover",
            "background: rgba(22, 25, 38, 0.88);",
            ".free-answer::placeholder",
            "color: #aeb6c8;",
            ".lesson-column .listen-btn",
            "background: rgba(139,211,255,0.12);",
        ]:
            self.assertIn(marker, self.html)

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
        self.assertIn("pronunciation_note", self.html)
        self.assertIn("Listen to a model phrase, then repeat it out loud.", self.html)
        self.assertIn("confidenceArrow", self.html)
        self.assertIn("realtimeTurns", self.html)
        self.assertIn("endConversation: (payload) => bridge(\"conversation_end\", payload)", self.html)

    def test_reliability_matrix_renderer_hooks_exist(self):
        for marker in [
            "AbortController",
            "timeoutMs = 20000",
            "retries: options.idempotent ? 1 : 0",
            "function scheduleRealtimeRefresh",
            "state.realtimeSecretExpiresAt - Date.now() - 60000",
            "Voice session is refreshing.",
            "Voice session could not refresh. Continuing in text mode with your transcript intact.",
            "Resume interrupted lesson",
            "Summarize your interrupted call",
            "discardLessonCheckpoint",
            "discardCallCheckpoint",
            "Your reply didn't go through — try again.",
            "Your answers didn't go through — try again.",
            "Camera is blocked. Continuing voice-only.",
            "queueLessonCheckpoint",
            "queueCallCheckpoint",
        ]:
            self.assertIn(marker, self.html)

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

    def test_home_workspace_and_memory_inspector_regions_exist(self):
        for marker in [
            'button class="header-tab active" id="headerHomeBtn"',
            'button class="ghost active" id="homeModeBtn"',
            'div class="pane home-pane" id="homePane"',
            'section class="home-panel today-panel" id="todayPanel"',
            'section class="home-panel profile-panel" id="homeProfilePanel"',
            'section class="home-panel" id="reviewPreviewPanel"',
            'section class="home-panel" id="recentProgressPanel"',
            'section class="home-panel" id="speakingTrendPanel"',
            'details class="home-panel memory-inspector" id="memoryInspectorPanel"',
            "Profile, skills, mistakes, reviews, conversation, privacy",
            "Export memory",
            "Show JSON",
            "Reset language",
            "Delete all memory",
        ]:
            self.assertIn(marker, self.html)

    def test_home_workspace_uses_dark_cards_and_responsive_stack(self):
        for marker in [
            ".home-panel {",
            "background: rgba(10,12,18,0.82);",
            "background-color: rgba(10,12,18,0.88);",
            "color: #f7f8f8;",
            ".home-panel button.secondary,",
            ".home-panel button.overlay-secondary",
            'meet.className = "secondary overlay-secondary";',
            "@media (max-width: 900px)",
            ".workspace.logs-open,\n      .workspace.logs-closed",
            ".home-pane {\n        grid-template-columns: 1fr;",
            ".memory-sections {\n        grid-template-columns: 1fr;",
        ]:
            self.assertIn(marker, self.html)

    def test_home_renderer_functions_and_no_initial_lesson_autostart(self):
        for function_name in [
            "loadHomeSummary",
            "renderHome",
            "runTodayAction",
            "showHome",
            "openMemoryInspector",
            "renderMemoryInspector",
            "exportMemory",
            "resetLanguageMemory",
            "deleteAllMemory",
        ]:
            self.assertIn(f"function {function_name}", self.html)
        self.assertIn('mode: "home"', self.html)
        self.assertIn('setMode("home");\n    initKeyGate().then((blocked) => {', self.html)
        self.assertIn("if (!blocked) initOnboarding();", self.html)
        self.assertIn("function initKeyGate", self.html)
        self.assertIn("Validate & Save", self.html)
        self.assertIn('await loadHomeSummary();\n      setMode("home");', self.html)
        self.assertNotIn("refreshStatus(true).then(ensureLessonStarted)", self.html)
        self.assertIn('const expected = `RESET ${currentLanguage()}`;', self.html)
        self.assertIn('Type DELETE ALL MEMORY to delete all memory.', self.html)

    def test_web_fallback_includes_home_memory_bridge_methods(self):
        self.assertIn("homeSummary: (payload) => bridge(\"home_summary\", payload, { idempotent: true })", self.html)
        self.assertIn("memoryInspect: (payload) => bridge(\"memory_inspect\", payload, { idempotent: true })", self.html)
        self.assertIn("const result = await bridge(\"memory_export\", payload)", self.html)
        self.assertIn("new Blob([JSON.stringify(result.data, null, 2)]", self.html)
        self.assertIn("memoryResetLanguage: (payload) => bridge(\"memory_reset_language\", payload)", self.html)
        self.assertIn("memoryDeleteAll: (payload) => bridge(\"memory_delete_all\", payload)", self.html)

    def test_preload_and_main_expose_home_memory_ipc(self):
        preload = (Path(__file__).resolve().parents[1] / "desktop" / "electron" / "preload.js").read_text(encoding="utf-8")
        main = (Path(__file__).resolve().parents[1] / "desktop" / "electron" / "main.js").read_text(encoding="utf-8")
        for marker in [
            "keyStatus: () => ipcRenderer.invoke(\"key:status\")",
            "validateKey: (payload) => ipcRenderer.invoke(\"key:validate\", payload)",
            "saveKey: (payload) => ipcRenderer.invoke(\"key:save\", payload)",
            "deleteKey: () => ipcRenderer.invoke(\"key:delete\")",
            "homeSummary: (payload) => ipcRenderer.invoke(\"home:summary\", payload)",
            "memoryInspect: (payload) => ipcRenderer.invoke(\"memory:inspect\", payload)",
            "memoryExport: (payload) => ipcRenderer.invoke(\"memory:export\", payload)",
            "memoryResetLanguage: (payload) => ipcRenderer.invoke(\"memory:reset_language\", payload)",
            "memoryDeleteAll: (payload) => ipcRenderer.invoke(\"memory:delete_all\", payload)",
            "sessionCheckpoints: (payload) => ipcRenderer.invoke(\"session:checkpoints\", payload)",
            "lessonCheckpoint: (payload) => ipcRenderer.invoke(\"lesson:checkpoint\", payload)",
            "discardLessonCheckpoint: (payload) => ipcRenderer.invoke(\"lesson:checkpoint_discard\", payload)",
            "callCheckpoint: (payload) => ipcRenderer.invoke(\"call:checkpoint\", payload)",
            "discardCallCheckpoint: (payload) => ipcRenderer.invoke(\"call:checkpoint_discard\", payload)",
            "summarizeCallCheckpoint: (payload) => ipcRenderer.invoke(\"call:checkpoint_summarize\", payload)",
            "phraseAudio: (payload) => ipcRenderer.invoke(\"phrase:audio\", payload)",
        ]:
            self.assertIn(marker, preload)
        for marker in [
            'ipcMain.handle("key:status"',
            'ipcMain.handle("key:validate"',
            'ipcMain.handle("key:save"',
            'ipcMain.handle("key:delete"',
            'ipcMain.handle("home:summary"',
            'runBridge("home_summary"',
            'ipcMain.handle("memory:inspect"',
            'runBridge("memory_inspect"',
            'ipcMain.handle("memory:export"',
            "dialog.showSaveDialog",
            "fs.writeFileSync",
            'runBridge("memory_reset_language"',
            'runBridge("memory_delete_all"',
            'ipcMain.handle("session:checkpoints"',
            'runBridge("session_checkpoints"',
            'ipcMain.handle("lesson:checkpoint"',
            'runBridge("lesson_checkpoint"',
            'ipcMain.handle("call:checkpoint"',
            'runBridge("call_checkpoint"',
            'ipcMain.handle("phrase:audio"',
            'runBridge("phrase_audio"',
        ]:
            self.assertIn(marker, main)


if __name__ == "__main__":
    unittest.main()
