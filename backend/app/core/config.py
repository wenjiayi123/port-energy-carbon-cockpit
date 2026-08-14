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

    @model_validator(mode="after")
    def validate_security_configuration(self) -> "Settings":
        self.api_auth_mode = self.api_auth_mode.lower().strip()
        if self.api_auth_mode not in {"disabled", "api_key"}:
            raise ValueError("API_AUTH_MODE must be disabled or api_key")
        if self.production and self.api_auth_mode != "api_key":
            raise ValueError("Production requires API_AUTH_MODE=api_key")
        if self.api_auth_mode == "api_key":
            configured = [
                value
                for value in (self.viewer_api_key, self.operator_api_key, self.admin_api_key)
                if value
            ]
            if not configured or any(len(value) < 24 for value in configured):
                raise ValueError("API keys must contain at least 24 characters")
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
            if self.api_auth_mode != "api_key":
                raise ValueError("Shadow port mode requires API_AUTH_MODE=api_key")
            if not self.live_port_id.strip():
                raise ValueError("Shadow port mode requires LIVE_PORT_ID")
            keys = self.snapshot_signing_keys
            if not keys or any(len(secret) < 32 for secret in keys.values()):
                raise ValueError(
                    "Shadow port mode requires per-adapter signing secrets of at least 32 characters"
                )
        return self


settings = Settings()
