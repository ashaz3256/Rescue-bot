"""Thin wrapper around Nebius Token Factory (OpenAI-compatible)."""
from __future__ import annotations

import base64
import io
import json
import re
import time
from typing import Any

from PIL import Image

import config

_client = None


def client():
    """Create the API client on first use, so DRY_RUN tools without a key still import."""
    global _client
    if _client is None:
        if not config.API_KEY:
            raise SystemExit("NEBIUS_API_KEY is not set. Copy .env.example to .env and add your key.")
        from openai import OpenAI
        _client = OpenAI(base_url=config.API_BASE, api_key=config.API_KEY)
    return _client


def image_url(img: Image.Image) -> str:
    """Downscale and encode a PIL image as a base64 JPEG data URL."""
    img = img.convert("RGB")
    img.thumbnail((config.MAX_IMAGE_SIDE, config.MAX_IMAGE_SIDE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def parse_json(text: str) -> dict[str, Any] | None:
    """Return the last {...} object in a reply. Reasoning models may think before answering."""
    for candidate in reversed(re.findall(r"\{[^{}]*\}", text or "", re.S)):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def ask(model: str, prompt: str, img: Image.Image | None = None,
        max_tokens: int = 1500, temperature: float = 0.15) -> tuple[str, float]:
    """Send a prompt (optionally with an image). Returns (reply text, seconds taken)."""
    content: list[dict[str, Any]] | str
    if img is not None:
        content = [{"type": "text", "text": prompt},
                   {"type": "image_url", "image_url": {"url": image_url(img)}}]
    else:
        content = prompt
    t0 = time.time()
    r = client().chat.completions.create(
        model=model, temperature=temperature, max_tokens=max_tokens,
        messages=[{"role": "user", "content": content}])
    return (r.choices[0].message.content or ""), time.time() - t0


def list_models() -> list[str]:
    return sorted(m.id for m in client().models.list().data)
