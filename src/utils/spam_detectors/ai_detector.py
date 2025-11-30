"""AI-based spam detector using an OpenAI-compatible API."""

import json
from typing import Optional, Tuple

import httpx
from telebot.types import Message

from src.config import logger, _
from src.utils.spam_detector_base import SpamDetectorBase


class OpenAISpamDetector(SpamDetectorBase):
    """Spam detector that delegates classification to an OpenAI-compatible model."""

    def __init__(self, api_key: str, base_url: str, model: str = "gpt-3.5-turbo",
                 threshold: float = 0.5, request_timeout: float = 15.0):
        self.api_key = api_key
        # Keep caller-supplied base as-is (OpenAI: https://api.openai.com/v1,
        # Gemini-OpenAI: https://generativelanguage.googleapis.com/v1beta/openai)
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.threshold = threshold
        self.request_timeout = request_timeout

    def get_name(self) -> str:
        return "AI Detector"

    def is_enabled(self, context: Optional[dict] = None) -> bool:
        """Enabled only when credentials exist and context allows AI."""
        if not self.api_key or not self.base_url:
            return False

        if context and context.get("enable_ai") is False:
            return False

        return True

    def detect(self, message: Message, context: Optional[dict] = None) -> Tuple[bool, Optional[dict]]:
        """Use chat completion endpoint to classify spam."""
        if not self.is_enabled(context):
            return False, None

        if not message.text:
            return False, None

        messages = self._build_messages(message.text)

        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "temperature": 0,
                    "messages": messages,
                },
                timeout=self.request_timeout,
            )
            response.raise_for_status()
        except Exception as e:
            logger.error(_("AI spam detection request failed: {}").format(str(e)))
            return False, None

        content = self._extract_content(response)
        if content is None:
            return False, None

        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            logger.error(_("AI spam detection returned non-JSON content"))
            return False, None

        spam_flag = bool(result.get("spam"))
        confidence = self._safe_confidence(result.get("confidence"))

        if spam_flag and confidence >= self.threshold:
            return True, {
                "method": "ai",
                "detector": self.get_name(),
                "confidence": confidence,
                "reason": result.get("reason"),
            }

        return False, None

    def _extract_content(self, response: httpx.Response) -> Optional[str]:
        """Extract the text content from an OpenAI-compatible response."""
        try:
            data = response.json()
            choices = data.get("choices") or []
            if not choices:
                return None
            choice = choices[0]
            message = choice.get("message") or {}

            # OpenAI style: message.content is a string
            content = message.get("content")
            # Gemini openai-compatible: content may be a list of text parts
            if isinstance(content, list):
                parts = []
                for part in content:
                    if isinstance(part, dict):
                        if "text" in part:
                            parts.append(str(part["text"]))
                        elif "content" in part:
                            parts.append(str(part["content"]))
                content = "\n".join(parts) if parts else None

            # Fallbacks: choice.content or choice.text
            if content is None:
                content = choice.get("content") or choice.get("text")

            if isinstance(content, str):
                stripped = content.strip()
                # Handle optional fenced code blocks
                if stripped.startswith("```"):
                    stripped = stripped.strip("`")
                    if "\n" in stripped:
                        stripped = "\n".join(stripped.split("\n")[1:])
                return stripped
        except Exception as e:
            logger.error(_("Failed to parse AI spam detection response: {}").format(str(e)))
        return None

    def _build_messages(self, user_text: str):
        """Build chat messages compatible with OpenAI and Gemini OpenAI endpoints."""
        system_text = (
            "You are a strict spam filter for a Telegram relay bot. "
            "Return JSON with fields: spam (boolean), confidence (0-1), reason (short text). "
            "Mark spam when the message is unsolicited ads, phishing, scams, or mass promotion. "
            "Only return the JSON object. Do not return any other text."
        )
        def _as_blocks(text: str):
            return [{"type": "text", "text": text}]

        return [
            {"role": "system", "content": _as_blocks(system_text)},
            {"role": "user", "content": _as_blocks(user_text)},
        ]

    @staticmethod
    def _safe_confidence(raw_value) -> float:
        """Convert confidence to a bounded float."""
        try:
            confidence = float(raw_value)
        except (TypeError, ValueError):
            return 0.5
        return max(0.0, min(confidence, 1.0))
