"""Test package: ensures ``src`` is on ``sys.path`` when running ``unittest`` from repo root."""

from __future__ import annotations

import sys
from pathlib import Path

_SRC: Path = Path(__file__).resolve().parent.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
