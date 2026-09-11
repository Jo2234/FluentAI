#!/usr/bin/env python3
"""Local recording harness. Real renderer/bridge; mocked provider; disposable state.

Not an application fallback. Never reads repository learner state or API keys.
"""
from __future__ import annotations

import argparse
import copy
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fluent_ai import desktop_bridge, web
from fluent_ai.state import default_state, profile_state, save_state, utc_now


class DemoProvider:
    available = True
    model = "mocked-portfolio-fixture"
    last_error = None

    def status(self):
        return "Mocked model responses — portfolio workflow recording."

    def enhance_lesson(self, state, lesson):
        result = copy.deepcopy(lesson)
        # The production bridge requires this provider-success marker. The
        # recording banner and logs explicitly identify the substituted service.
        result["source"] = "openai"
        return result

    def conversation_tutor_reply(self, topic, state, transcript, phase, fallback):
        return fallback


class DemoHandler(web.FluentAIHandler):
    def _renderer_html(self):
        banner = '''<div id="recordingDisclosure" style="position:fixed;top:0;left:0;
        width:100%;z-index:99999;background:#fef3c7;color:#422006;padding:12px 24px;
        font:600 15px system-ui;box-sizing:border-box;">
        WORKFLOW DEMO · Mocked model responses · Temporary learner profile · No API calls
        <span id="recordingChapter" style="float:right">Home → Lesson → Review → Conversation</span>
        </div><style>body {padding-top:48px !important;}</style>'''
        return super()._renderer_html().replace("<body>", "<body>" + banner)

    def _run_bridge_command(self, command, body):
        # Do not imply a live model call in the visible agent log.
        result = super()._run_bridge_command(command, body)
        result["logs"] = [
            line.replace("[OpenAI Model Agent]", "[Mock Provider]")
                .replace("with the OpenAI Responses API", "from the demo fixture")
            for line in result.get("logs", [])
        ]
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=7861)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="fluentai-recording-") as temp:
        state = default_state("Spanish")
        state["learner"].update(display_name="Demo Learner", onboarded_at=utc_now())
        profile_state(state)["placement_completed_at"] = utc_now()
        path = Path(temp) / "progress.json"
        save_state(path, state)
        DemoHandler.state_path = path
        DemoHandler.language = "Spanish"
        with patch.object(web, "OpenAIProvider", DemoProvider), patch.object(desktop_bridge, "OpenAIProvider", DemoProvider):
            with web.ThreadingHTTPServer(("127.0.0.1", args.port), DemoHandler) as server:
                print(f"Mocked portfolio recording: http://127.0.0.1:{args.port}", flush=True)
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    pass


if __name__ == "__main__":
    main()
