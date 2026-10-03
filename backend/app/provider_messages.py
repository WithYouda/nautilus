"""Encode transient canonical user images into the configured wire protocol.

Only the application-facing ``_images`` field uses this format. It is removed
before sending, and never changes the selected Provider or model.

Protocol references:
https://developers.openai.com/api/docs/guides/images-vision
https://ai.google.dev/api/generate-content#Part
https://platform.claude.com/docs/en/build-with-claude/vision
"""
from __future__ import annotations

import base64
import binascii
from typing import Any


def message_images(message: dict[str, Any]) -> list[dict[str, str]]:
    # Import lazily because providers also imports these shared helpers.
    from .providers import ProviderError

    def invalid() -> ProviderError:
        return ProviderError("图片输入格式无效或不受支持", kind="invalid_image_input")

    if "_images" not in message:
        return []
    images = message["_images"]
    if not isinstance(images, list):
        raise invalid()
    if not images:
        return []
    if message.get("role") != "user" or not isinstance(message.get("content"), str):
        raise invalid()
    for item in images:
        if not isinstance(item, dict) or set(item) != {"media_type", "data"}:
            raise invalid()
        media_type, data = item["media_type"], item["data"]
        if not isinstance(media_type, str) or media_type not in {"image/png", "image/jpeg", "image/webp"} or not isinstance(data, str) or not data:
            raise invalid()
        try:
            decoded = base64.b64decode(data, validate=True)
        except (ValueError, binascii.Error):
            raise invalid() from None
        if not decoded or base64.b64encode(decoded).decode("ascii") != data:
            raise invalid()
        # Upload utilities own full decoding and decoder security. Check the
        # declared container here as well, without resizing or altering bytes.
        valid = (
            (media_type == "image/png" and decoded.startswith(b"\x89PNG\r\n\x1a\n"))
            or (media_type == "image/jpeg" and decoded.startswith(b"\xff\xd8\xff"))
            or (media_type == "image/webp" and decoded.startswith(b"RIFF") and decoded[8:12] == b"WEBP")
        )
        if not valid:
            raise invalid()
    return images


def encode_message(message: dict[str, Any], kind: str) -> dict[str, Any] | None:
    """Return one vendor message, keeping text-only wire behavior unchanged."""
    images = message_images(message)
    role = message.get("role")
    if kind in {"openai_compatible", "openai_responses"}:
        converted = {key: value for key, value in message.items() if key != "_images"}
        if images:
            if kind == "openai_compatible":
                text = [{"type": "text", "text": message["content"]}] if message["content"] else []
                converted["content"] = text + [
                    {"type": "image_url", "image_url": {"url": f"data:{image['media_type']};base64,{image['data']}"}}
                    for image in images
                ]
            else:
                text = [{"type": "input_text", "text": message["content"]}] if message["content"] else []
                converted["content"] = text + [
                    {"type": "input_image", "image_url": f"data:{image['media_type']};base64,{image['data']}"}
                    for image in images
                ]
        return converted
    if role == "system":
        return None
    if kind == "google":
        text = str(message.get("content", ""))
        parts = [{"text": text}] if text or not images else []
        parts.extend({"inlineData": {"mimeType": image["media_type"], "data": image["data"]}} for image in images)
        return {"role": "model" if role == "assistant" else "user", "parts": parts}
    if kind == "anthropic":
        content: Any = str(message.get("content", ""))
        if images:
            content = [
                *[{"type": "image", "source": {"type": "base64", **image}} for image in images],
                *([{"type": "text", "text": content}] if content else []),
            ]
        return {"role": "assistant" if role == "assistant" else "user", "content": content}
    from .providers import ProviderError
    raise ProviderError("暂不支持提供方类型", kind="config_error")


def encode_messages(messages: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    converted = [encode_message(message, kind) for message in messages]
    return [message for message in converted if message is not None]
