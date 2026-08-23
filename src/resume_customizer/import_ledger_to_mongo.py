"""CLI: import existing JSON cost ledger into MongoDB (requires ``MONGODB_URI``).

Prefer the thin wrapper at ``scripts/import_ledger_to_mongo.py`` from the repo root.
This module remains importable as ``python -m resume_customizer.import_ledger_to_mongo``
when ``src`` is on ``PYTHONPATH``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from resume_customizer.cost_ledger import default_ledger_path, load_ledger
from resume_customizer.cost_ledger_mongo import CostLedgerMongoService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import customization_cost_ledger.json into MongoDB.")
    parser.add_argument(
        "--ledger-path",
        type=Path,
        default=None,
        help="Path to customization_cost_ledger.json (default: repo cost_data file).",
    )
    args = parser.parse_args(argv)

    svc = CostLedgerMongoService.from_env()

    path = args.ledger_path if args.ledger_path is not None else default_ledger_path()
    entries = load_ledger(path)
    inserted, skipped = svc.import_many(entries, source="json_import")
    print(f"inserted={inserted} skipped_duplicates={skipped} source_file={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
