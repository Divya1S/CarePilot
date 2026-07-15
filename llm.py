"""Provider-agnostic LLM adapter — so CarePilot runs against whatever key you have.

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

Observability: every call is timed, token-counted, and reported — one log line via
the "carepilot.llm" logger, plus an optional recorder hook (`set_recorder`) that the
backend uses to persist a per-call ledger. Only metadata is recorded (purpose label,
model, latency, attempts, token counts, ok/error) — never prompt or response text,
so the ledger stays PII-free by construction.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Callable, Type

from pydantic import BaseModel

logger = logging.getLogger("carepilot.llm")
if not logger.handlers:  # standalone runs (eval corpus) still get visible lines
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)
    logger.propagate = False


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


# ---------------------------------------------------------------------------
# Call ledger — metadata only, never prompt/response text.
# ---------------------------------------------------------------------------

_recorder: Callable[[dict], None] | None = None


def set_recorder(fn: Callable[[dict], None] | None) -> Callable[[dict], None] | None:
    """Register a per-call recorder (the backend persists these to SQLite).

    Returns the previous recorder so callers can restore it.
    """
    global _recorder
    prev, _recorder = _recorder, fn
    return prev


def _record(purpose: str, started: float, attempts: int, ptok: int, ctok: int,
            ok: bool, error: str | None = None) -> None:
    rec = {
        "purpose": purpose,
        "provider": provider(),
        "model": model(),
        "latency_ms": int((time.monotonic() - started) * 1000),
        "attempts": attempts,
        "prompt_tokens": ptok,
        "completion_tokens": ctok,
        "ok": ok,
        "error": (error or "")[:300],
    }
    logger.info(
        "%s %s ok=%s %dms attempts=%d tokens=%d/%d%s",
        rec["purpose"], rec["model"], rec["ok"], rec["latency_ms"],
        rec["attempts"], rec["prompt_tokens"], rec["completion_tokens"],
        f" error={rec['error']}" if error else "",
    )
    if _recorder is not None:
        try:
            _recorder(rec)
        except Exception as exc:  # noqa: BLE001 - telemetry must never break a call
            logger.warning("llm recorder failed: %s", exc)


def _openai_usage(resp) -> tuple[int, int]:
    u = getattr(resp, "usage", None)
    return (getattr(u, "prompt_tokens", 0) or 0, getattr(u, "completion_tokens", 0) or 0)


def _anthropic_usage(resp) -> tuple[int, int]:
    u = getattr(resp, "usage", None)
    return (getattr(u, "input_tokens", 0) or 0, getattr(u, "output_tokens", 0) or 0)


# ---------------------------------------------------------------------------
# Public calls
# ---------------------------------------------------------------------------

def complete_text(system: str, user: str, *, purpose: str = "llm") -> str:
    """Plain text completion."""
    key = _require_key()
    started = time.monotonic()
    try:
        if provider() == "anthropic":
            import anthropic

            client = anthropic.Anthropic(api_key=key)
            resp = client.messages.create(
                model=model(),
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            ptok, ctok = _anthropic_usage(resp)
            text = "".join(b.text for b in resp.content if b.type == "text").strip()
        else:
            import openai

            client = openai.OpenAI(api_key=key, base_url=base_url())
            resp = client.chat.completions.create(
                model=model(),
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            )
            ptok, ctok = _openai_usage(resp)
            text = (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        _record(purpose, started, 1, 0, 0, ok=False, error=str(exc))
        raise
    _record(purpose, started, 1, ptok, ctok, ok=True)
    return text


def extract_structured(
    system: str, user: str, schema: Type[BaseModel], *, max_attempts: int = 3, purpose: str = "llm"
) -> BaseModel:
    """Structured output validated against `schema`, with self-correction retries.

    Robust against smaller / less-strict models (e.g. Gemini Flash): strips code
    fences and surrounding prose, and on a parse/validation failure feeds the error
    back to the model for a corrected attempt.
    """
    key = _require_key()
    started = time.monotonic()

    if provider() == "anthropic":
        import anthropic

        client = anthropic.Anthropic(api_key=key)
        try:
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
        except Exception as exc:
            _record(purpose, started, 1, 0, 0, ok=False, error=str(exc))
            raise
        ptok, ctok = _anthropic_usage(resp)
        _record(purpose, started, 1, ptok, ctok, ok=True)
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
    ptok = ctok = 0
    for attempt in range(1, max_attempts + 1):
        try:
            text, usage = _chat(client, messages)
        except Exception as exc:
            _record(purpose, started, attempt, ptok, ctok, ok=False, error=str(exc))
            raise
        ptok += usage[0]
        ctok += usage[1]
        candidate = _extract_json_block(_strip_code_fence(text))
        try:
            result = schema.model_validate_json(candidate)
            _record(purpose, started, attempt, ptok, ctok, ok=True)
            return result
        except (ValidationError, ValueError) as exc:
            last_err = exc
            logger.info("structured parse failed (attempt %d/%d): %s", attempt, max_attempts, str(exc)[:160])
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
    _record(purpose, started, max_attempts, ptok, ctok, ok=False,
            error=f"failed after {max_attempts} attempts: {last_err}")
    raise RuntimeError(f"structured extraction failed after {max_attempts} attempts: {last_err}")


def _chat(client, messages) -> tuple[str, tuple[int, int]]:
    """Call chat.completions, degrading params for picky OpenAI-compatible providers.

    Returns (text, (prompt_tokens, completion_tokens)).
    """
    last_err: Exception | None = None
    for extra in (
        {"response_format": {"type": "json_object"}, "temperature": 0},
        {"temperature": 0},
        {},
    ):
        try:
            resp = client.chat.completions.create(model=model(), messages=messages, **extra)
            return (resp.choices[0].message.content or "").strip(), _openai_usage(resp)
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
