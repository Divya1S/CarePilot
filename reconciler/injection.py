"""Prompt-injection / exfiltration detection.

Uploaded documents (and the messages drafted from them) are the attack surface:
a poisoned PDF could try to make the agent follow embedded instructions or
exfiltrate data. Defense is layered:
  1. The Reconciler treats document text as DATA, not instructions (prompts.py
     + the UNTRUSTED markers in reconciler.py).
  2. Structured output gives the model no channel to take arbitrary actions —
     it can only emit extracted items + conflicts.
  3. These scans flag injection on ingest (a visible warning) and block
     exfiltration in drafts (fall back to a safe template).
"""

from __future__ import annotations

import re

# Imperative-override phrases typical of prompt injection. Tuned for precision so
# real after-visit summaries don't trip them.
INJECTION_PATTERNS = [
    r"\bignore (all|any|the|your|these|previous|prior|above)\b.{0,40}\binstruction",
    r"\bdisregard (all|any|the|your|these|previous|prior|above)\b.{0,40}\b(instruction|rule|prompt)",
    r"\b(system|developer)[-\s]?prompt\b",
    r"\byou are now\b",
    r"\binstead[, ]+(send|email|forward|output|print|reply|add|include|ignore)\b",
    r"\bdo not (tell|inform|mention|flag|report|warn)\b",
    r"\bprint (your|the) (system )?(prompt|instructions)\b",
    r"\bact as (an? )?(ai|assistant|system|agent|model|admin)\b",
    r"\boverride\b.{0,20}\b(safety|policy|rule|instruction|guardrail)",
]

# Exfiltration markers — an after-visit reconciliation or a pharmacy/PCP
# confirmation should contain no email addresses or URLs (real recipients are
# named, not addressed).
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(r"\bhttps?://\S+", re.IGNORECASE)


def scan_injection(text: str) -> list[str]:
    """Return injected-instruction markers found in `text` (empty == clean)."""
    low = text.lower()
    hits: list[str] = []
    for pat in INJECTION_PATTERNS:
        m = re.search(pat, low)
        if m:
            hits.append(m.group(0).strip())
    return hits


def scan_exfiltration(text: str) -> list[str]:
    """Return exfiltration markers (emails / URLs) found in `text`."""
    hits: list[str] = []
    for addr in EMAIL_RE.findall(text):
        hits.append(f"email address: {addr}")
    for url in URL_RE.findall(text):
        hits.append(f"url: {url}")
    return hits
