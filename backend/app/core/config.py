import base64
import binascii
import json
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    app_env: str = "development"
    api_auth_mode: str = "disabled"
    viewer_api_key: str = ""
    operator_api_key: str = ""
    admin_api_key: str = ""
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_public_keys_json: str = "{}"
    oidc_role_map_json: str = '{"viewer":"viewer","operator":"operator","admin":"admin"}'
    oidc_role_claim: str = "roles"
    oidc_tenant_claim: str = "tenant_ids"
    oidc_require_mfa: bool = True
    oidc_clock_skew_seconds: int = 60
    oidc_max_token_age_seconds: int = 3_600
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    audit_log_path: str = str(DEFAULT_DATA_DIR / "audit" / "audit.jsonl")
    carbon_price_cny_per_ton: float = 85.0
    default_scenario: str = "port_la_2025_public_benchmark"
    default_green_preference: float = 0.5
    max_request_body_bytes: int = 1_048_576
    rate_limit_requests_per_minute: int = 600
    port_operation_mode: str = "offline_benchmark"
    live_port_id: str = ""
    port_snapshot_keys_json: str = "{}"
    integration_state_path: str = str(DEFAULT_DATA_DIR / "integration" / "state.json")
    runtime_state_path: str = str(DEFAULT_DATA_DIR / "runtime" / "decisions.json")
    live_max_clock_skew_seconds: int = 60
    mv_verifier_public_keys_json: str = "{}"
    carbon_registry_public_keys_json: str = "{}"
    management_system_auditor_public_keys_json: str = "{}"
    operations_source_public_keys_json: str = "{}"
    electrical_source_public_keys_json: str = "{}"
    algorithm_evidence_public_keys_json: str = "{}"
    commercial_settlement_public_keys_json: str = "{}"
    port_collaboration_public_keys_json: str = "{}"
    enterprise_security_public_keys_json: str = "{}"
    site_cutover_trusted_signers_json: str = "{}"

    @property
    def allowed_cors_origins(self) -> list[str]:
        return [value.strip() for value in self.cors_origins.split(",") if value.strip()]

    @property
    def production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}

    @property
    def snapshot_signing_keys(self) -> dict[str, str]:
        try:
            value = json.loads(self.port_snapshot_keys_json or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("PORT_SNAPSHOT_KEYS_JSON must be a JSON object") from exc
        if not isinstance(value, dict) or not all(
            isinstance(name, str) and isinstance(secret, str) for name, secret in value.items()
        ):
            raise ValueError("PORT_SNAPSHOT_KEYS_JSON must map adapter IDs to secrets")
        return value

    @property
    def oidc_public_keys(self) -> dict[str, str]:
        try:
            value = json.loads(self.oidc_public_keys_json or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("OIDC_PUBLIC_KEYS_JSON must be a JSON object") from exc
        if not isinstance(value, dict) or not all(
            isinstance(key_id, str) and isinstance(public_key, str)
            for key_id, public_key in value.items()
        ):
            raise ValueError("OIDC_PUBLIC_KEYS_JSON must map key IDs to base64 Ed25519 keys")
        for key_id, public_key in value.items():
            try:
                decoded = base64.b64decode(public_key, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ValueError(f"OIDC public key {key_id} is not valid base64") from exc
            if len(decoded) != 32:
                raise ValueError(f"OIDC public key {key_id} must be a 32-byte Ed25519 key")
        return value

    @property
    def oidc_role_map(self) -> dict[str, str]:
        try:
            value = json.loads(self.oidc_role_map_json or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("OIDC_ROLE_MAP_JSON must be a JSON object") from exc
        if not isinstance(value, dict) or not value or not all(
            isinstance(external, str)
            and isinstance(internal, str)
            and internal in {"viewer", "operator", "admin"}
            for external, internal in value.items()
        ):
            raise ValueError("OIDC_ROLE_MAP_JSON must map external roles to viewer/operator/admin")
        return value

    @property
    def mv_verifier_public_keys(self) -> dict[str, str]:
        try:
            value = json.loads(self.mv_verifier_public_keys_json or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("MV_VERIFIER_PUBLIC_KEYS_JSON must be a JSON object") from exc
        if not isinstance(value, dict) or not all(
            isinstance(key_id, str) and isinstance(public_key, str)
            for key_id, public_key in value.items()
        ):
            raise ValueError("MV_VERIFIER_PUBLIC_KEYS_JSON must map key IDs to base64 public keys")
        return value

    @property
    def carbon_registry_public_keys(self) -> dict[str, str]:
        try:
            value = json.loads(self.carbon_registry_public_keys_json or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("CARBON_REGISTRY_PUBLIC_KEYS_JSON must be a JSON object") from exc
        if not isinstance(value, dict) or not all(
            isinstance(key_id, str) and isinstance(public_key, str)
            for key_id, public_key in value.items()
        ):
            raise ValueError(
                "CARBON_REGISTRY_PUBLIC_KEYS_JSON must map key IDs to base64 public keys"
            )
        return value

    @property
    def management_system_auditor_public_keys(self) -> dict[str, str]:
        try:
            value = json.loads(self.management_system_auditor_public_keys_json or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(
                "MANAGEMENT_SYSTEM_AUDITOR_PUBLIC_KEYS_JSON must be a JSON object"
            ) from exc
        if not isinstance(value, dict) or not all(
            isinstance(key_id, str) and isinstance(public_key, str)
            for key_id, public_key in value.items()
        ):
            raise ValueError(
                "MANAGEMENT_SYSTEM_AUDITOR_PUBLIC_KEYS_JSON must map key IDs to base64 public keys"
            )
        return value

    @property
    def operations_source_public_keys(self) -> dict[str, str]:
        try:
            value = json.loads(self.operations_source_public_keys_json or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("OPERATIONS_SOURCE_PUBLIC_KEYS_JSON must be a JSON object") from exc
        if not isinstance(value, dict) or not all(
            isinstance(key_id, str) and isinstance(public_key, str)
            for key_id, public_key in value.items()
        ):
            raise ValueError(
                "OPERATIONS_SOURCE_PUBLIC_KEYS_JSON must map key IDs to base64 public keys"
            )
        return value

    @property
    def electrical_source_public_keys(self) -> dict[str, str]:
        try:
            value = json.loads(self.electrical_source_public_keys_json or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("ELECTRICAL_SOURCE_PUBLIC_KEYS_JSON must be a JSON object") from exc
        if not isinstance(value, dict) or not all(
            isinstance(key_id, str) and isinstance(public_key, str)
            for key_id, public_key in value.items()
        ):
            raise ValueError(
                "ELECTRICAL_SOURCE_PUBLIC_KEYS_JSON must map key IDs to base64 public keys"
            )
        return value

    @property
    def algorithm_evidence_public_keys(self) -> dict[str, str]:
        try:
            value = json.loads(self.algorithm_evidence_public_keys_json or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("ALGORITHM_EVIDENCE_PUBLIC_KEYS_JSON must be a JSON object") from exc
        if not isinstance(value, dict) or not all(
            isinstance(key_id, str) and isinstance(public_key, str)
            for key_id, public_key in value.items()
        ):
            raise ValueError(
                "ALGORITHM_EVIDENCE_PUBLIC_KEYS_JSON must map key IDs to base64 public keys"
            )
        return value

    @property
    def commercial_settlement_public_keys(self) -> dict[str, str]:
        try:
            value = json.loads(self.commercial_settlement_public_keys_json or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(
                "COMMERCIAL_SETTLEMENT_PUBLIC_KEYS_JSON must be a JSON object"
            ) from exc
        if not isinstance(value, dict) or not all(
            isinstance(key_id, str) and isinstance(public_key, str)
            for key_id, public_key in value.items()
        ):
            raise ValueError(
                "COMMERCIAL_SETTLEMENT_PUBLIC_KEYS_JSON must map key IDs to base64 public keys"
            )
        return value

    @property
    def port_collaboration_public_keys(self) -> dict[str, str]:
        try:
            value = json.loads(self.port_collaboration_public_keys_json or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("PORT_COLLABORATION_PUBLIC_KEYS_JSON must be a JSON object") from exc
        if not isinstance(value, dict) or not all(
            isinstance(key_id, str) and isinstance(public_key, str)
            for key_id, public_key in value.items()
        ):
            raise ValueError(
                "PORT_COLLABORATION_PUBLIC_KEYS_JSON must map key IDs to base64 public keys"
            )
        return value

    @property
    def enterprise_security_public_keys(self) -> dict[str, str]:
        try:
            value = json.loads(self.enterprise_security_public_keys_json or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("ENTERPRISE_SECURITY_PUBLIC_KEYS_JSON must be a JSON object") from exc
        if not isinstance(value, dict) or not all(
            isinstance(key_id, str) and isinstance(public_key, str)
            for key_id, public_key in value.items()
        ):
            raise ValueError(
                "ENTERPRISE_SECURITY_PUBLIC_KEYS_JSON must map key IDs to base64 public keys"
            )
        return value

    @property
    def site_cutover_trusted_signers(self) -> dict[str, dict[str, str]]:
        try:
            value = json.loads(self.site_cutover_trusted_signers_json or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("SITE_CUTOVER_TRUSTED_SIGNERS_JSON must be a JSON object") from exc
        authorities = {
            "live_port_data",
            "measurement_and_calibration",
            "production_execution",
            "long_horizon_shadow",
            "port_emissions_inventory",
            "energy_carbon_management",
            "operations_energy_coupling",
            "electrical_network",
            "algorithm_production",
            "carbon_asset_compliance",
            "commercial_settlement",
            "port_collaboration",
            "enterprise_ot_security",
            "port_owner",
            "operations_owner",
            "energy_carbon_owner",
            "ot_safety_owner",
            "chief_information_security_officer",
            "independent_verifier",
        }
        if not isinstance(value, dict):
            raise ValueError("SITE_CUTOVER_TRUSTED_SIGNERS_JSON must be a JSON object")
        for key_id, signer in value.items():
            if (
                not isinstance(key_id, str)
                or not isinstance(signer, dict)
                or not isinstance(signer.get("public_key"), str)
                or signer.get("authority") not in authorities
            ):
                raise ValueError(
                    "SITE_CUTOVER_TRUSTED_SIGNERS_JSON must map key IDs to public_key and authority"
                )
            try:
                decoded = base64.b64decode(signer["public_key"], validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ValueError(f"Site cutover public key {key_id} is not valid base64") from exc
            if len(decoded) != 32:
                raise ValueError(f"Site cutover public key {key_id} must be 32 bytes")
        return value

    @model_validator(mode="after")
    def validate_security_configuration(self) -> "Settings":
        self.api_auth_mode = self.api_auth_mode.lower().strip()
        if self.api_auth_mode not in {"disabled", "api_key", "oidc"}:
            raise ValueError("API_AUTH_MODE must be disabled, api_key, or oidc")
        if self.production and self.api_auth_mode not in {"api_key", "oidc"}:
            raise ValueError("Production requires API_AUTH_MODE=api_key or oidc")
        if self.api_auth_mode == "api_key":
            configured = [
                value
                for value in (self.viewer_api_key, self.operator_api_key, self.admin_api_key)
                if value
            ]
            if not configured or any(len(value) < 24 for value in configured):
                raise ValueError("API keys must contain at least 24 characters")
        if self.api_auth_mode == "oidc":
            if not self.oidc_issuer.strip() or not self.oidc_audience.strip():
                raise ValueError("OIDC mode requires OIDC_ISSUER and OIDC_AUDIENCE")
            if not self.oidc_public_keys:
                raise ValueError("OIDC mode requires at least one OIDC public key")
            self.oidc_role_map
            if not self.oidc_role_claim.strip() or not self.oidc_tenant_claim.strip():
                raise ValueError("OIDC role and tenant claim names cannot be empty")
            if not 0 <= self.oidc_clock_skew_seconds <= 300:
                raise ValueError("OIDC_CLOCK_SKEW_SECONDS must be between 0 and 300")
            if not 60 <= self.oidc_max_token_age_seconds <= 86_400:
                raise ValueError("OIDC_MAX_TOKEN_AGE_SECONDS must be between 60 and 86400")
        self.port_operation_mode = self.port_operation_mode.lower().strip()
        if self.port_operation_mode not in {"offline_benchmark", "shadow"}:
            raise ValueError(
                "PORT_OPERATION_MODE must be offline_benchmark or shadow; "
                "physical dispatch is intentionally outside this repository"
            )
        if not 1_024 <= self.max_request_body_bytes <= 16_777_216:
            raise ValueError("MAX_REQUEST_BODY_BYTES must be between 1024 and 16777216")
        if not 10 <= self.rate_limit_requests_per_minute <= 100_000:
            raise ValueError("RATE_LIMIT_REQUESTS_PER_MINUTE must be between 10 and 100000")
        if self.port_operation_mode == "shadow":
            if self.api_auth_mode not in {"api_key", "oidc"}:
                raise ValueError("Shadow port mode requires API_AUTH_MODE=api_key or oidc")
            if not self.live_port_id.strip():
                raise ValueError("Shadow port mode requires LIVE_PORT_ID")
            keys = self.snapshot_signing_keys
            if not keys or any(len(secret) < 32 for secret in keys.values()):
                raise ValueError(
                    "Shadow port mode requires per-adapter signing secrets of at least 32 characters"
                )
        return self


settings = Settings()
