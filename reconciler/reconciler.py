"""The Reconciler — the riskiest component, built first.

Turns messy after-visit documents (PDF or markdown) + a canonical med list into
a structured, non-hallucinated diff with source citations and coordination
conflicts. Single structured LLM call through the provider-agnostic `llm` adapter
(works with OpenAI / Gemini / OpenRouter / Anthropic / local), not an agent loop —
deterministic and testable, which is what the trust pitch needs.

Requires an LLM key configured for the `llm` adapter (see ../llm.py).
"""

from __future__ import annotations

import json
from pathlib import Path

from .injection import scan_injection
from .models import ReconciliationResult
from .prompts import SYSTEM_PROMPT
from .redact import redact, rehydrate_obj
from .safety import scan_forbidden

REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_DATA = REPO_ROOT / "demo-data"


def _safety_text(result: ReconciliationResult) -> str:
    """The model's OWN assertions — excludes source_quote.

    A source_quote is verbatim from the clinical document; quoting "the patient
    asked about an interaction" is not the agent *claiming* an interaction. We
    scan only the agent's generated language (conflict statements, recommended
    actions, med names, schedules).
    """
    parts: list[str] = []
    for it in result.extracted:
        parts += [it.name, it.schedule or ""]
    for c in result.conflicts:
        parts += [c.statement, c.recommended_action]
    return "\n".join(parts)


def _assert_safe(result: ReconciliationResult) -> None:
    """Runtime guard: the live model must never surface a clinical assertion.

    On a violation we raise — callers (e.g. the backend) fall back to the safe
    fixture rather than show a forbidden claim.
    """
    hits = scan_forbidden(_safety_text(result))
    if hits:
        raise RuntimeError(f"reconciliation produced forbidden clinical language: {hits}")


def _document_text(path: Path) -> str:
    """Return the text of a source document. PDFs are extracted with pypdf."""
    if path.suffix.lower() == ".pdf":
        try:
            import pypdf
        except ImportError as exc:  # pragma: no cover - environment-dependent
            raise RuntimeError(
                f"Reading {path.name} needs pypdf (`pip install pypdf`), "
                "or pass the markdown source instead."
            ) from exc
        reader = pypdf.PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    return path.read_text(encoding="utf-8")


def _build_prompt(document_paths: list[Path], med_list_text: str) -> str:
    parts: list[str] = []
    for p in document_paths:
        # Explicit untrusted-data markers so injected instructions are treated as content.
        parts.append(
            f"<<<BEGIN UNTRUSTED DOCUMENT: {p.name}>>>\n{_document_text(p)}\n<<<END UNTRUSTED DOCUMENT>>>"
        )
    parts.append(
        "=== Canonical medication list (state BEFORE these documents) ===\n" + med_list_text
    )
    parts.append(
        "Reconcile the untrusted documents above against this canonical list. Extract every "
        "medication change and lab order with a verbatim source_quote, then surface the "
        "coordination conflicts. Follow your hard rules and SECURITY rules exactly."
    )
    return "\n\n".join(parts)


def scan_documents_for_injection(document_paths) -> list[str]:
    """Flag injected-instruction markers in the documents (for a visible warning)."""
    hits: list[str] = []
    for p in document_paths:
        for h in scan_injection(_document_text(Path(p))):
            hits.append(f"{Path(p).name}: “{h}”")
    return hits


def reconcile(
    document_paths, med_list_path, *, enforce_safety: bool = True, redact_terms=None
) -> ReconciliationResult:
    """Run the reconciliation. Returns a validated ReconciliationResult.

    PII (names in `redact_terms` + MRN/DOB/IDs/SSN/phone/email) is redacted before
    the prompt reaches the LLM and rehydrated in the output. enforce_safety=True
    (default) raises if the output contains a clinical claim; the eval corpus
    passes False so it can classify safety failures itself.
    """
    import llm  # provider-agnostic adapter (repo root)

    med_list = Path(med_list_path).read_text(encoding="utf-8")
    prompt = _build_prompt([Path(p) for p in document_paths], med_list)
    redacted_prompt, mapping = redact(prompt, names=redact_terms)
    result = llm.extract_structured(SYSTEM_PROMPT, redacted_prompt, ReconciliationResult, purpose="reconcile")
    if mapping:
        result = ReconciliationResult.model_validate(rehydrate_obj(result.model_dump(), mapping))
    if enforce_safety:
        _assert_safe(result)
    return result


def reconcile_demo() -> ReconciliationResult:
    """Run against the staged demo dataset (PDFs if pypdf is available, else markdown)."""
    pdf_dir = DEMO_DATA / "documentspdf"
    md_dir = DEMO_DATA / "documents"
    names = ["neurology-after-visit-summary", "endocrinology-portal-note"]

    try:
        import pypdf  # noqa: F401

        have_pdf = True
    except ImportError:
        have_pdf = False

    docs: list[Path] = []
    for n in names:
        pdf = pdf_dir / f"{n}.pdf"
        docs.append(pdf if (have_pdf and pdf.exists()) else md_dir / f"{n}.md")

    return reconcile(docs, DEMO_DATA / "med-list.json")


if __name__ == "__main__":
    print(json.dumps(reconcile_demo().model_dump(), indent=2))
