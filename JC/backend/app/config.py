from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BAD_JWT_SECRETS = frozenset({"", "dev-change-me", "change-me", "secret", "jwt-secret"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    jwt_secret: str = "dev-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24  # 24h staff sessions
    # Customer portal — stay logged in on device for years
    jwt_customer_expire_minutes: int = 60 * 24 * 365 * 10  # ~10 years
    admin_api_key: str = ""

    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_api_version: str = "v22.0"
    whatsapp_disable: bool = False
    # Comma-separated staff phones for new customer-order alerts (10-digit or E.164).
    whatsapp_staff_notify_phones: str = ""
    customer_portal_url: str = ""
    customer_portal_url_button_suffix: str = ""

    s3_endpoint_url: str = ""
    s3_region: str = "ap-southeast-1"
    s3_bucket: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""

    @field_validator("whatsapp_disable", mode="before")
    @classmethod
    def _parse_whatsapp_disable(cls, v: object) -> bool:
        if isinstance(v, bool):
            return v
        if v is None:
            return False
        return str(v).strip().lower() in ("1", "true", "yes")

    @model_validator(mode="after")
    def _harden_jwt(self) -> "Settings":
        is_sqlite = self.database_url.strip().lower().startswith("sqlite:")
        secret = (self.jwt_secret or "").strip()
        if not is_sqlite and (secret.lower() in _BAD_JWT_SECRETS or len(secret) < 16):
            raise ValueError(
                "JWT_SECRET must be set to a strong value (≥16 chars) when not using sqlite"
            )
        if self.jwt_expire_minutes > 60 * 24 * 7:
            # Cap absurd TTLs; default is 24h
            object.__setattr__(self, "jwt_expire_minutes", 60 * 24 * 7)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
