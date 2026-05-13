"""MongoDB persistence for customization cost ledger rows."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from resume_customizer.cost_ledger import CostLedgerEntry

_COLLECTION_NAME = "customization_cost_ledger"


def _mongo_uri_from_env() -> str | None:
    v = (os.environ.get("MONGODB_URI") or os.environ.get("MONGO_URI") or "").strip()
    return v or None


def _database_name_from_env() -> str:
    return (os.environ.get("RESUME_CUSTOMIZER_DB") or "resume_customizer").strip()


def _ledger_dedupe_key(entry: CostLedgerEntry) -> str:
    payload: dict[str, Any] = {
        "ts": entry.ts,
        "model": entry.model,
        "input_tokens": entry.input_tokens,
        "output_tokens": entry.output_tokens,
        "estimated_cost_usd": entry.estimated_cost_usd,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _parse_ledger_ts(ts: str) -> datetime:
    normalized = ts.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class CostLedgerMongoService:
    """Read/write cost ledger documents in MongoDB."""

    def __init__(self, collection: Collection) -> None:
        self._coll = collection
        self._ensure_indexes()

    @classmethod
    def from_uri(cls, uri: str, database: str | None = None) -> CostLedgerMongoService:
        """Connect with explicit URI and database name (used by Streamlit cache and tests)."""
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        dbname = (database or _database_name_from_env()).strip() or "resume_customizer"
        coll = client[dbname][_COLLECTION_NAME]
        return cls(coll)

    @classmethod
    def from_env(cls) -> CostLedgerMongoService | None:
        uri = _mongo_uri_from_env()
        if not uri:
            return None
        return cls.from_uri(uri, _database_name_from_env())

    @classmethod
    def from_client(cls, client: MongoClient, database: str) -> CostLedgerMongoService:
        """Build a service for tests or custom wiring (same collection name)."""
        coll = client[database][_COLLECTION_NAME]
        return cls(coll)

    def _ensure_indexes(self) -> None:
        self._coll.create_index("dedupe_key", unique=True)
        self._coll.create_index([("ts", -1)])

    def add_document(self, entry: CostLedgerEntry, *, source: str = "app") -> bool:
        """Insert one ledger row. Returns False if duplicate ``dedupe_key``."""
        doc = {
            "dedupe_key": _ledger_dedupe_key(entry),
            "ts": _parse_ledger_ts(entry.ts),
            "model": entry.model,
            "input_tokens": entry.input_tokens,
            "output_tokens": entry.output_tokens,
            "estimated_cost_usd": entry.estimated_cost_usd,
            "source": source,
        }
        try:
            self._coll.insert_one(doc)
            return True
        except DuplicateKeyError:
            return False

    def get_total(self) -> float:
        """Sum ``estimated_cost_usd`` for documents with a numeric cost (skips null / missing)."""
        pipeline = [
            {"$match": {"estimated_cost_usd": {"$type": ["double", "int", "long", "decimal"]}}},
            {"$group": {"_id": None, "total": {"$sum": "$estimated_cost_usd"}}},
        ]
        agg = list(self._coll.aggregate(pipeline))
        if not agg:
            return 0.0
        return float(agg[0]["total"])

    def import_many(
        self, entries: Iterable[CostLedgerEntry], *, source: str = "json_import"
    ) -> tuple[int, int]:
        """Insert many rows; duplicates are skipped. Returns ``(inserted, skipped_duplicates)``."""
        inserted = 0
        skipped = 0
        for entry in entries:
            if self.add_document(entry, source=source):
                inserted += 1
            else:
                skipped += 1
        return inserted, skipped

    def ping(self) -> bool:
        """Return True if the server responds to ``ping``."""
        try:
            self._coll.database.client.admin.command("ping")
            return True
        except Exception:
            return False
