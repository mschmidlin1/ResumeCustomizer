"""Append-only JSON ledger of estimated API costs per customization run."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LEDGER_VERSION = 1
_LEDGER_FILENAME = "customization_cost_ledger.json"


@dataclass(frozen=True, slots=True)
class CostLedgerEntry:
    """One persisted customization cost row."""

    ts: str
    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float | None


def default_ledger_path() -> Path:
    """Path to the ledger file under ``cost_data/`` at the repo root."""
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "cost_data" / _LEDGER_FILENAME


def load_ledger(path: Path) -> list[CostLedgerEntry]:
    """Load ledger entries from ``path``; return empty list if missing or invalid."""
    if not path.is_file():
        return []
    try:
        raw_text = path.read_text(encoding="utf-8")
        data: Any = json.loads(raw_text)
    except (OSError, json.JSONDecodeError):
        return []
    entries_raw = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries_raw, list):
        return []
    out: list[CostLedgerEntry] = []
    for row in entries_raw:
        if not isinstance(row, dict):
            continue
        try:
            ts = str(row["ts"])
            model = str(row["model"])
            input_tokens = int(row["input_tokens"])
            output_tokens = int(row["output_tokens"])
        except (KeyError, TypeError, ValueError):
            continue
        cost_raw = row.get("estimated_cost_usd")
        estimated: float | None
        if cost_raw is None:
            estimated = None
        else:
            try:
                estimated = float(cost_raw)
            except (TypeError, ValueError):
                continue
        out.append(
            CostLedgerEntry(
                ts=ts,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_usd=estimated,
            )
        )
    return out


def total_estimated_cost_usd(entries: list[CostLedgerEntry]) -> float:
    """Sum stored estimates; entries with ``None`` cost are skipped."""
    total = 0.0
    for e in entries:
        if e.estimated_cost_usd is not None:
            total += e.estimated_cost_usd
    return total


def append_entry(path: Path, entry: CostLedgerEntry) -> None:
    """Append one entry to the ledger file (read-modify-write)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = load_ledger(path)
    entries.append(entry)
    payload = {
        "version": _LEDGER_VERSION,
        "entries": [_entry_to_jsonable(e) for e in entries],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _entry_to_jsonable(entry: CostLedgerEntry) -> dict[str, Any]:
    d = asdict(entry)
    return d


def ledger_entry_now(
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    estimated_cost_usd: float | None,
) -> CostLedgerEntry:
    """Build a ledger row with the current UTC timestamp."""
    ts = datetime.now(timezone.utc).isoformat()
    return CostLedgerEntry(
        ts=ts,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_usd=estimated_cost_usd,
    )
