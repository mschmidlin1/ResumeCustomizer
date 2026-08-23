#!/usr/bin/env python3
"""CLI wrapper: import JSON cost ledger into MongoDB (requires ``MONGODB_URI``).

Run from the repo root with ``PYTHONPATH=src`` (or an installed package)::

    python scripts/import_ledger_to_mongo.py
    python scripts/import_ledger_to_mongo.py --ledger-path path/to/ledger.json
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from resume_customizer.import_ledger_to_mongo import main

if __name__ == "__main__":
    raise SystemExit(main())
