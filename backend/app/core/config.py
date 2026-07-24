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

    @property
    def allowed_cors_origins(self) -> list[str]:
        return [value.strip() for value in self.cors_origins.split(",") if value.strip()]

    @property
    def production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}

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
        return self


settings = Settings()
