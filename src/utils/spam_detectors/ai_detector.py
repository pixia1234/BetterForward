"""AI-based spam detector using an OpenAI-compatible API with optional images."""

import base64
import json
import mimetypes
from typing import List, Optional, Tuple

import httpx
from telebot import TeleBot
from telebot.types import File, Message

from src.config import logger, _
from src.utils.spam_detector_base import SpamDetectorBase


class OpenAISpamDetector(SpamDetectorBase):
    """Spam detector that delegates classification to an OpenAI-compatible model."""

    def __init__(self, api_key: str, base_url: str, model: str = "gpt-3.5-turbo",
                 threshold: float = 0.5, request_timeout: float = 15.0,
                 bot: Optional[TeleBot] = None):
        self.api_key = api_key
        # Keep caller-supplied base as-is (OpenAI: https://api.openai.com/v1,
        # Gemini-OpenAI: https://generativelanguage.googleapis.com/v1beta/openai)
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.threshold = threshold
        self.request_timeout = request_timeout
        # TeleBot instance is needed for downloading images when doing multimodal checks
        self.bot = bot

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

        if not (message.text or message.caption or self._has_images(message)):
            return False, None

        user_text = message.text or message.caption or ""
        image_parts = self._extract_image_parts(message)
        messages = self._build_messages(user_text, image_parts)

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

    def _build_messages(self, user_text: str, image_parts: List[dict]):
        """Build chat messages compatible with OpenAI/Gemini OpenAI endpoints."""
        system_text = (
            "You are a strict spam filter for a Telegram relay bot. "
            "Return JSON with fields: spam (boolean), confidence (0-1), reason (short text). "
            "Mark spam when the message or attached images are unsolicited ads, phishing, scams, or mass promotion. "
            "Only return the JSON object. Do not return any other text."
        )
        def _as_blocks(text: str):
            return [{"type": "text", "text": text}]

        user_blocks = []
        if user_text:
            user_blocks.extend(_as_blocks(user_text))
        else:
            user_blocks.extend(_as_blocks("No user text was provided. Review only the attached images for spam."))

        if image_parts:
            user_blocks.extend(image_parts)

        return [
            {"role": "system", "content": _as_blocks(system_text)},
            {"role": "user", "content": user_blocks},
        ]

    @staticmethod
    def _safe_confidence(raw_value) -> float:
        """Convert confidence to a bounded float."""
        try:
            confidence = float(raw_value)
        except (TypeError, ValueError):
            return 0.5
        return max(0.0, min(confidence, 1.0))

    def _has_images(self, message: Message) -> bool:
        """Check whether the Telegram message carries image content."""
        if getattr(message, "photo", None):
            return True
        doc = getattr(message, "document", None)
        return bool(doc and doc.mime_type and doc.mime_type.startswith("image/"))

    def _extract_image_parts(self, message: Message) -> List[dict]:
        """Download and encode images as data URLs for multimodal models."""
        if not self.bot:
            return []

        image_parts: List[dict] = []

        # Photos (use the highest resolution available)
        if getattr(message, "photo", None):
            photo = message.photo[-1]
            data = self._download_file(photo.file_id)
            if data:
                image_parts.append(self._to_image_part(data, "image/jpeg"))

        # Image documents (stickers/animations are ignored here)
        doc = getattr(message, "document", None)
        if doc and doc.mime_type and doc.mime_type.startswith("image/"):
            data = self._download_file(doc.file_id)
            if data:
                image_parts.append(self._to_image_part(data, doc.mime_type))

        return image_parts

    def _download_file(self, file_id: str) -> Optional[bytes]:
        """Download file bytes from Telegram."""
        try:
            file_info: File = self.bot.get_file(file_id)
            return self.bot.download_file(file_info.file_path)
        except Exception as e:
            logger.error(_("Failed to download file for AI spam detection: {}").format(str(e)))
        return None

    @staticmethod
    def _to_image_part(data: bytes, mime_type: Optional[str]) -> dict:
        """Convert image bytes to OpenAI-compatible inline image."""
        guessed_type = mime_type or mimetypes.guess_type("file")[0] or "image/jpeg"
        encoded = base64.b64encode(data).decode("utf-8")
        return {
            "type": "image_url",
            "image_url": {
                "url": f"data:{guessed_type};base64,{encoded}"
            }
        }
