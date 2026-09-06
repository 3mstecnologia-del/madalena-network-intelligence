from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://madalena:change_me_in_local_env_only@db:5432/madalena"
    api_log_level: str = "info"
    secret_provider: str = "infisical"
    api_base_url: str = "http://api:8000"
    scheduler_enabled: bool = True
    # Automatic collection policy: only N FULL runs per day (comma-separated
    # HH:MM in scheduler_timezone). Intermediate/light auto jobs are removed.
    scheduler_full_cron: str = "07:00,12:00,18:00,23:59"
    scheduler_timezone: str = "America/Sao_Paulo"
    mcp_http_host: str = "0.0.0.0"
    mcp_http_port: int = 8081
    seed_tenant_slug: str = "example-tenant"
    seed_site_slug: str = "example-site"
    seed_exclude_vlan: Optional[str] = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
