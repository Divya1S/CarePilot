"""Provider-agnostic LLM adapter — so Relay runs against whatever key you have.

No Anthropic key required. Configure via environment:

  RELAY_LLM_PROVIDER  openai | anthropic         (default: openai)
  RELAY_LLM_MODEL     model id                   (default: gpt-4o-mini / claude-opus-4-8)
  RELAY_LLM_API_KEY   your key                   (else OPENAI_API_KEY / ANTHROPIC_API_KEY)
  RELAY_LLM_BASE_URL  OpenAI-compatible base url (for Gemini / OpenRouter / Groq / Ollama / ...)

The "openai" provider is OpenAI-*compatible*: it covers OpenAI, Google Gemini
(via https://generativelanguage.googleapis.com/v1beta/openai/), OpenRouter, Groq,
Together, DeepSeek, Mistral, and local Ollama / LM Studio. Point RELAY_LLM_BASE_URL
at the provider and set RELAY_LLM_MODEL accordingly.

If no key is configured, callers fall back to fixtures/templates — the demo still runs.
"""

from __future__ import annotations

import json
import os
from typing import Type

from pydantic import BaseModel


class LLMNotConfigured(RuntimeError):
    pass


def provider() -> str:
    return os.environ.get("RELAY_LLM_PROVIDER", "openai").lower()


def api_key() -> str | None:
    explicit = os.environ.get("RELAY_LLM_API_KEY")
    if explicit:
        return explicit
    if provider() == "anthropic":
        return os.environ.get("ANTHROPIC_API_KEY")
    return os.environ.get("OPENAI_API_KEY")


def model() -> str:
    m = os.environ.get("RELAY_LLM_MODEL")
    if m:
        return m
    return "claude-opus-4-8" if provider() == "anthropic" else "gpt-4o-mini"


def base_url() -> str | None:
    return os.environ.get("RELAY_LLM_BASE_URL") or None


def is_configured() -> bool:
    return bool(api_key())


def describe() -> str:
    suffix = f" @ {base_url()}" if base_url() else ""
    return f"{provider()}:{model()}{suffix}"


def _require_key() -> str:
    key = api_key()
    if not key:
        raise LLMNotConfigured("No LLM key configured — set RELAY_LLM_API_KEY (or OPENAI_API_KEY).")
    return key


def complete_text(system: str, user: str) -> str:
    """Plain text completion."""
    key = _require_key()
    if provider() == "anthropic":
        import anthropic

        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(
            model=model(),
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip()

    import openai

    client = openai.OpenAI(api_key=key, base_url=base_url())
    resp = client.chat.completions.create(
        model=model(),
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    return (resp.choices[0].message.content or "").strip()


def extract_structured(
    system: str, user: str, schema: Type[BaseModel], *, max_attempts: int = 3
) -> BaseModel:
    """Structured output validated against `schema`, with self-correction retries.

    Robust against smaller / less-strict models (e.g. Gemini Flash): strips code
    fences and surrounding prose, and on a parse/validation failure feeds the error
    back to the model for a corrected attempt.
    """
    key = _require_key()
    if provider() == "anthropic":
        import anthropic

        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.parse(
            model=model(),
            max_tokens=8000,
            thinking={"type": "adaptive"},
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=schema,
        )
        if resp.parsed_output is None:
            raise RuntimeError(f"structured parse returned None (stop_reason={resp.stop_reason})")
        return resp.parsed_output

    import openai
    from pydantic import ValidationError

    client = openai.OpenAI(api_key=key, base_url=base_url())
    sys = (
        system
        + "\n\nReturn ONLY a single JSON object that conforms to this JSON Schema "
        "(no markdown fences, no prose):\n"
        + json.dumps(schema.model_json_schema())
    )
    messages = [{"role": "system", "content": sys}, {"role": "user", "content": user}]
    last_err: Exception | None = None
    for _ in range(max_attempts):
        text = _chat(client, messages)
        candidate = _extract_json_block(_strip_code_fence(text))
        try:
            return schema.model_validate_json(candidate)
        except (ValidationError, ValueError) as exc:
            last_err = exc
            # Feed the error back so the model can self-correct.
            messages = [
                {"role": "system", "content": sys},
                {"role": "user", "content": user},
                {"role": "assistant", "content": text},
                {
                    "role": "user",
                    "content": (
                        "That response did not parse against the schema. Error:\n"
                        f"{exc}\n\nReturn ONLY a corrected JSON object that matches the schema. "
                        "No prose, no markdown fences."
                    ),
                },
            ]
    raise RuntimeError(f"structured extraction failed after {max_attempts} attempts: {last_err}")


def _chat(client, messages) -> str:
    """Call chat.completions, degrading params for picky OpenAI-compatible providers."""
    last_err: Exception | None = None
    for extra in (
        {"response_format": {"type": "json_object"}, "temperature": 0},
        {"temperature": 0},
        {},
    ):
        try:
            resp = client.chat.completions.create(model=model(), messages=messages, **extra)
            return (resp.choices[0].message.content or "").strip()
        except Exception as exc:  # noqa: BLE001 - try a simpler param set
            last_err = exc
    raise last_err  # type: ignore[misc]


def _extract_json_block(t: str) -> str:
    """If the model wrapped JSON in prose, slice out the first {...last } object."""
    if t.startswith("{"):
        return t
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end != -1 and end > start:
        return t[start : end + 1]
    return t


def _strip_code_fence(t: str) -> str:
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        if t.endswith("```"):
            t = t.rsplit("```", 1)[0]
    return t.strip()
