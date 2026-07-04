"""Relay Reconciler — the riskiest hackathon component, built and tested first.

See reconciler/README.md. Public API:
    from reconciler import reconcile, reconcile_demo, ReconciliationResult
"""

import sys
from pathlib import Path

# Make the repo root importable so the provider-agnostic `llm` adapter resolves
# no matter how this package is imported.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from .models import Conflict, ExtractedItem, ReconciliationResult
from .reconciler import reconcile, reconcile_demo

__all__ = [
    "reconcile",
    "reconcile_demo",
    "ReconciliationResult",
    "ExtractedItem",
    "Conflict",
]
