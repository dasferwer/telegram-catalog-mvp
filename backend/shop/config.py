import re
from functools import cached_property

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")
    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://unconfigured:unconfigured@localhost:5432/catalog"
    )
    public_origin: str = "http://localhost:8088"
    cookie_secure: bool = False
    bot_token: SecretStr = SecretStr("")
    webhook_secret: SecretStr = SecretStr("")
    admin_ids: str = ""
    telegram_api_url: str = ""
    s3_endpoint: str = "http://minio:9000"
    s3_access_key: SecretStr = SecretStr("unconfigured")
    s3_secret_key: SecretStr = SecretStr("unconfigured")
    s3_bucket: str = "product-photos"
    max_photo_bytes: int = Field(default=5 * 1024 * 1024, ge=1024, le=10 * 1024 * 1024)

    @field_validator("public_origin")
    @classmethod
    def origin_only(cls, value: str) -> str:
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or parsed.username
        ):
            raise ValueError("PUBLIC_ORIGIN must be an HTTP(S) origin")
        return value.rstrip("/")

    @model_validator(mode="after")
    def secure_https(self) -> "Settings":
        if self.public_origin.startswith("https://") and not self.cookie_secure:
            raise ValueError("HTTPS requires COOKIE_SECURE=true")
        if self.admin_ids and not all(
            re.fullmatch(r"[1-9][0-9]*", x.strip()) for x in self.admin_ids.split(",")
        ):
            raise ValueError("ADMIN_IDS must contain positive numeric IDs")
        return self

    @field_validator("webhook_secret")
    @classmethod
    def webhook_secret_format(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if raw and not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", raw):
            raise ValueError("WEBHOOK_SECRET must contain 1-256 URL-safe characters")
        return value

    @cached_property
    def admins(self) -> frozenset[int]:
        return frozenset(int(x.strip()) for x in self.admin_ids.split(",") if x.strip())

    @property
    def session_cookie_name(self) -> str:
        return "__Host-catalog_session" if self.cookie_secure else "catalog_session"
