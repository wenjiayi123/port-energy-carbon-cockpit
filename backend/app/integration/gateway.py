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
SHADOW_STATE_SCHEMA_VERSION = "port-shadow-state.v1"
SHADOW_ALIGNMENT_MAX_SECONDS = 300
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
DYNAMIC_ADAPTER_IDS = tuple(
    adapter_id
    for adapter_id in DATA_ADAPTER_CONTRACTS
    if adapter_id != "shore_power_compatibility_registry"
)
REQUIRED_SHADOW_FIELD_COUNT = sum(
    len(contract["required_fields"])
    for contract in DATA_ADAPTER_CONTRACTS.values()
)
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
        # Validated operational values intentionally remain process-local. A
        # restart must be followed by a fresh resend from every source before a
        # composite shadow state can become ready again.
        self._resident_envelopes: dict[str, SnapshotEnvelope] = {}
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
            "composite_shadow_state": {
                "schema_version": SHADOW_STATE_SCHEMA_VERSION,
                "endpoint": "/api/integration/shadow-snapshot",
                "required_adapter_count": len(DATA_ADAPTER_CONTRACTS),
                "required_field_count": REQUIRED_SHADOW_FIELD_COUNT,
                "dynamic_adapter_ids": list(DYNAMIC_ADAPTER_IDS),
                "max_observation_skew_seconds": SHADOW_ALIGNMENT_MAX_SECONDS,
                "atomic_release": "no observation values are released until every gate passes",
                "restart_behavior": "resident payloads are cleared and every source must resend",
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
                    self._resident_envelopes[envelope.adapter_id] = envelope.model_copy(deep=True)
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
                self._resident_envelopes[envelope.adapter_id] = envelope.model_copy(deep=True)
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
            resident = dict(self._resident_envelopes)
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
            resident_envelope = resident.get(adapter_id)
            resident_payload_ready = bool(
                ready
                and resident_envelope
                and resident_envelope.snapshot_id == evidence.get("snapshot_id")
                and resident_envelope.payload_sha256 == evidence.get("payload_sha256")
            )
            items.append(
                {
                    "adapter_id": adapter_id,
                    "ready": ready,
                    "resident_payload_ready": resident_payload_ready,
                    "fresh": fresh,
                    "max_age_seconds": contract["max_age_seconds"],
                    "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
                    "snapshot_id": evidence.get("snapshot_id"),
                    "payload_sha256": evidence.get("payload_sha256"),
                    "source_system": evidence.get("source_system"),
                    "source_record_id": evidence.get("source_record_id"),
                    "sequence": evidence.get("sequence"),
                    "observed_at": observed,
                    "received_at": evidence.get("received_at"),
                    "signature_valid": bool(evidence.get("signature_valid")),
                }
            )
        identity_ready = settings.api_auth_mode == "api_key"
        audit_chain_ok = bool(verify_audit_chain().get("ok"))
        identity_and_audit_ready = identity_ready and audit_chain_ok
        feed_evidence_ready = bool(items) and all(item["ready"] for item in items)
        resident_adapter_ids = [
            item["adapter_id"] for item in items if item["resident_payload_ready"]
        ]
        missing_resident_adapters = [
            item["adapter_id"] for item in items if not item["resident_payload_ready"]
        ]
        dynamic_observed_at = [
            resident[adapter_id].observed_at
            for adapter_id in DYNAMIC_ADAPTER_IDS
            if adapter_id in resident_adapter_ids
        ]
        dynamic_sources_complete = len(dynamic_observed_at) == len(DYNAMIC_ADAPTER_IDS)
        observed_skew_seconds = (
            (max(dynamic_observed_at) - min(dynamic_observed_at)).total_seconds()
            if dynamic_sources_complete
            else None
        )
        time_alignment_ready = bool(
            dynamic_sources_complete
            and observed_skew_seconds is not None
            and observed_skew_seconds <= SHADOW_ALIGNMENT_MAX_SECONDS
        )
        shadow_mode_ready = settings.port_operation_mode == "shadow" and bool(self.port_id)
        read_only_ready = (
            feed_evidence_ready
            and len(resident_adapter_ids) == len(items)
            and time_alignment_ready
            and identity_and_audit_ready
            and shadow_mode_ready
        )
        blocker_codes: list[str] = []
        blockers: list[str] = []
        if not shadow_mode_ready:
            blocker_codes.append("shadow_mode_not_configured")
            blockers.append("Shadow operation mode and a named port are required.")
        if not feed_evidence_ready:
            blocker_codes.append("signed_feed_evidence_incomplete")
            blockers.append("Every required feed must have a fresh, signed, schema-valid snapshot.")
        if missing_resident_adapters:
            blocker_codes.append("resident_payload_missing")
            blockers.append(
                "Every source must resend after process start; persisted digests cannot reconstruct values."
            )
        if dynamic_sources_complete and not time_alignment_ready:
            blocker_codes.append("dynamic_sources_not_time_aligned")
            blockers.append(
                f"Dynamic source observation times must be within {SHADOW_ALIGNMENT_MAX_SECONDS} seconds."
            )
        if not identity_and_audit_ready:
            blocker_codes.append("identity_or_audit_not_ready")
            blockers.append("API authentication and tamper-evident audit must be enabled.")
        return {
            "mode": settings.port_operation_mode,
            "port_id": self.port_id or None,
            "read_only_shadow_ready": read_only_ready,
            "signed_feed_evidence_ready": feed_evidence_ready,
            "identity_and_audit_ready": identity_and_audit_ready,
            "audit_chain_ok": audit_chain_ok,
            "ready_adapter_count": sum(item["ready"] for item in items),
            "required_adapter_count": len(items),
            "resident_payload_count": len(resident_adapter_ids),
            "required_field_count": REQUIRED_SHADOW_FIELD_COUNT,
            "adapters": items,
            "missing_adapters": [item["adapter_id"] for item in items if not item["ready"]],
            "missing_resident_adapters": missing_resident_adapters,
            "dynamic_time_alignment": {
                "ready": time_alignment_ready,
                "observed_skew_seconds": round(observed_skew_seconds, 3)
                if observed_skew_seconds is not None
                else None,
                "max_allowed_seconds": SHADOW_ALIGNMENT_MAX_SECONDS,
                "adapter_ids": list(DYNAMIC_ADAPTER_IDS),
            },
            "production_dispatch_enabled": False,
            "blocker_codes": blocker_codes,
            "blockers": [] if read_only_ready else blockers,
        }

    def shadow_snapshot(self) -> dict[str, Any]:
        """Build one atomic, model-readable state from the six validated sources.

        Values are returned only when mode, identity, audit, freshness, resident
        payload and time-alignment gates all pass. This method never persists
        operational values and never grants production authority.
        """

        now = self.clock().astimezone(timezone.utc)
        status = self.status()
        base: dict[str, Any] = {
            "schema_version": SHADOW_STATE_SCHEMA_VERSION,
            "status": "ready" if status["read_only_shadow_ready"] else "blocked",
            "ready": status["read_only_shadow_ready"],
            "mode": status["mode"],
            "port_id": status["port_id"],
            "generated_at": now.isoformat().replace("+00:00", "Z"),
            "observation": {},
            "signals": {},
            "source_evidence": [
                {
                    "adapter_id": item["adapter_id"],
                    "ready": item["ready"],
                    "resident_payload_ready": item["resident_payload_ready"],
                    "source_system": item["source_system"],
                    "source_record_id": item["source_record_id"],
                    "sequence": item["sequence"],
                    "snapshot_id": item["snapshot_id"],
                    "payload_sha256": item["payload_sha256"],
                    "observed_at": item["observed_at"],
                    "received_at": item["received_at"],
                }
                for item in status["adapters"]
            ],
            "quality": {
                "gate": "PASS" if status["read_only_shadow_ready"] else "FAIL_CLOSED",
                "ready_adapter_count": status["ready_adapter_count"],
                "resident_payload_count": status["resident_payload_count"],
                "required_adapter_count": status["required_adapter_count"],
                "available_field_count": 0,
                "required_field_count": status["required_field_count"],
                "dynamic_time_alignment": status["dynamic_time_alignment"],
                "blocker_codes": status["blocker_codes"],
                "blockers": status["blockers"],
            },
            "production_boundary": {
                "read_only_shadow": True,
                "source_reported_values": status["read_only_shadow_ready"],
                "measurement_calibration_verified": False,
                "live_data_verified": False,
                "dispatch_allowed": False,
                "production_authority": False,
                "production_dispatch_enabled": False,
            },
            "snapshot_id": None,
            "snapshot_sha256": None,
        }
        if not status["read_only_shadow_ready"]:
            return base

        with self._lock:
            resident = {
                adapter_id: self._resident_envelopes[adapter_id].model_copy(deep=True)
                for adapter_id in DATA_ADAPTER_CONTRACTS
            }

        observation: dict[str, float] = {}
        signals: dict[str, dict[str, Any]] = {}
        for adapter_id, contract in DATA_ADAPTER_CONTRACTS.items():
            envelope = resident[adapter_id]
            event_time = envelope.observed_at.isoformat().replace("+00:00", "Z")
            ingest_time = envelope.received_at.isoformat().replace("+00:00", "Z")
            for field_id in contract["required_fields"]:
                value = float(envelope.payload[field_id])
                observation[field_id] = value
                signals[field_id] = {
                    "field_id": field_id,
                    "value": value,
                    "unit": envelope.units[field_id],
                    "event_time": event_time,
                    "ingest_time": ingest_time,
                    "source_type": "signed_shadow_source",
                    "source_id": envelope.source_system,
                    "source_record_id": envelope.source_record_id,
                    "adapter_id": adapter_id,
                    "source_snapshot_id": envelope.snapshot_id,
                    "source_payload_sha256": envelope.payload_sha256,
                    "source_sequence": envelope.sequence,
                    "quality_status": "schema_signature_freshness_alignment_verified",
                    "value_origin": "source_reported_not_independently_calibrated",
                    "measurement_verified": False,
                    "is_simulated": False,
                    "is_derived": False,
                }

        digest_payload = {
            "schema_version": SHADOW_STATE_SCHEMA_VERSION,
            "port_id": status["port_id"],
            "observation": observation,
            "sources": {
                adapter_id: {
                    "snapshot_id": resident[adapter_id].snapshot_id,
                    "payload_sha256": resident[adapter_id].payload_sha256,
                    "sequence": resident[adapter_id].sequence,
                }
                for adapter_id in DATA_ADAPTER_CONTRACTS
            },
        }
        snapshot_sha256 = hashlib.sha256(canonical_json(digest_payload)).hexdigest()
        base.update(
            {
                "snapshot_id": f"shadow:{snapshot_sha256[:24]}",
                "snapshot_sha256": snapshot_sha256,
                "observation": observation,
                "signals": signals,
            }
        )
        base["quality"]["available_field_count"] = len(observation)
        return base


integration_gateway = PortIntegrationGateway(signing_keys=settings.snapshot_signing_keys)
