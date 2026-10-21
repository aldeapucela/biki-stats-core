from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = Field(default="development", alias="BIKI_ENV")
    database_path: str = Field(default="./data/movilidad.sqlite3", alias="BIKI_DATABASE_PATH")
    cors_origins: str = Field(
        default="http://localhost:5173,http://localhost:5174,https://biki.aldeapucela.org",
        alias="BIKI_CORS_ORIGINS",
    )
    gbfs_url: str = Field(
        default="https://valladolid.publicbikesystem.net/customer/gbfs/v3.0/gbfs.json",
        alias="BIKI_GBFS_URL",
    )
    capture_interval_seconds: int = Field(default=300, alias="BIKI_CAPTURE_INTERVAL_SECONDS", ge=1)
    http_timeout_seconds: float = Field(default=20.0, alias="BIKI_HTTP_TIMEOUT_SECONDS", gt=0)
    log_level: str = Field(default="INFO", alias="BIKI_LOG_LEVEL")
    collector_token: str | None = Field(default=None, alias="BIKI_COLLECTOR_TOKEN")
    history_import_on_startup: bool = Field(default=False, alias="BIKI_HISTORY_IMPORT_ON_STARTUP")
    history_source_repository: str = Field(
        default="serherval/flujosbiki", alias="BIKI_HISTORY_SOURCE_REPOSITORY"
    )
    history_source_ref: str = Field(default="main", alias="BIKI_HISTORY_SOURCE_REF")
    history_import_retry_seconds: int = Field(
        default=300, alias="BIKI_HISTORY_IMPORT_RETRY_SECONDS", ge=1
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
