"""Recoverable offline comparisons for external tool-using agents.

This stores computed results, never dispatches equipment or changes runtime
controls. The version token detects ordinary policy/dataset cache invalidation;
it is not a signed content attestation or a live sensor snapshot identifier.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from app.core.config import settings
from app.services.dispatch_simulator import DispatchSimulator
from app.services.kpi_engine import KpiEngine


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def source_context():
    return {
        "source_version": DispatchSimulator._policy_source_signature(),
        "version_basis": "policy_and_dataset_file_metadata_invalidation_token",
        "scope": "public offline energy dataset and selected calculation policy; not current live telemetry",
        "production_authority": False,
    }


class ComparisonConflict(ValueError):
    pass


class ComparisonStore:
    def __init__(self, path=None):
        self.path = Path(
            path or Path(settings.runtime_state_path).parent / "agent-comparisons.sqlite"
        )

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("""CREATE TABLE IF NOT EXISTS comparisons (
            owner TEXT NOT NULL, request_id TEXT NOT NULL, payload_hash TEXT NOT NULL,
            receipt_json TEXT NOT NULL, PRIMARY KEY(owner, request_id))""")
        connection.commit()
        return connection

    def get(self, owner, request_id):
        connection = self.connect()
        try:
            row = connection.execute(
                "SELECT receipt_json FROM comparisons WHERE owner=? AND request_id=?",
                (owner, request_id),
            ).fetchone()
            if row is None:
                return None
            receipt = json.loads(row["receipt_json"])
            checksum = receipt.pop("receipt_sha256")
            if digest(receipt) != checksum:
                raise ValueError("persisted comparison receipt checksum mismatch")
            return {**receipt, "receipt_sha256": checksum}
        finally:
            connection.close()

    def compare(self, owner, payload):
        payload_hash = digest(payload)
        connection = self.connect()
        try:
            # Serializes duplicate requests across threads/processes, including
            # computation. If a pure calculation crashes, no partial result is
            # published; a completed transaction survives response loss.
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM comparisons WHERE owner=? AND request_id=?",
                (owner, payload["request_id"]),
            ).fetchone()
            if existing:
                if existing["payload_hash"] != payload_hash:
                    raise ComparisonConflict("request_id already bound to different parameters")
                receipt = json.loads(existing["receipt_json"])
                expected_hash = receipt.pop("receipt_sha256")
                if digest(receipt) != expected_hash:
                    raise ValueError("persisted comparison receipt checksum mismatch")
                return {"duplicate": True, "receipt": {**receipt, "receipt_sha256": expected_hash}}
            before = source_context()
            if before["source_version"] != payload["expected_source_version"]:
                raise ComparisonConflict(
                    "source version changed; reread source context before submitting a new request"
                )
            alternatives = []
            for green in [payload["baseline_green_preference"], payload["green_preference"]]:
                raw = (
                    KpiEngine()
                    .build_snapshot(
                        green_preference=green, carbon_price=payload["carbon_price_cny_per_ton"]
                    )
                    .model_dump(mode="json")
                )
                if raw.get("green_preference") != round(green, 6) or raw.get(
                    "carbon_market", {}
                ).get("carbon_price_cny_per_ton") != round(payload["carbon_price_cny_per_ton"], 6):
                    raise ValueError("calculation did not echo requested parameters")
                if raw.get("governance", {}).get("production_dispatch_enabled") is not False:
                    raise ValueError("offline calculation authority missing")
                alternatives.append(
                    {
                        "parameters": {
                            "green": green,
                            "carbon": payload["carbon_price_cny_per_ton"],
                        },
                        "raw": raw,
                    }
                )
            after = source_context()
            if before != after:
                raise ComparisonConflict(
                    "source version changed during comparison; result not published"
                )
            hashes = [
                a["raw"].get("rl_environment", {}).get("dataset_sha256") for a in alternatives
            ]
            if not hashes[0] or hashes[0] != hashes[1]:
                raise ComparisonConflict(
                    "alternative calculations used different or missing datasets"
                )
            receipt = {
                "schema": "agent-energy-comparison.v1",
                "request_id": payload["request_id"],
                "request_sha256": payload_hash,
                "status": "completed",
                "parameters": payload,
                "source_context": before,
                "dataset_sha256": hashes[0],
                "alternatives": alternatives,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "production_authority": False,
            }
            receipt["receipt_sha256"] = digest(receipt)
            connection.execute(
                "INSERT INTO comparisons VALUES(?,?,?,?)",
                (
                    owner,
                    payload["request_id"],
                    payload_hash,
                    json.dumps(receipt, ensure_ascii=False, allow_nan=False),
                ),
            )
            connection.commit()
            return {"duplicate": False, "receipt": receipt}
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
