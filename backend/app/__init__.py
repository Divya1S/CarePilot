"""Relay backend package.

Ensure the repo root is importable so `import reconciler` works from any
submodule, regardless of how the app is launched. Runs before any submodule body.
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
