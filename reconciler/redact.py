"""PII minimization — redact sensitive identifiers before they reach the LLM.

The provider (Gemini/OpenAI/…) should never receive raw patient identifiers.
`redact()` replaces detected PII with stable placeholder tokens and returns a
mapping; `rehydrate()` restores the real values in the model's output so humans
still see them. Medication names, doses, and schedules are never touched.

Detection is label/pattern based (MRN, DOB, member/insurance IDs, SSN, phone,
email) plus exact-match for known names the caller passes in. This is data
minimization, not a guarantee against every possible identifier — it removes the
common, high-value ones from prompts and provider logs.
"""

from __future__ import annotations

import re

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")

# Labeled identifiers — capture the value after the label. The value must contain
# a digit so prose like "group therapy" isn't mistaken for an ID.
_VAL = r"([A-Za-z0-9\-•]*\d[A-Za-z0-9\-•]*)"
LABELED = [
    ("MRN", re.compile(r"\b(MRN)[:#]?\s*" + _VAL, re.IGNORECASE)),
    ("DOB", re.compile(r"\b(DOB|date of birth)[:#]?\s*(\d{1,4}[/\-]\d{1,2}[/\-]\d{1,4})", re.IGNORECASE)),
    ("ID", re.compile(
        r"\b(member id|insurance id|subscriber id|policy(?: number)?|group(?: number)?|rx ?bin)[:#]?\s*" + _VAL,
        re.IGNORECASE,
    )),
]


def redact(text: str, names: list[str] | None = None) -> tuple[str, dict[str, str]]:
    """Return (redacted_text, {token: original})."""
    mapping: dict[str, str] = {}
    counters: dict[str, int] = {}

    def tok(kind: str, value: str) -> str:
        for t, v in mapping.items():  # reuse a token for a repeated value
            if v == value:
                return t
        counters[kind] = counters.get(kind, 0) + 1
        t = f"[{kind}_{counters[kind]}]"
        mapping[t] = value
        return t

    # Known names first (full name + its parts → the same token).
    for name in sorted([n for n in (names or []) if n], key=len, reverse=True):
        parts = sorted({name, *[p for p in name.split() if len(p) > 2]}, key=len, reverse=True)
        for part in parts:
            pat = re.compile(r"\b" + re.escape(part) + r"\b")
            if pat.search(text):
                text = pat.sub(tok("NAME", name), text)

    # Labeled identifiers — replace only the value, preserving the label + separator.
    def _labeled_sub(m, kind):
        whole = m.group(0)
        s, e = m.start(2) - m.start(0), m.end(2) - m.start(0)
        return whole[:s] + tok(kind, m.group(2)) + whole[e:]

    for kind, rx in LABELED:
        text = rx.sub(lambda m, k=kind: _labeled_sub(m, k), text)

    # Standalone patterns.
    text = EMAIL_RE.sub(lambda m: tok("EMAIL", m.group(0)), text)
    text = SSN_RE.sub(lambda m: tok("SSN", m.group(0)), text)
    text = PHONE_RE.sub(lambda m: tok("PHONE", m.group(0)), text)
    return text, mapping


def rehydrate(text: str, mapping: dict[str, str]) -> str:
    for token, original in mapping.items():
        text = text.replace(token, original)
    return text


def rehydrate_obj(obj, mapping: dict[str, str]):
    """Recursively rehydrate every string in a dict/list structure."""
    if isinstance(obj, str):
        return rehydrate(obj, mapping)
    if isinstance(obj, list):
        return [rehydrate_obj(x, mapping) for x in obj]
    if isinstance(obj, dict):
        return {k: rehydrate_obj(v, mapping) for k, v in obj.items()}
    return obj
