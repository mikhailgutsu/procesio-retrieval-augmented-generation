"""Provider-agnostic LLM access — Anthropic Claude or OpenAI, chosen by config.

The answer-extraction step uses :func:`complete_json`; the OCR vision fallback
uses :func:`vision`. The provider is selected by ``LLM_PROVIDER`` (extraction) and
``VISION_PROVIDER`` (vision; empty = inherit ``LLM_PROVIDER``), so you can e.g. run
the vision fallback on a cheap OpenAI model (gpt-4o-mini) independently of
extraction. Keys: ``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY``.
"""

from __future__ import annotations

import base64
from typing import Any

from .config import Settings, get_settings
from .errors import ConfigError, ExtractionError
from .logging_config import get_logger

log = get_logger(__name__)


def _anthropic_client(settings: Settings):
    import anthropic

    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _openai_client(settings: Settings):
    from openai import OpenAI

    return OpenAI(api_key=settings.openai_api_key)


# ─────────────────────────────────────────────────────────────────────────────
# Text/JSON completion — used by the answer-extraction step
# ─────────────────────────────────────────────────────────────────────────────
def complete_json(
    system: str,
    user: str,
    settings: Settings | None = None,
    json_schema: dict[str, Any] | None = None,
    client: Any | None = None,
) -> str:
    """Return the model's text output (expected to be JSON), provider-dispatched.

    ``client`` may be injected (tests) to bypass real construction.
    """
    settings = settings or get_settings()
    provider = (settings.llm_provider or "anthropic").lower()
    if provider == "openai":
        return _openai_complete_json(system, user, settings, client)
    return _anthropic_complete_json(system, user, settings, json_schema, client)


def _anthropic_complete_json(system, user, settings, json_schema, client):
    if client is None:
        if not settings.anthropic_api_key:
            raise ConfigError(
                "ANTHROPIC_API_KEY is not set — required for extraction (LLM_PROVIDER=anthropic)."
            )
        client = _anthropic_client(settings)
    kwargs: dict[str, Any] = {
        "model": settings.anthropic_model,
        "max_tokens": settings.llm_max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    if settings.llm_thinking:
        kwargs["thinking"] = {"type": "adaptive"}
    try:
        if json_schema is not None:
            resp = client.messages.create(
                output_config={"format": {"type": "json_schema", "schema": json_schema}}, **kwargs
            )
        else:
            resp = client.messages.create(**kwargs)
    except Exception as exc:  # older SDK/model without output_config → plain JSON instruction
        log.warning("Structured outputs unavailable (%s); plain JSON fallback.", exc)
        kwargs["system"] = system + "\n\nRespond with ONLY the JSON object, no prose."
        resp = client.messages.create(**kwargs)

    if getattr(resp, "stop_reason", None) == "refusal":
        raise ExtractionError("The model refused to answer this request.")
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    if not text.strip():
        raise ExtractionError("The model returned no text output.")
    return text


def _openai_complete_json(system, user, settings, client):
    if client is None:
        if not settings.openai_api_key:
            raise ConfigError(
                "OPENAI_API_KEY is not set — required for extraction (LLM_PROVIDER=openai)."
            )
        client = _openai_client(settings)
    resp = client.chat.completions.create(
        model=settings.openai_model,
        max_tokens=settings.llm_max_tokens,
        messages=[
            {"role": "system", "content": system + "\n\nRespond with ONLY a JSON object."},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
    )
    text = resp.choices[0].message.content or ""
    if not text.strip():
        raise ExtractionError("The model returned no text output.")
    return text


# ─────────────────────────────────────────────────────────────────────────────
# Vision — used by the OCR fallback for images/diagrams/photos
# ─────────────────────────────────────────────────────────────────────────────
def vision(prompt: str, image_png: bytes, settings: Settings | None = None) -> str:
    """Return a transcription/description of a PNG image, or '' on failure / no key."""
    settings = settings or get_settings()
    provider = settings.resolved_vision_provider
    b64 = base64.standard_b64encode(image_png).decode("utf-8")
    try:
        if provider == "openai":
            if not settings.openai_api_key:
                log.warning("Vision requested (openai) but OPENAI_API_KEY is unset; skipping.")
                return ""
            client = _openai_client(settings)
            resp = client.chat.completions.create(
                model=settings.openai_model,
                max_tokens=settings.llm_max_tokens,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                        ],
                    }
                ],
            )
            return (resp.choices[0].message.content or "").strip()

        if not settings.anthropic_api_key:
            log.warning("Vision requested (anthropic) but ANTHROPIC_API_KEY is unset; skipping.")
            return ""
        client = _anthropic_client(settings)
        resp = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=settings.llm_max_tokens,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
    except Exception as exc:  # vision is best-effort
        log.warning("Vision transcription failed (%s): %s", provider, exc)
        return ""
