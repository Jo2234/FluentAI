"""Regression tests for independent processes and session/reset races; no network."""
import json
import multiprocessing
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fluent_ai import desktop_bridge as bridge
from fluent_ai.agent import generate_lesson, generate_quiz
from fluent_ai.state import (
    SessionExpired, StateConflict, atomic_write, conversation_memory, default_state,
    load_state, profile_state, save_state, state_transaction,
)


class FakeProvider:
    available = True
    model = 'offline'
    last_error = None

    def status(self):
        return 'Offline fake'

    def evaluate_quiz_answers(self, state, lesson, items):
        return None


def increment_worker(path, language, start):
    start.wait(10)
    for _ in range(8):
        with state_transaction(Path(path), language) as state:
            profile_state(state)['xp'] += 1


def submit_worker(payload, counter_path, start, output):
    class CountingProvider(FakeProvider):
        def evaluate_quiz_answers(self, state, lesson, items):
            with open(counter_path, 'a', encoding='utf-8') as counter:
                counter.write('grade\n')
            return None
    start.wait(10)
    with patch.object(bridge, 'OpenAIProvider', CountingProvider):
        output.put(bridge.lesson_submit(payload))


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'progress.json'
        self.state = load_state(self.path)
        self.payload = {'state_path': str(self.path), 'language': 'Spanish',
                        'memory_generation': self.state['memory_generation']}

    def lesson_payload(self, session_id='lesson-1'):
        lesson = generate_lesson(self.state)
        lesson.update(session_id=session_id, memory_generation=self.state['memory_generation'])
        quiz = generate_quiz(self.state, lesson)
        return {**self.payload, 'lesson': lesson, 'quiz': quiz, 'answers': [q['answer'] for q in quiz]}

    def test_independent_processes_preserve_same_and_other_language_updates(self):
        ctx = multiprocessing.get_context('spawn')
        start = ctx.Event()
        workers = [ctx.Process(target=increment_worker, args=(str(self.path), language, start))
                   for language in ('Spanish', 'French', 'Spanish', 'French')]
        for worker in workers:
            worker.start()
            self.addCleanup(lambda p=worker: p.is_alive() and p.terminate())
        start.set()
        # Raw readers must never see a partial document during concurrent commits.
        deadline = time.monotonic() + 20
        while any(worker.is_alive() for worker in workers):
            self.assertLess(time.monotonic(), deadline, "concurrent writers did not finish")
            self.assertIsInstance(json.loads(self.path.read_text()), dict)
            for worker in workers:
                worker.join(0.02)
        for worker in workers:
            self.assertEqual(worker.exitcode, 0)
        final = load_state(self.path)
        self.assertEqual(profile_state(final, 'Spanish')['xp'], 16)
        self.assertEqual(profile_state(final, 'French')['xp'], 16)

    def test_stale_snapshot_cannot_overwrite_newer_progress(self):
        stale = load_state(self.path)
        with state_transaction(self.path, 'French') as latest:
            profile_state(latest)['xp'] = 99
        profile_state(stale)['xp'] = 15
        with self.assertRaises(StateConflict):
            save_state(self.path, stale)
        self.assertEqual(profile_state(load_state(self.path), 'French')['xp'], 99)

    def test_failed_atomic_replace_preserves_old_document_and_cleans_temp(self):
        before = self.path.read_bytes()
        with patch('fluent_ai.state.os.replace', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                atomic_write(self.path, b'new data')
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.glob('.progress.json.*.tmp')), [])

    def test_simultaneous_process_retries_grade_and_award_once(self):
        ctx = multiprocessing.get_context('spawn')
        start, output = ctx.Event(), ctx.Queue()
        counter = self.path.parent / 'provider-calls.txt'
        payload = self.lesson_payload()
        workers = [ctx.Process(target=submit_worker, args=(payload, str(counter), start, output)) for _ in range(2)]
        for worker in workers:
            worker.start()
            self.addCleanup(lambda p=worker: p.is_alive() and p.terminate())
        start.set()
        results = [output.get(timeout=20) for _ in workers]
        for worker in workers:
            worker.join(20)
            self.assertEqual(worker.exitcode, 0)
        self.assertEqual(results[0], results[1])
        self.assertEqual(counter.read_text().splitlines(), ['grade'])
        final = load_state(self.path)
        self.assertEqual(profile_state(final)['xp'], results[0]['profile']['xp'])
        self.assertEqual(sum(e['type'] == 'lesson_completed' for e in final['events']), 1)

    def test_new_lesson_attempt_can_practice_same_material(self):
        with patch.object(bridge, 'OpenAIProvider', FakeProvider):
            first = bridge.lesson_submit(self.lesson_payload('attempt-1'))
            second = bridge.lesson_submit(self.lesson_payload('attempt-2'))
        self.assertEqual(second['profile']['xp'], first['profile']['xp'] * 2)

    def test_provider_failure_leaves_attempt_retryable(self):
        class Failure(FakeProvider):
            def evaluate_quiz_answers(self, *args):
                raise TimeoutError('offline timeout')
        payload = self.lesson_payload()
        with patch.object(bridge, 'OpenAIProvider', Failure), self.assertRaises(TimeoutError):
            bridge.lesson_submit(payload)
        self.assertEqual(profile_state(load_state(self.path))['xp'], 0)
        with patch.object(bridge, 'OpenAIProvider', FakeProvider):
            self.assertTrue(bridge.lesson_submit(payload)['ok'])

    def test_model_work_does_not_lock_other_language_and_commits_to_latest_state(self):
        entered, release = threading.Event(), threading.Event()
        class Blocking(FakeProvider):
            def evaluate_quiz_answers(self, *args):
                entered.set()
                if not release.wait(10):
                    raise TimeoutError('test did not release provider')
                return None
        with patch.object(bridge, 'OpenAIProvider', Blocking), ThreadPoolExecutor() as pool:
            future = pool.submit(bridge.lesson_submit, self.lesson_payload())
            self.assertTrue(entered.wait(5))
            try:
                with state_transaction(self.path, 'French') as latest:
                    profile_state(latest)['xp'] = 99
            finally:
                release.set()
            self.assertTrue(future.result(timeout=10)['ok'])
        final = load_state(self.path)
        self.assertEqual(profile_state(final, 'French')['xp'], 99)
        self.assertGreater(profile_state(final, 'Spanish')['xp'], 0)

    def test_delete_erases_owned_data_and_rejects_late_session_writes(self):
        lesson = self.lesson_payload()
        call = {**self.payload, 'session_id': 'call-1', 'turns': [{'learner_text': 'private phrase'}]}
        bridge.lesson_checkpoint(lesson)
        bridge.call_checkpoint(call)
        audio = self.path.parent / 'cache' / 'tts' / 'speech.mp3'
        audio.parent.mkdir(parents=True)
        audio.write_bytes(b'private audio')
        backup = self.path.with_name('progress.corrupt.audit.json')
        backup.write_text('private recovered data')
        orphan = self.path.parent / '.progress.json.crashed.tmp'
        orphan.write_text('private interrupted write')
        export = self.path.parent / 'user-export.json'
        export.write_text('explicit export')
        result = bridge.memory_delete_all({**self.payload, 'confirm': 'DELETE ALL MEMORY'})
        self.assertTrue(result['ok'])
        self.assertFalse(audio.exists())
        self.assertFalse(backup.exists())
        self.assertFalse(orphan.exists())
        self.assertFalse((self.path.parent / 'sessions').exists())
        self.assertTrue(export.exists())
        for operation, payload in ((bridge.call_checkpoint, call), (bridge.lesson_checkpoint, lesson),
                                   (bridge.conversation_end, call), (bridge.lesson_submit, lesson)):
            self.assertTrue(operation(payload)['session_expired'])
        self.assertTrue(bridge.call_checkpoint({'state_path': str(self.path), 'turns': call['turns']})['session_expired'])
        self.assertEqual(conversation_memory(load_state(self.path))['post_call_summaries'], [])
        with self.assertRaises(SessionExpired):
            save_state(self.path, self.state)
        fresh = {**call, 'memory_generation': result['profile']['memory_generation'], 'session_id': 'new-call'}
        self.assertTrue(bridge.call_checkpoint(fresh)['ok'])

    def test_delete_during_grading_does_not_resurrect_progress(self):
        entered, release = threading.Event(), threading.Event()
        class Blocking(FakeProvider):
            def evaluate_quiz_answers(self, *args):
                entered.set()
                if not release.wait(10):
                    raise TimeoutError('test did not release provider')
                return None
        with patch.object(bridge, 'OpenAIProvider', Blocking), ThreadPoolExecutor() as pool:
            future = pool.submit(bridge.lesson_submit, self.lesson_payload())
            self.assertTrue(entered.wait(5))
            try:
                self.assertTrue(bridge.memory_delete_all({**self.payload, 'confirm': 'DELETE ALL MEMORY'})['ok'])
            finally:
                release.set()
            self.assertTrue(future.result(timeout=10)['session_expired'])
        final = load_state(self.path)
        self.assertEqual(profile_state(final)['xp'], 0)
        self.assertEqual(final['completed_sessions'], {})

    def test_delete_during_speech_generation_does_not_recreate_audio(self):
        entered, release = threading.Event(), threading.Event()
        class Blocking(FakeProvider):
            def synthesize_speech(self, *args):
                entered.set()
                if not release.wait(10):
                    raise TimeoutError('test did not release provider')
                return b'private speech'
        with patch.object(bridge, 'OpenAIProvider', Blocking), ThreadPoolExecutor() as pool:
            future = pool.submit(bridge.phrase_audio, {**self.payload, 'phrase': 'Hola'})
            self.assertTrue(entered.wait(5))
            try:
                bridge.memory_delete_all({**self.payload, 'confirm': 'DELETE ALL MEMORY'})
            finally:
                release.set()
            with self.assertRaises(SessionExpired):
                future.result(timeout=10)
        self.assertFalse((self.path.parent / 'cache' / 'tts').exists())

    def test_older_lesson_completion_does_not_discard_new_checkpoint(self):
        entered, release = threading.Event(), threading.Event()
        class Blocking(FakeProvider):
            def enhance_lesson(self, state, lesson):
                return {**lesson, 'source': 'openai'}

            def evaluate_quiz_answers(self, *args):
                entered.set()
                if not release.wait(10):
                    raise TimeoutError('test did not release provider')
                return None
        old_lesson = self.lesson_payload()
        bridge.lesson_checkpoint(old_lesson)
        with patch.object(bridge, 'OpenAIProvider', Blocking), ThreadPoolExecutor() as pool:
            future = pool.submit(bridge.lesson_submit, old_lesson)
            self.assertTrue(entered.wait(5))
            try:
                fresh = bridge.lesson_start(self.payload)
                self.assertTrue(fresh['ok'])
            finally:
                release.set()
            self.assertTrue(future.result(timeout=10)['ok'])
        checkpoint = bridge.session_checkpoints(self.payload)['checkpoints']['lesson']
        self.assertEqual(checkpoint['session_id'], fresh['lesson']['session_id'])

    def test_old_call_discard_does_not_remove_another_call_checkpoint(self):
        call = {**self.payload, 'session_id': 'new-call', 'turns': [{'learner_text': 'Bonjour'}]}
        bridge.call_checkpoint(call)
        bridge.call_checkpoint_discard({**self.payload, 'session_id': 'old-call'})
        checkpoint = bridge.session_checkpoints(self.payload)['checkpoints']['call']
        self.assertEqual(checkpoint['session_id'], 'new-call')

    def test_recovered_call_uses_captured_language_and_deduplicates_finalization(self):
        call = {**self.payload, 'language': 'French', 'session_id': 'call-french',
                'turns': [{'learner_text': 'Bonjour', 'score': 0.8}],
                'topic': {'topic': 'introductions', 'complexity': 'beginner'}}
        bridge.call_checkpoint(call)
        with patch.object(bridge, 'OpenAIProvider', FakeProvider):
            first = bridge.call_checkpoint_summarize(self.payload)
            repeated = bridge.conversation_end(call)
        self.assertTrue(first['ok'])
        self.assertEqual(repeated['profile']['language'], 'French')
        final = load_state(self.path)
        self.assertEqual(len(conversation_memory(final, 'French')['post_call_summaries']), 1)
        self.assertEqual(len(conversation_memory(final, 'Spanish')['post_call_summaries']), 0)
        self.assertEqual(profile_state(final, 'French')['xp'], repeated['profile']['xp'])
        # A delayed autosave must not recreate the finalized transcript.
        bridge.call_checkpoint(call)
        self.assertFalse((self.path.parent / 'sessions' / 'current_call.json').exists())


if __name__ == '__main__':
    unittest.main()
