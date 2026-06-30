import os
import unittest
from pathlib import Path
from unittest.mock import patch

from fluent_ai.openai_provider import OpenAIProvider, _safe_error


class ProjectContractTests(unittest.TestCase):
    def test_required_demo_files_exist(self):
        root = Path(__file__).resolve().parents[1]
        for relative in [".env.example", "macos/desktop_app.py", "scripts/smoke_demo.py", ".github/workflows/smoke.yml"]:
            self.assertTrue((root / relative).exists(), relative)

    def test_openai_status_is_non_secret_and_model_aware(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-secret", "OPENAI_MODEL": "demo-model"}, clear=False):
            provider = OpenAIProvider()
            with patch.object(provider, "_load_client", return_value=object()):
                status = provider.status()

        self.assertIn("OpenAI enabled: model demo-model", status)
        self.assertNotIn("sk-test-secret", status)

    def test_safe_error_truncates_verbose_messages(self):
        message = _safe_error(RuntimeError("x" * 200))
        self.assertLessEqual(len(message), 140)
        self.assertIn("RuntimeError", message)


if __name__ == "__main__":
    unittest.main()
