from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://madalena:change_me_in_local_env_only@db:5432/madalena"
    api_log_level: str = "info"
    secret_provider: str = "infisical"
    api_base_url: str = "http://api:8000"
    scheduler_enabled: bool = True
    scheduler_mikrotik_interval_sec: int = 900
    scheduler_olt_interval_sec: int = 1800
    scheduler_full_inventory_interval_sec: int = 21600
    mcp_http_host: str = "0.0.0.0"
    mcp_http_port: int = 8081
    seed_tenant_slug: str = "example-tenant"
    seed_site_slug: str = "example-site"


@lru_cache
def get_settings() -> Settings:
    return Settings()
