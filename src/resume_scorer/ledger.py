"""MongoDB persistence for Textkernel scorer usage (credits per Run)."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from pymongo import MongoClient
from pymongo.collection import Collection

from resume_scorer.models import ScoreResult, TxCallInfo

_COLLECTION_NAME = "scorer_usage"


def _mongo_uri_from_env() -> str:
    return os.environ["MONGODB_URI"].strip()


def _database_name_from_env() -> str:
    return (os.environ.get("RESUME_SCORER_DB") or "resume_scorer").strip()


class ScorerLedgerMongoService:
    """Read/write scorer usage documents in a database separate from Anthropic spend."""

    def __init__(self, collection: Collection) -> None:
        self._coll = collection
        self._ensure_indexes()

    @classmethod
    def from_uri(cls, uri: str, database: str | None = None) -> ScorerLedgerMongoService:
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        dbname = (database or _database_name_from_env()).strip() or "resume_scorer"
        return cls(client[dbname][_COLLECTION_NAME])

    @classmethod
    def from_env(cls) -> ScorerLedgerMongoService:
        return cls.from_uri(_mongo_uri_from_env(), _database_name_from_env())

    @classmethod
    def from_client(cls, client: MongoClient, database: str) -> ScorerLedgerMongoService:
        return cls(client[database][_COLLECTION_NAME])

    def _ensure_indexes(self) -> None:
        self._coll.create_index([("ts", -1)])

    def add_run(
        self,
        *,
        credits_used: float,
        credits_remaining: float | None,
        transaction_ids: list[str],
        calls: list[TxCallInfo],
        source: str = "app",
        succeeded: bool = True,
        error: str | None = None,
    ) -> None:
        """Insert one document per user Run (including partial billed failures)."""
        if credits_used <= 0 and not calls:
            return
        doc: dict[str, Any] = {
            "ts": datetime.now(timezone.utc),
            "credits_used": float(credits_used),
            "credits_remaining": credits_remaining,
            "transaction_ids": list(transaction_ids),
            "calls": [
                {
                    "endpoint": c.endpoint,
                    "transaction_cost": c.transaction_cost,
                    "credits_remaining": c.credits_remaining,
                    "transaction_id": c.transaction_id,
                    "code": c.code,
                }
                for c in calls
            ],
            "source": source,
            "succeeded": succeeded,
        }
        if error:
            doc["error"] = error
        self._coll.insert_one(doc)

    def add_score_result(self, result: ScoreResult) -> None:
        self.add_run(
            credits_used=result.credits_used,
            credits_remaining=result.credits_remaining,
            transaction_ids=list(result.transaction_ids),
            calls=list(result.calls),
            succeeded=True,
        )

    def get_total_credits(self) -> float:
        """Sum ``credits_used`` across all recorded Runs."""
        pipeline = [
            {
                "$match": {
                    "$or": [
                        {"credits_used": {"$type": "double"}},
                        {"credits_used": {"$type": "int"}},
                        {"credits_used": {"$type": "long"}},
                        {"credits_used": {"$type": "decimal"}},
                    ]
                }
            },
            {"$group": {"_id": None, "total": {"$sum": "$credits_used"}}},
        ]
        agg = list(self._coll.aggregate(pipeline))
        if not agg:
            return 0.0
        return float(agg[0]["total"])

    def get_latest_credits_remaining(self) -> float | None:
        """Return ``credits_remaining`` from the newest document that has it."""
        doc = self._coll.find_one(
            {"credits_remaining": {"$ne": None}},
            sort=[("ts", -1), ("_id", -1)],
        )
        if not doc:
            return None
        try:
            return float(doc["credits_remaining"])
        except (TypeError, ValueError, KeyError):
            return None

    def ping(self) -> bool:
        try:
            self._coll.database.client.admin.command("ping")
            return True
        except Exception:
            return False
