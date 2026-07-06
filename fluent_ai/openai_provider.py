from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from fluent_ai.agent import current_level
from fluent_ai.config import load_env_file, openai_model
from fluent_ai.state import active_language, conversation_memory, language_state, profile_state


ALLOWED_QUIZ_ERROR_CATEGORIES = {
    "vocabulary_missing",
    "wrong_conjugation",
    "wrong_tense",
    "word_order",
    "comprehension",
    "too_short",
    "unnatural",
}

ALLOWED_QUIZ_SEVERITIES = {"low", "medium", "high"}


NATURAL_TURN_POLICY = """
Natural conversation policy:
- Do not interrupt the learner. Treat short pauses, filler words, self-corrections, and thinking sounds as part of their turn.
- Wait for a real pause of about 2.5 seconds before responding. If the learner sounds mid-sentence, keep listening.
- If the learner is silent for several seconds after your question, give one short check-in such as "Take your time" or "¿Quieres una pista?". Do not monologue.
- If the learner says they did not understand, asks you to repeat, asks what something means, or falls back to English, respond in the language they used for that help request.
- For English help, explain the meaning in English first, then offer one simple target-language phrase and gently invite them back into the target language.
- After two failed attempts or repeated confusion, use more English scaffolding briefly, then continue in the target language when they are ready.
""".strip()


class OpenAIProvider:
    def __init__(self) -> None:
        load_env_file()
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.model = openai_model()
        self.reasoning_effort = os.getenv("OPENAI_REASONING_EFFORT", "low")
        self.verbosity = os.getenv("OPENAI_VERBOSITY", "low")
        self.last_error: str | None = None
        self._client = None

    @property
    def available(self) -> bool:
        return bool(self.api_key) and self._load_client() is not None

    def status(self) -> str:
        if not self.api_key:
            return "OpenAI required: OPENAI_API_KEY is not set."
        if self._load_client() is None:
            return f"OpenAI disabled: {self.last_error}"
        return f"OpenAI enabled: model {self.model}."

    def realtime_client_secret(
        self,
        state: dict[str, Any],
        *,
        video_on: bool = False,
        video_context: str | None = None,
    ) -> dict[str, Any]:
        if not self.api_key:
            return {"ok": False, "error": "OPENAI_API_KEY is not set."}

        realtime_model = os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime")
        voice = os.getenv("OPENAI_REALTIME_VOICE", "alloy")
        target_language = active_language(state)
        visual = f" If video context is enabled, use this camera analysis: {video_context}." if video_on and video_context else ""
        goal_instruction = _next_conversation_goal_instruction(state)
        instructions = _realtime_instructions(
            target_language=target_language,
            level=current_level(state),
            weak_topics=language_state(state).get("weak_topics", []),
            visual=visual,
            goal_instruction=goal_instruction,
        )
        turn_detection = _realtime_turn_detection(state)
        payload = {
            "expires_after": {"anchor": "created_at", "seconds": 600},
            "session": {
                "type": "realtime",
                "model": realtime_model,
                "instructions": instructions,
                "output_modalities": ["audio"],
                "audio": {
                    "input": {
                        "turn_detection": turn_detection,
                    },
                    "output": {
                        "voice": voice,
                    },
                },
            },
        }
        request = urllib.request.Request(
            "https://api.openai.com/v1/realtime/client_secrets",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return {"ok": False, "error": f"Realtime client secret failed: HTTP {exc.code}: {detail[:300]}"}
        except Exception as exc:
            return {"ok": False, "error": f"Realtime client secret failed: {exc.__class__.__name__}: {exc}"}

        secret_value = data.get("value")
        if not secret_value and isinstance(data.get("client_secret"), dict):
            secret_value = data["client_secret"].get("value")

        return {
            "ok": True,
            "client_secret": secret_value,
            "expires_at": data.get("expires_at")
            or (data.get("client_secret", {}).get("expires_at") if isinstance(data.get("client_secret"), dict) else None),
            "session": data.get("session", {}),
            "model": realtime_model,
            "voice": voice,
            "turn_detection": turn_detection,
        }

    def analyze_camera_frame(self, state: dict[str, Any], image_data_url: str) -> dict[str, Any]:
        if not self.api_key:
            return {"ok": False, "error": "OPENAI_API_KEY is not set."}
        if not image_data_url.startswith("data:image/"):
            return {"ok": False, "error": "Camera frame must be an image data URL."}

        vision_model = os.getenv("OPENAI_VISION_MODEL", "gpt-4.1-mini")
        target_language = active_language(state)
        prompt = (
            f"You are the Vision Context Agent for a live {target_language} tutoring call. "
            "The image is a camera frame from the learner's current video feed. "
            "Look at the camera frame and return JSON only with keys: "
            "summary, primary_object, spanish_prompt, confidence. "
            "summary should be one short English phrase about what is visible right now. "
            "primary_object should be the main object or scene, or empty string if unclear. "
            "Prefer being uncertain over being wrong: if you cannot clearly identify the object, set confidence to low and say unclear instead of guessing. "
            f"spanish_prompt should be one beginner-friendly {target_language} tutor prompt using what you see. "
            "If the frame looks like a synthetic webcam test pattern or fake media source, say "
            '"synthetic test camera feed" in summary, leave primary_object empty, and do not invent an object. '
            "Do not identify private or sensitive personal attributes."
        )
        payload = {
            "model": vision_model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": image_data_url, "detail": "low"},
                    ],
                }
            ],
        }
        request = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return {"ok": False, "error": f"Vision analysis failed: HTTP {exc.code}: {detail[:300]}"}
        except Exception as exc:
            return {"ok": False, "error": f"Vision analysis failed: {exc.__class__.__name__}: {exc}"}

        output_text = _response_output_text(data)
        parsed = _extract_json(output_text)
        if not isinstance(parsed, dict):
            parsed = {
                "summary": "camera frame analyzed",
                "primary_object": "",
                "spanish_prompt": output_text[:220],
                "confidence": "medium",
            }

        return {
            "ok": True,
            "model": vision_model,
            "summary": str(parsed.get("summary") or "camera frame analyzed")[:180],
            "primary_object": str(parsed.get("primary_object") or "")[:80],
            "spanish_prompt": str(parsed.get("spanish_prompt") or "")[:220],
            "confidence": str(parsed.get("confidence") or "medium")[:40],
        }

    def health_check(self) -> bool:
        if not self.available:
            return False
        text = self._text_response("Return exactly: FLUENTAI_OK")
        return "FLUENTAI_OK" in text

    def enhance_lesson(self, state: dict[str, Any], lesson: dict[str, Any]) -> dict[str, Any]:
        if not self.available:
            return lesson

        profile = profile_state(state)
        prompt = f"""
You are the Lesson Generator Agent for FluentAI.
Return JSON only. Do not use Markdown.

Learner profile:
- target language: {active_language(state)}
- level: {current_level(state)}
- weak topics: {', '.join(language_state(state).get('weak_topics', []))}
- learning goals: {'; '.join(profile.get('learning_goals', []))}

Keep this lesson topic and focus:
- topic: {lesson['topic']}
- focus skill: {lesson['focus_skill']}
- duration minutes: {lesson['minutes']}
- selection reason: {lesson.get('reason', 'No selection reason provided.')}

Return exactly these keys:
{{
  "vocabulary": [["target-language phrase", "English meaning"], ... five items],
  "grammar_explanation": "one concise explanation",
  "examples": [["target-language sentence", "English meaning"], ... three items],
  "micro_task": "one short speaking task"
}}

Requirements:
- Keep the target language natural and level-appropriate.
- For A1/A2, keep sentences very short.
- Prefer practical conversation examples.
"""
        text = self._text_response(prompt)
        data = _extract_json(text)
        if not isinstance(data, dict):
            return lesson

        enhanced = lesson.copy()
        if _valid_pairs(data.get("vocabulary"), 5):
            enhanced["vocabulary"] = data["vocabulary"]
        if isinstance(data.get("grammar_explanation"), str):
            enhanced["grammar_explanation"] = data["grammar_explanation"]
        if _valid_pairs(data.get("examples"), 3):
            enhanced["examples"] = data["examples"]
        if isinstance(data.get("micro_task"), str):
            enhanced["micro_task"] = data["micro_task"]
        enhanced["source"] = "openai"
        return enhanced

    def evaluate_quiz_answers(
        self,
        state: dict[str, Any],
        lesson: dict[str, Any],
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any] | None] | None:
        if not self.available:
            return None
        if not items:
            return []

        prompt = f"""
You are FluentAI's Quiz Evaluator Agent.
Return strict JSON only. Do not use Markdown.

Allowed error_category values for incorrect answers, plus advisory "unnatural" on correct answers:
{", ".join(sorted(ALLOWED_QUIZ_ERROR_CATEGORIES))}

Return a strict JSON array with one object per item, in the same order.
Each object must be exactly:
{{
  "correct": true or false,
  "error_category": null or one allowed value,
  "feedback": "one specific learner-facing sentence",
  "corrected_form": null or "the corrected target-language form",
  "severity": "low" or "medium" or "high",
  "confidence": number from 0 to 1
}}

Use correct=true and error_category="unnatural" only when the answer is understandable but not the native phrasing.

Lesson context:
- language: {active_language(state)}
- level: {current_level(state)}
- topic: {lesson.get('topic')}
- focus skill: {lesson.get('focus_skill')}
- reason: {lesson.get('reason', '')}

Items:
{json.dumps(items, ensure_ascii=True)}
"""
        data = _extract_json(self._text_response(prompt))
        if not isinstance(data, list) or len(data) != len(items):
            return None
        return [_validate_quiz_grade(item) for item in data]

    def conversation_tutor_reply(
        self,
        topic: dict[str, Any],
        state: dict[str, Any],
        transcript: list[Any],
        phase: str,
        fallback: str,
    ) -> str | None:
        if not self.available:
            return None

        target_language = active_language(state)
        recent_turns = "\n".join(
            f"Tutor: {turn.tutor_text}\nLearner: {turn.learner_text}\nFeedback: {turn.feedback}"
            for turn in transcript[-3:]
        )
        visual = topic.get("visual", {})
        goal_guidance = _topic_goal_guidance(topic)
        prompt = f"""
You are FluentAI's Conversation Tutor Agent.
Return only the next tutor utterance. No labels. No Markdown.

Product behavior:
- You initiate and steer the conversation.
- The selected target language is {target_language}.
- Detect whether the learner's latest reply is in Hindi, Spanish, French, or English.
- If the learner replies in Hindi, Spanish, or French, answer in that same language.
- If the learner asks what a phrase means, asks for English, says they do not understand, or asks for help, answer the question directly in English first. Then give one simple {target_language} model phrase and a tiny follow-up.
- Match the learner's level: {current_level(state)}.
- Current topic: {topic['topic']}.
- Complexity: {topic['complexity']}.
- Tutor guidance: {goal_guidance or 'No lesson-specific goal for this call.'}
- If beginner, use one short sentence plus one simple question.
- If advanced, ask for opinions, reasons, tradeoffs, or examples.
- If video context exists, use it naturally.
- Be warm, conversational, and specific.
- Natural turn policy: {NATURAL_TURN_POLICY}

Video context:
{json.dumps(visual, ensure_ascii=True)}

Recent turns:
{recent_turns or "No prior turns. Start the call now."}

Fallback utterance to improve if useful:
{fallback}

Phase: {phase}
"""
        text = self._text_response(prompt)
        cleaned = " ".join(text.strip().split())
        if not cleaned:
            return None
        return cleaned[:500]

    def _load_client(self):
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI
        except Exception as exc:  # pragma: no cover - depends on local package state.
            self.last_error = f"OpenAI SDK import failed: {exc.__class__.__name__}"
            return None

        try:
            self._client = OpenAI(api_key=self.api_key, timeout=30)
        except Exception as exc:  # pragma: no cover - defensive.
            self.last_error = f"OpenAI client setup failed: {exc.__class__.__name__}"
            return None
        return self._client

    def _text_response(self, prompt: str) -> str:
        client = self._load_client()
        if client is None:
            return ""

        kwargs: dict[str, Any] = {
            "model": self.model,
            "input": prompt,
            "reasoning": {"effort": self.reasoning_effort},
            "text": {"verbosity": self.verbosity},
        }
        try:
            response = client.responses.create(**kwargs)
        except TypeError:
            response = client.responses.create(model=self.model, input=prompt)
        except Exception as exc:
            self.last_error = _safe_error(exc)
            return ""

        output_text = getattr(response, "output_text", None)
        if output_text:
            return output_text
        return str(response)


def _realtime_instructions(
    *,
    target_language: str,
    level: str,
    weak_topics: list[Any],
    visual: str = "",
    goal_instruction: str = "",
) -> str:
    weak = ", ".join(str(topic) for topic in weak_topics) or "none"
    goal = f" Today, steer toward: {goal_instruction}. " if goal_instruction else ""
    return (
        f"You are FluentAI, a warm live {target_language} tutor in a FaceTime-style call. "
        f"The learner level is {level}. Weak topics: {weak}. "
        + goal
        + f"Initiate the conversation in {target_language}, then adapt turn-by-turn. "
        "Detect whether the learner replies in Hindi, Spanish, French, or English. "
        "When the learner clearly speaks Hindi, Spanish, or French, respond in that same language. "
        f"When the learner speaks English because they need help, answer in English first, then give one simple {target_language} model phrase and invite them back. "
        "For beginners, use one short sentence and one simple question at a time. "
        "Correct gently and provide a short model phrase when needed. "
        "Keep turns natural, brief, and encouraging. "
        + NATURAL_TURN_POLICY
        + visual
    )


def _topic_goal_guidance(topic: dict[str, Any]) -> str:
    goal = topic.get("goal")
    if isinstance(goal, dict) and goal.get("instruction"):
        return f"Today, steer toward: {goal['instruction']}"
    return ""


def _next_conversation_goal_instruction(state: dict[str, Any]) -> str:
    goal = conversation_memory(state).get("next_conversation_goal")
    if isinstance(goal, dict) and goal.get("instruction"):
        return str(goal["instruction"])
    return ""


def _realtime_turn_detection(state: dict[str, Any] | None = None) -> dict[str, Any]:
    memory = conversation_memory(state or {"active_language": "Spanish", "languages": {}}) if isinstance(state, dict) else {}
    confidence = float(memory.get("speaking_confidence", 0.3) or 0.3)
    level = current_level(state or {"active_language": "Spanish", "languages": {}})
    if level in {"A1", "A2"} or confidence < 0.45:
        default_silence = 2800
    elif confidence > 0.72 or level in {"C1", "C2"}:
        default_silence = 1800
    else:
        default_silence = 2300
    return {
        "type": "server_vad",
        "threshold": _env_float("OPENAI_REALTIME_VAD_THRESHOLD", 0.65, 0.3, 0.95),
        "prefix_padding_ms": _env_int("OPENAI_REALTIME_PREFIX_PADDING_MS", 450, 150, 1000),
        "silence_duration_ms": _env_int("OPENAI_REALTIME_SILENCE_MS", default_silence, 1400, 4200),
        "idle_timeout_ms": _env_int("OPENAI_REALTIME_IDLE_PROMPT_MS", 6500, 3500, 11000),
        "create_response": True,
        "interrupt_response": False,
    }


def _env_int(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(low, min(high, value))


def _env_float(name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(low, min(high, value))


def _safe_error(exc: Exception) -> str:
    message = str(exc).splitlines()[0].strip()
    if len(message) > 120:
        message = message[:117] + "..."
    return f"{exc.__class__.__name__}: {message}" if message else exc.__class__.__name__


def _validate_quiz_grade(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    try:
        correct = data["correct"]
        feedback = data["feedback"]
        severity = data["severity"]
        confidence = data["confidence"]
    except KeyError:
        return None
    if not isinstance(correct, bool) or not isinstance(feedback, str) or not isinstance(severity, str):
        return None
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return None

    feedback = feedback.strip()
    severity = severity.strip().lower()
    confidence = float(confidence)
    if not feedback or severity not in ALLOWED_QUIZ_SEVERITIES or not 0 <= confidence <= 1:
        return None

    category = data.get("error_category")
    if category is not None:
        if not isinstance(category, str):
            return None
        category = category.strip().lower()
    if correct:
        if category not in {None, "unnatural"}:
            return None
    elif category not in ALLOWED_QUIZ_ERROR_CATEGORIES:
        return None

    corrected = data.get("corrected_form")
    if corrected is not None:
        if not isinstance(corrected, str):
            return None
        corrected = corrected.strip() or None

    return {
        "correct": correct,
        "error_category": category,
        "feedback": feedback[:260],
        "corrected_form": corrected,
        "severity": severity,
        "confidence": round(confidence, 3),
    }


def _extract_json(text: str) -> Any:
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        candidates: list[str] = []
        for opener, closer in (("{", "}"), ("[", "]")):
            start = stripped.find(opener)
            end = stripped.rfind(closer)
            if start != -1 and end > start:
                candidates.append(stripped[start : end + 1])
        for candidate in candidates:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
        return None


def _response_output_text(data: dict[str, Any]) -> str:
    direct = data.get("output_text")
    if isinstance(direct, str):
        return direct
    chunks: list[str] = []
    for item in data.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "\n".join(chunks)


def _valid_pairs(value: Any, expected_count: int) -> bool:
    if not isinstance(value, list) or len(value) < expected_count:
        return False
    return all(isinstance(item, list) and len(item) == 2 for item in value)
