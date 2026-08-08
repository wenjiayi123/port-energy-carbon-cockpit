from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
from pathlib import Path
import threading
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import settings


SNAPSHOT_SCHEMA_VERSION = "port-snapshot.v1"
DATA_ADAPTER_CONTRACTS: dict[str, dict[str, Any]] = {
    "terminal_operating_system": {
        "max_age_seconds": 300,
        "required_fields": ("loaded_import_teu", "loaded_export_teu", "total_teu"),
    },
    "energy_management_system": {
        "max_age_seconds": 120,
        "required_fields": (
            "grid_carbon_kg_per_kwh",
            "electricity_price_per_kwh",
            "fuel_price_per_liter",
            "grid_available_ratio",
            "renewable_power_available_kw",
        ),
    },
    "berth_and_vessel_feed": {
        "max_age_seconds": 300,
        "required_fields": (
            "vessels_at_anchor",
            "vessels_at_berth",
            "vessels_departed",
            "average_days_at_berth",
            "average_days_in_port",
            "berth_available_ratio",
        ),
    },
    "equipment_availability_feed": {
        "max_age_seconds": 120,
        "required_fields": ("crane_available_ratio", "yard_available_ratio"),
    },
    "weather_and_navigation_feed": {
        "max_age_seconds": 900,
        "required_fields": (
            "wind_speed_m_s",
            "wave_height_m",
            "visibility_km",
            "precipitation_mm",
        ),
    },
    "shore_power_compatibility_registry": {
        "max_age_seconds": 86_400,
        "required_fields": ("shore_power_compatible_ratio",),
    },
}
RATIO_FIELDS = {
    "grid_available_ratio",
    "berth_available_ratio",
    "crane_available_ratio",
    "yard_available_ratio",
    "shore_power_compatible_ratio",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class SnapshotEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SNAPSHOT_SCHEMA_VERSION
    snapshot_id: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    port_id: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")
    adapter_id: str
    source_system: str = Field(min_length=2, max_length=128)
    source_record_id: str = Field(min_length=1, max_length=256)
    sequence: int = Field(ge=0)
    observed_at: datetime
    received_at: datetime
    payload: dict[str, Any]
    units: dict[str, str]
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    signature: str = Field(default="", pattern=r"^(?:[0-9a-f]{64})?$")

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: str) -> str:
        if value != SNAPSHOT_SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {SNAPSHOT_SCHEMA_VERSION}")
        return value

    @field_validator("adapter_id")
    @classmethod
    def validate_adapter_id(cls, value: str) -> str:
        if value not in DATA_ADAPTER_CONTRACTS:
            raise ValueError(f"Unknown adapter_id: {value}")
        return value

    @field_validator("observed_at", "received_at")
    @classmethod
    def validate_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("snapshot timestamps must be timezone-aware")
        return value.astimezone(timezone.utc)

    def computed_payload_sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.payload)).hexdigest()

    def signing_bytes(self) -> bytes:
        return canonical_json(self.model_dump(mode="json", exclude={"signature"}))

    def signed(self, secret: str) -> "SnapshotEnvelope":
        signature = hmac.new(secret.encode("utf-8"), self.signing_bytes(), hashlib.sha256).hexdigest()
        return self.model_copy(update={"signature": signature})


class PortIntegrationGateway:
    """Validate and persist evidence for read-only port snapshots.

    Only digests and lineage metadata are persisted. Operational payload values
    remain in the source system and are deliberately excluded from this state file.
    """

    def __init__(
        self,
        *,
        signing_keys: dict[str, str] | None = None,
        state_path: str | Path | None = None,
        port_id: str | None = None,
        clock: Callable[[], datetime] = utc_now,
        max_clock_skew_seconds: int | None = None,
    ) -> None:
        self.signing_keys = dict(signing_keys or {})
        self.state_path = Path(state_path or settings.integration_state_path)
        self.port_id = str(port_id if port_id is not None else settings.live_port_id).strip()
        self.clock = clock
        self.max_clock_skew_seconds = int(
            max_clock_skew_seconds
            if max_clock_skew_seconds is not None
            else settings.live_max_clock_skew_seconds
        )
        self._lock = threading.RLock()
        self._state: dict[str, Any] = {"schema_version": "integration-state.v1", "adapters": {}}
        self._load()

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            if value.get("schema_version") == "integration-state.v1" and isinstance(
                value.get("adapters"), dict
            ):
                self._state = value
        except (OSError, ValueError, TypeError):
            self._state = {"schema_version": "integration-state.v1", "adapters": {}}

    def _persist(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(self.state_path)

    @staticmethod
    def contract() -> dict[str, Any]:
        return {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "mode": "read_only_shadow_ingestion",
            "adapters": DATA_ADAPTER_CONTRACTS,
            "integrity": {
                "payload_digest": "SHA-256 over canonical payload JSON",
                "signature": "per-adapter HMAC-SHA256 over the canonical envelope",
                "replay_protection": "snapshot_id plus strictly increasing per-adapter sequence",
                "persistence": "lineage and digests only; raw operational payload is not retained",
            },
            "production_dispatch_enabled": False,
        }

    def ingest(self, envelope: SnapshotEnvelope) -> dict[str, Any]:
        now = self.clock().astimezone(timezone.utc)
        contract = DATA_ADAPTER_CONTRACTS[envelope.adapter_id]
        errors: list[str] = []
        if self.port_id and envelope.port_id != self.port_id:
            errors.append("port_id_mismatch")
        if envelope.payload_sha256 != envelope.computed_payload_sha256():
            errors.append("payload_sha256_mismatch")
        missing = sorted(set(contract["required_fields"]) - set(envelope.payload))
        if missing:
            errors.append("missing_fields:" + ",".join(missing))
        missing_units = sorted(
            field
            for field in contract["required_fields"]
            if field in envelope.payload and not str(envelope.units.get(field) or "").strip()
        )
        if missing_units:
            errors.append("missing_units:" + ",".join(missing_units))
        for name in contract["required_fields"]:
            value = envelope.payload.get(name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                errors.append(f"non_numeric_field:{name}")
                continue
            if not math.isfinite(float(value)):
                errors.append(f"non_finite_field:{name}")
            elif float(value) < 0:
                errors.append(f"negative_field:{name}")
            elif name in RATIO_FIELDS and float(value) > 1:
                errors.append(f"ratio_out_of_range:{name}")
        if envelope.received_at < envelope.observed_at:
            errors.append("received_before_observed")
        if (envelope.observed_at - now).total_seconds() > self.max_clock_skew_seconds:
            errors.append("observed_at_in_future")
        age_seconds = max(0.0, (now - envelope.observed_at).total_seconds())
        fresh = age_seconds <= float(contract["max_age_seconds"])
        if not fresh:
            errors.append("snapshot_stale")
        secret = self.signing_keys.get(envelope.adapter_id, "")
        signature_valid = bool(secret and envelope.signature) and hmac.compare_digest(
            envelope.signature,
            hmac.new(secret.encode("utf-8"), envelope.signing_bytes(), hashlib.sha256).hexdigest(),
        )
        if not secret:
            errors.append("adapter_signing_key_unconfigured")
        elif not signature_valid:
            errors.append("signature_invalid")

        with self._lock:
            previous = dict(self._state["adapters"].get(envelope.adapter_id) or {})
            recent = dict(previous.get("recent_snapshot_ids") or {})
            prior_digest = recent.get(envelope.snapshot_id)
            if prior_digest:
                if prior_digest != envelope.payload_sha256:
                    errors.append("snapshot_id_digest_conflict")
                elif not errors:
                    return {
                        "accepted": True,
                        "idempotent_replay": True,
                        "snapshot_id": envelope.snapshot_id,
                        "adapter_id": envelope.adapter_id,
                        "payload_sha256": envelope.payload_sha256,
                        "production_dispatch_enabled": False,
                    }
            last_sequence = int(previous.get("sequence", -1))
            if envelope.sequence <= last_sequence:
                errors.append("sequence_not_increasing")
            accepted = not errors
            evidence = {
                "adapter_id": envelope.adapter_id,
                "port_id": envelope.port_id,
                "source_system": envelope.source_system,
                "source_record_id": envelope.source_record_id,
                "snapshot_id": envelope.snapshot_id,
                "sequence": envelope.sequence,
                "observed_at": envelope.observed_at.isoformat().replace("+00:00", "Z"),
                "received_at": envelope.received_at.isoformat().replace("+00:00", "Z"),
                "validated_at": now.isoformat().replace("+00:00", "Z"),
                "payload_sha256": envelope.payload_sha256,
                "signature_valid": signature_valid,
                "fresh_at_validation": fresh,
                "age_seconds_at_validation": round(age_seconds, 3),
                "required_fields": list(contract["required_fields"]),
                "accepted": accepted,
                "errors": errors,
            }
            if accepted:
                recent[envelope.snapshot_id] = envelope.payload_sha256
                evidence["recent_snapshot_ids"] = dict(list(recent.items())[-100:])
                self._state["adapters"][envelope.adapter_id] = evidence
                self._state["updated_at"] = evidence["validated_at"]
                self._persist()
        return {
            **evidence,
            "idempotent_replay": False,
            "production_dispatch_enabled": False,
        }

    def status(self) -> dict[str, Any]:
        from app.core.security import verify_audit_chain

        now = self.clock().astimezone(timezone.utc)
        items: list[dict[str, Any]] = []
        with self._lock:
            persisted = dict(self._state.get("adapters") or {})
        for adapter_id, contract in DATA_ADAPTER_CONTRACTS.items():
            evidence = dict(persisted.get(adapter_id) or {})
            observed = evidence.get("observed_at")
            age_seconds = None
            if observed:
                age_seconds = max(
                    0.0,
                    (now - datetime.fromisoformat(str(observed).replace("Z", "+00:00"))).total_seconds(),
                )
            fresh = bool(
                evidence.get("accepted")
                and age_seconds is not None
                and age_seconds <= float(contract["max_age_seconds"])
            )
            ready = bool(fresh and evidence.get("signature_valid"))
            items.append(
                {
                    "adapter_id": adapter_id,
                    "ready": ready,
                    "fresh": fresh,
                    "max_age_seconds": contract["max_age_seconds"],
                    "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
                    "snapshot_id": evidence.get("snapshot_id"),
                    "payload_sha256": evidence.get("payload_sha256"),
                    "source_system": evidence.get("source_system"),
                    "observed_at": observed,
                    "signature_valid": bool(evidence.get("signature_valid")),
                }
            )
        identity_ready = settings.api_auth_mode == "api_key"
        audit_chain_ok = bool(verify_audit_chain().get("ok"))
        identity_and_audit_ready = identity_ready and audit_chain_ok
        read_only_ready = (
            bool(items)
            and all(item["ready"] for item in items)
            and identity_and_audit_ready
        )
        return {
            "mode": settings.port_operation_mode,
            "port_id": self.port_id or None,
            "read_only_shadow_ready": read_only_ready,
            "identity_and_audit_ready": identity_and_audit_ready,
            "audit_chain_ok": audit_chain_ok,
            "ready_adapter_count": sum(item["ready"] for item in items),
            "required_adapter_count": len(items),
            "adapters": items,
            "missing_adapters": [item["adapter_id"] for item in items if not item["ready"]],
            "production_dispatch_enabled": False,
            "blockers": (
                []
                if read_only_ready
                else [
                    "Every required feed must have a fresh, signed, schema-valid snapshot.",
                    "API authentication and tamper-evident audit must be enabled.",
                ]
            ),
        }


integration_gateway = PortIntegrationGateway(signing_keys=settings.snapshot_signing_keys)
