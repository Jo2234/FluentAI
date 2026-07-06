import importlib.util
import json
import shutil
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fluent_ai import curriculum
from fluent_ai.agent import evaluate_answers, generate_lesson, generate_quiz
from fluent_ai.state import default_state, language_state, profile_state, review_queue


CURRICULUM_DIR = Path(__file__).resolve().parents[1] / "fluent_ai" / "curriculum"
LANGUAGES = ("Spanish", "French", "Hindi")
REQUIRED_ANSWERS = {"mc", "fill_prompt", "fill", "open", "translation"}


SPANISH_BASELINE = {
    "introductions": {
        "focus_skill": "vocabulary",
        "vocabulary": [
            ("me llamo", "my name is"),
            ("soy de", "I am from"),
            ("encantado", "delighted"),
            ("mucho gusto", "nice to meet you"),
            ("a que te dedicas", "what do you do"),
        ],
        "grammar": "Use 'ser' for identity and origin: 'Soy Ana' and 'Soy de Singapur.'",
        "examples": [
            ("Me llamo Ana.", "My name is Ana."),
            ("Soy de Singapur.", "I am from Singapore."),
            ("Mucho gusto.", "Nice to meet you."),
        ],
        "answers": {
            "mc": "Nice to meet you.",
            "fill_prompt": "___ de Singapur.",
            "fill": "Soy",
            "open": "Me llamo Ana.",
            "translation": "Soy de Singapur.",
        },
    },
    "cafe orders": {
        "focus_skill": "vocabulary",
        "vocabulary": [
            ("quisiera", "I would like"),
            ("un cafe", "a coffee"),
            ("un te", "a tea"),
            ("la cuenta", "the bill"),
            ("por favor", "please"),
        ],
        "grammar": "Use 'Quisiera...' for a polite request. Put 'por favor' at the end to soften the order.",
        "examples": [
            ("Quisiera un cafe, por favor.", "I would like a coffee, please."),
            ("La cuenta, por favor.", "The bill, please."),
            ("Me gustaria un te.", "I would like a tea."),
        ],
        "answers": {
            "mc": "the bill",
            "fill_prompt": "___ un cafe, por favor.",
            "fill": "Quisiera",
            "open": "Quisiera un cafe, por favor.",
            "translation": "Un te, por favor.",
        },
    },
    "daily routines": {
        "focus_skill": "grammar",
        "vocabulary": [
            ("me levanto", "I get up"),
            ("trabajo", "I work"),
            ("estudio", "I study"),
            ("todos los dias", "every day"),
            ("por la manana", "in the morning"),
        ],
        "grammar": "For daily routines, use present-tense verbs with time phrases: 'Estudio por la noche.'",
        "examples": [
            ("Me levanto a las siete.", "I get up at seven."),
            ("Trabajo todos los dias.", "I work every day."),
            ("Estudio por la noche.", "I study at night."),
        ],
        "answers": {
            "mc": "in the morning",
            "fill_prompt": "___ por la noche.",
            "fill": "Estudio",
            "open": "Trabajo todos los dias.",
            "translation": "Me levanto a las siete.",
        },
    },
    "past tense": {
        "focus_skill": "conjugations",
        "vocabulary": [
            ("ayer", "yesterday"),
            ("fui", "I went"),
            ("comi", "I ate"),
            ("hable", "I spoke"),
            ("vi", "I saw"),
        ],
        "grammar": "For completed past actions, use the preterite: 'hable', 'comi', 'fui', and 'vi.'",
        "examples": [
            ("Ayer fui al mercado.", "Yesterday I went to the market."),
            ("Comi con mi familia.", "I ate with my family."),
            ("Hable con mi amigo.", "I spoke with my friend."),
        ],
        "answers": {
            "mc": "yesterday",
            "fill_prompt": "Ayer ___ al mercado.",
            "fill": "fui",
            "open": "Ayer fui al mercado.",
            "translation": "Hable con mi amigo.",
        },
    },
    "conjugations": {
        "focus_skill": "conjugations",
        "vocabulary": [
            ("yo hablo", "I speak"),
            ("tu hablas", "you speak"),
            ("ella habla", "she speaks"),
            ("nosotros hablamos", "we speak"),
            ("ellos hablan", "they speak"),
        ],
        "grammar": "Regular -ar verbs change endings by subject: hablo, hablas, habla, hablamos, hablan.",
        "examples": [
            ("Yo hablo espanol.", "I speak Spanish."),
            ("Ella habla ingles.", "She speaks English."),
            ("Nosotros hablamos cada dia.", "We speak every day."),
        ],
        "answers": {
            "mc": "I speak",
            "fill_prompt": "Yo ___ espanol.",
            "fill": "hablo",
            "open": "Yo hablo espanol.",
            "translation": "Ella habla ingles.",
        },
    },
    "vocabulary": {
        "focus_skill": "vocabulary",
        "vocabulary": [
            ("casa", "house"),
            ("trabajo", "work"),
            ("comida", "food"),
            ("tiempo", "time"),
            ("amigo", "friend"),
        ],
        "grammar": "Pair new nouns with short sentences so vocabulary is learned in context.",
        "examples": [
            ("Mi casa es pequena.", "My house is small."),
            ("Tengo trabajo hoy.", "I have work today."),
            ("Mi amigo come comida rica.", "My friend eats tasty food."),
        ],
        "answers": {
            "mc": "friend",
            "fill_prompt": "Mi ___ es pequena.",
            "fill": "casa",
            "open": "Mi amigo come comida rica.",
            "translation": "Tengo trabajo hoy.",
        },
    },
}


def _load_json(language: str) -> dict:
    path = CURRICULUM_DIR / f"{language.lower()}.json"
    return json.loads(path.read_text(encoding="utf-8"))


class CurriculumTests(unittest.TestCase):
    def test_language_files_match_schema_expectations(self):
        for language in LANGUAGES:
            with self.subTest(language=language):
                data = _load_json(language)
                self.assertEqual(data["language"], language)
                self.assertEqual(data["schema_version"], 1)
                self.assertIsInstance(data["levels"], dict)
                self.assertIsInstance(data["generic"], dict)
                self.assert_topic_valid(language, data["generic"], require_romanization=language == "Hindi")

                for level_name, level in data["levels"].items():
                    self.assertIn("topic_order", level)
                    self.assertIn("topics", level)
                    self.assertIn("default_topic", level)
                    for topic_name, topic in level["topics"].items():
                        with self.subTest(language=language, level=level_name, topic=topic_name):
                            self.assert_topic_valid(language, topic, require_romanization=language == "Hindi")

    def assert_topic_valid(self, language: str, topic: dict, *, require_romanization: bool) -> None:
        for field in ("title", "focus_skill", "vocabulary", "grammar", "examples", "answers"):
            self.assertIn(field, topic)
        self.assertGreaterEqual(len(topic["vocabulary"]), 5)
        self.assertGreaterEqual(len(topic["examples"]), 3)
        self.assertTrue(REQUIRED_ANSWERS.issubset(topic["answers"]))
        self.assertIn("___", topic["answers"]["fill_prompt"])
        for item in topic["vocabulary"] + topic["examples"]:
            self.assertTrue(item.get("target"))
            self.assertTrue(item.get("english"))
            if require_romanization:
                self.assertTrue(item.get("romanization"))

    def test_spanish_original_six_topics_are_zero_diff(self):
        bank = curriculum.lesson_bank("Spanish")
        for topic, expected in SPANISH_BASELINE.items():
            with self.subTest(topic=topic):
                actual = {key: bank[topic][key] for key in expected}
                self.assertEqual(actual, expected)

    def test_every_declared_lesson_topic_generates_lesson_and_quiz(self):
        for language in LANGUAGES:
            topics_by_level = curriculum.topics_by_level(language)
            for level, topics in topics_by_level.items():
                for topic in topics:
                    if curriculum.topic_lesson(language, level, topic) is None:
                        continue
                    with self.subTest(language=language, level=level, topic=topic):
                        state = default_state(language)
                        profile_state(state)["current_level"] = level
                        language_state(state)["weak_topics"] = []
                        language_state(state)["mistake_memory"] = {}
                        review_queue(state).clear()
                        with patch("fluent_ai.agent.random.choice", return_value=topic):
                            lesson = generate_lesson(state)
                        quiz = generate_quiz(state, lesson)
                        self.assertEqual(lesson["language"], language)
                        self.assertEqual(lesson["topic"], topic)
                        self.assertGreaterEqual(len(lesson["vocabulary"]), 5)
                        self.assertGreaterEqual(len(lesson["examples"]), 3)
                        self.assertGreaterEqual(len(quiz), 5)

    def test_accented_answers_grade_correctly(self):
        accented_question = {
            "type": "fill_blank",
            "skill": "vocabulary",
            "topic": "cafe orders",
            "prompt": "Fill in the blank.",
            "answer": "Quisiera un café",
            "acceptable_answers": ["Quisiera un café"],
        }
        plain_question = dict(accented_question, answer="Quisiera un cafe", acceptable_answers=["Quisiera un cafe"])

        self.assertTrue(evaluate_answers([accented_question], ["Quisiera un cafe"])[0].correct)
        self.assertTrue(evaluate_answers([plain_question], ["Quisiera un café"])[0].correct)

    def test_hindi_loader_exposes_romanization_metadata(self):
        bank = curriculum.lesson_bank("Hindi")
        for topic_name, topic in bank.items():
            with self.subTest(topic=topic_name):
                if topic_name in {"cafe orders", "travel plans", "health symptoms", "past weekend", "vocabulary"}:
                    continue
                self.assertTrue(topic.get("romanization_available"))
                self.assertTrue(all(item.get("romanization") for item in topic["vocabulary_rich"]))
                self.assertTrue(all(item.get("romanization") for item in topic["examples_rich"]))

    def test_loader_resolves_from_copied_package_layout(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package = root / "fluent_ai"
            package.mkdir()
            shutil.copy(Path(__file__).resolve().parents[1] / "fluent_ai" / "curriculum.py", package / "curriculum.py")
            shutil.copytree(CURRICULUM_DIR, package / "curriculum")

            spec = importlib.util.spec_from_file_location("copied_curriculum", package / "curriculum.py")
            self.assertIsNotNone(spec)
            module = importlib.util.module_from_spec(spec)
            sys.modules["copied_curriculum"] = module
            assert spec and spec.loader
            spec.loader.exec_module(module)

            lesson = module.topic_lesson("French", "A1", "cafe_orders")
            self.assertEqual(lesson["vocabulary"][0], ("je voudrais", "I would like"))
            self.assertIn("A1", module.topics_by_level("Hindi"))


if __name__ == "__main__":
    unittest.main()
