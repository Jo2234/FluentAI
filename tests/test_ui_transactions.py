"""Exercise Gradio callbacks without importing or launching a browser/server."""
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fluent_ai import ui
from fluent_ai.conversation import ConversationTurn, update_conversation_progress
from fluent_ai.state import active_language, load_state, profile_state, state_transaction


class GradioTransactionsTests(unittest.TestCase):
    def launch_callbacks(self, path):
        callbacks = {}

        class Component:
            def __init__(self, *args, **kwargs):
                self.label = args[0] if args else kwargs.get('label', '')

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def click(self, function, **kwargs):
                callbacks[self.label] = function

            def launch(self):
                pass

        gradio = types.SimpleNamespace(**{name: Component for name in
            ('Blocks', 'Tab', 'Markdown', 'Textbox', 'Button', 'Slider', 'Checkbox')})
        with patch.dict('sys.modules', {'gradio': gradio}), patch.object(
            ui, 'OpenAIProvider', return_value=types.SimpleNamespace(available=False)
        ):
            ui.launch_ui(path, language='Spanish')
        return callbacks

    def test_lesson_credits_captured_lesson_language_after_another_writer_switches(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'progress.json'
            load_state(path, 'French')
            callbacks = self.launch_callbacks(path)
            with state_transaction(path, 'Spanish') as latest:
                profile_state(latest)['xp'] = 99
            callbacks['Submit answers']('bonjour')
            final = load_state(path)
            self.assertGreater(profile_state(final, 'French')['xp'], 0)
            self.assertEqual(profile_state(final, 'Spanish')['xp'], 99)
            self.assertEqual(final['events'][-1]['language'], 'French')

    def test_conversation_credits_language_used_to_generate_transcript(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'progress.json'
            load_state(path, 'French')
            callbacks = self.launch_callbacks(path)

            def conversation(state, **kwargs):
                self.assertEqual(active_language(state), 'French')
                topic = {'topic': 'greetings', 'complexity': 'simple', 'keywords': []}
                turns = [ConversationTurn(1, 'Bonjour', 'Bonjour', 'greetings', 'simple',
                                          False, None, .8, 'Good', None, None)]
                update_conversation_progress(state, topic, turns, False, None)
                with state_transaction(path, 'Spanish') as latest:
                    profile_state(latest)['xp'] = 99
                return turns, state, topic

            with patch.object(ui, 'run_conversation', side_effect=conversation):
                callbacks['Start conversation'](1, False, '')
            final = load_state(path)
            self.assertEqual(profile_state(final, 'Spanish')['xp'], 99)
            self.assertEqual(final['events'][-1]['language'], 'French')
            self.assertEqual(sum(event['type'] == 'conversation_started' for event in final['events']), 1)
