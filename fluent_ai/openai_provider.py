from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from fluent_ai.agent import current_level
from fluent_ai.config import load_env_file, openai_model


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
            return "OpenAI disabled: OPENAI_API_KEY is not set."
        if self._load_client() is None:
            return f"OpenAI disabled: {self.last_error}"
        return "OpenAI connected."

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
        target_language = str(state.get("learner", {}).get("target_language", "Spanish"))
        visual = f" If video context is enabled, use this camera analysis: {video_context}." if video_on and video_context else ""
        instructions = (
            f"You are FluentAI, a warm live {target_language} tutor in a FaceTime-style call. "
            f"The learner level is {current_level(state)}. "
            f"Weak topics: {', '.join(state.get('weak_topics', [])) or 'none'}. "
            f"Initiate the conversation in {target_language}. "
            "Detect whether the learner replies in Hindi, Spanish, French, or English. "
            "When the learner replies in Hindi, Spanish, or French, respond in that same language. "
            "If the learner asks what something means, asks for English, says they do not understand, "
            "or uses phrases like 'what does that mean', briefly explain in English first, then give "
            f"one simple {target_language} model phrase and ask if they want to try it. "
            "For beginners, use one short sentence and one simple question at a time. "
            "Correct gently and provide a short model phrase when needed. "
            "Keep turns natural, brief, and encouraging."
            + visual
        )
        payload = {
            "expires_after": {"anchor": "created_at", "seconds": 600},
            "session": {
                "type": "realtime",
                "model": realtime_model,
                "instructions": instructions,
                "output_modalities": ["audio"],
                "audio": {
                    "input": {
                        "turn_detection": {"type": "server_vad"},
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
        }

    def analyze_camera_frame(self, state: dict[str, Any], image_data_url: str) -> dict[str, Any]:
        if not self.api_key:
            return {"ok": False, "error": "OPENAI_API_KEY is not set."}
        if not image_data_url.startswith("data:image/"):
            return {"ok": False, "error": "Camera frame must be an image data URL."}

        vision_model = os.getenv("OPENAI_VISION_MODEL", self.model)
        target_language = str(state.get("learner", {}).get("target_language", "Spanish"))
        prompt = (
            f"You are the Vision Context Agent for a live {target_language} tutoring call. "
            "The image is a camera frame from the learner's current video feed. "
            "Look at the camera frame and return JSON only with keys: "
            "summary, primary_object, spanish_prompt, confidence. "
            "summary should be one short English phrase about what is visible. "
            "primary_object should be the main object or scene, or empty string if unclear. "
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
            with urllib.request.urlopen(request, timeout=30) as response:
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

        prompt = f"""
You are the Lesson Generator Agent for FluentAI.
Return JSON only. Do not use Markdown.

Learner profile:
- target language: {state['learner']['target_language']}
- level: {current_level(state)}
- weak topics: {', '.join(state.get('weak_topics', []))}
- learning goals: {'; '.join(state['learner'].get('learning_goals', []))}

Keep this lesson topic and focus:
- topic: {lesson['topic']}
- focus skill: {lesson['focus_skill']}
- duration minutes: {lesson['minutes']}

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

        target_language = str(state.get("learner", {}).get("target_language", "Spanish"))
        recent_turns = "\n".join(
            f"Tutor: {turn.tutor_text}\nLearner: {turn.learner_text}\nFeedback: {turn.feedback}"
            for turn in transcript[-3:]
        )
        visual = topic.get("visual", {})
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
- If beginner, use one short sentence plus one simple question.
- If advanced, ask for opinions, reasons, tradeoffs, or examples.
- If video context exists, use it naturally.
- Be warm, conversational, and specific.

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
            self.last_error = f"{exc.__class__.__name__}: {exc}"
            return ""

        output_text = getattr(response, "output_text", None)
        if output_text:
            return output_text
        return str(response)


def _extract_json(text: str) -> dict[str, Any] | None:
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
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            return json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
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
