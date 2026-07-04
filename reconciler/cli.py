"""Pretty demo runner: `python -m reconciler.cli`

Runs the Reconciler against the staged demo data and prints a human-readable
view — extracted items with their source citations, then conflicts by tier.
This is the screen you put in front of judges for WOW #1.
"""

from __future__ import annotations

import sys

from .reconciler import reconcile_demo


def main() -> int:
    print("Relay · Reconciler — running against staged demo data...\n")
    try:
        result = reconcile_demo()
    except Exception as exc:  # noqa: BLE001 - surface anything to the operator
        print(f"ERROR: {exc}", file=sys.stderr)
        print("(Is ANTHROPIC_API_KEY set?)", file=sys.stderr)
        return 1

    print("EXTRACTED CHANGES & ORDERS")
    print("=" * 60)
    for item in result.extracted:
        tag = item.kind.upper()
        sched = f"  [{item.schedule}]" if item.schedule else ""
        due = f"  (due before {item.due_before})" if item.due_before else ""
        print(f"  {item.action:6} {tag:11} {item.name}{sched}{due}")
        print(f"         prescriber: {item.prescriber}")
        print(f'         source: {item.source_document} — "{item.source_quote}"')
        print()

    print("CONFLICTS")
    print("=" * 60)
    for c in sorted(result.conflicts, key=lambda x: x.tier):
        print(f"  [tier {c.tier} · {c.severity}] {c.id}")
        print(f"    {c.statement}")
        print(f"    -> {c.recommended_action}")
        print()

    print(f"{len(result.extracted)} item(s), {len(result.conflicts)} conflict(s).")
    print("Run `python -m reconciler.evaluate` to check against the ground-truth fixture.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
