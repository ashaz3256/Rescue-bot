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


def image_url(img: Image.Image, side: int | None = None) -> str:
    """Downscale and encode a PIL image as a base64 JPEG data URL."""
    side = side or config.MAX_IMAGE_SIDE
    img = img.convert("RGB")
    img.thumbnail((side, side))
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


_thinking_switch_works = True


def ask(model: str, prompt: str, img: Image.Image | None = None,
        max_tokens: int = 1500, temperature: float = 0.15,
        image_side: int | None = None, thinking: str | None = None) -> tuple[str, float]:
    """Send a prompt (optionally with an image). Returns (reply text, seconds taken).

    thinking="off" asks the model to skip its reasoning phase (much faster when supported).
    If the API rejects the switch, we drop it for the rest of the session and carry on.
    """
    global _thinking_switch_works
    thinking = thinking or config.THINKING
    content: list[dict[str, Any]] | str
    if img is not None:
        content = [{"type": "text", "text": prompt},
                   {"type": "image_url", "image_url": {"url": image_url(img, image_side)}}]
    else:
        content = prompt
    kwargs: dict[str, Any] = dict(model=model, temperature=temperature, max_tokens=max_tokens,
                                  messages=[{"role": "user", "content": content}])
    if thinking == "off" and _thinking_switch_works:
        kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
    t0 = time.time()
    try:
        r = client().chat.completions.create(**kwargs)
    except Exception as e:  # some models refuse the switch: retry once without it
        if "extra_body" not in kwargs or "400" not in str(e):
            raise
        _thinking_switch_works = False
        kwargs.pop("extra_body")
        t0 = time.time()
        r = client().chat.completions.create(**kwargs)
    return (r.choices[0].message.content or ""), time.time() - t0


def list_models() -> list[str]:
    return sorted(m.id for m in client().models.list().data)
