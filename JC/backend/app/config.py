from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    jwt_secret: str = "dev-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7
    admin_api_key: str = ""

    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_api_version: str = "v22.0"
    whatsapp_disable: bool = False
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
