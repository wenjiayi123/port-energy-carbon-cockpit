"""New durable envelope around legacy offline receipts; legacy code is unchanged."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from app.core.config import settings
from app.rl.dataset import PortDataset
from app.services.agent_comparisons import ComparisonConflict, ComparisonStore, digest
from app.services.agent_comparisons import source_context as legacy_context
from app.services.expert_energy_evidence import project_trial


def source_context():
    root = Path(__file__).resolve().parents[1]
    names = [
        "services/expert_energy_evidence.py",
        "services/expert_comparisons.py",
        "services/agent_comparisons.py",
        "services/dispatch_simulator.py",
        "services/kpi_engine.py",
        "rl/environment.py",
        "rl/dataset.py",
        "schemas/dashboard.py",
    ]
    body = {
        "schema": "expert-energy-source.v1",
        "legacy_context": legacy_context(),
        "implementation_sha256": {
            n: hashlib.sha256((root / n).read_bytes()).hexdigest() for n in names
        },
        "scope": "versioned offline calculation; no live runtime telemetry",
        "production_authority": False,
    }
    return {**body, "source_version": digest(body)}


class ExpertComparisonStore:
    def __init__(self, path=None):
        self.path = Path(
            path or Path(settings.runtime_state_path).parent / "expert-comparisons.sqlite"
        )
        self.legacy = ComparisonStore(self.path.with_suffix(".native.sqlite"))

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=60)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS receipts (owner TEXT, request_id TEXT, payload_hash TEXT, body TEXT, PRIMARY KEY(owner, request_id))"
        )
        connection.commit()
        return connection

    @staticmethod
    def decode(text):
        receipt = json.loads(text)
        checksum = receipt.pop("receipt_sha256")
        if digest(receipt) != checksum:
            raise ValueError("expert receipt checksum mismatch")
        return {**receipt, "receipt_sha256": checksum}

    def get(self, owner, request_id):
        connection = self.connect()
        try:
            row = connection.execute(
                "SELECT body FROM receipts WHERE owner=? AND request_id=?", (owner, request_id)
            ).fetchone()
            return self.decode(row["body"]) if row else None
        finally:
            connection.close()

    def compare(self, owner, payload):
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM receipts WHERE owner=? AND request_id=?",
                (owner, payload["request_id"]),
            ).fetchone()
            if row:
                if row["payload_hash"] != digest(payload):
                    raise ComparisonConflict("request_id already bound to different parameters")
                return {"duplicate": True, "receipt": self.decode(row["body"])}
            before = source_context()
            if payload["expected_source_version"] != before["source_version"]:
                raise ComparisonConflict("source version changed; reread context")
            legacy_payload = {
                **payload,
                "expected_source_version": before["legacy_context"]["source_version"],
            }
            native = self.legacy.compare(owner, legacy_payload)["receipt"]
            alternatives = []
            for entry in native["alternatives"]:
                raw = entry["raw"]
                dataset = PortDataset.load(raw["rl_environment"]["dataset_path"])
                facts = project_trial(raw, dataset)
                alternatives.append({"parameters": entry["parameters"], "facts": facts})
            if source_context() != before:
                raise ComparisonConflict("source changed during calculation")
            receipt = {
                "schema": "expert-energy-comparison.v1",
                "request_id": payload["request_id"],
                "request_sha256": digest(payload),
                "parameters": payload,
                "source_context": before,
                "native_receipt": native,
                "alternatives": alternatives,
                "status": "completed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "production_authority": False,
            }
            receipt["receipt_sha256"] = digest(receipt)
            connection.execute(
                "INSERT INTO receipts VALUES(?,?,?,?)",
                (
                    owner,
                    payload["request_id"],
                    digest(payload),
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
