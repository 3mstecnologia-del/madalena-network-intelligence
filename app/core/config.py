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

    # CDR portal / LeSante
    cdr_public_host: str = "cdr.sante.madalena.3mstecnologia.com"
    cdr_portal_username: str = "cdr.lesante"
    cdr_portal_password: str = ""
    cdr_portal_secret_prefix: str = "CDR_PORTAL"
    cdr_db_engine: str = "postgresql"
    asterisk_lesante_cdr_db_engine: str = "postgresql"
    cdr_db_host: str = ""
    asterisk_lesante_cdr_db_host: str = ""
    cdr_db_port: int = 5432
    asterisk_lesante_cdr_db_port: int = 5432
    cdr_db_name: str = "asterisk"
    asterisk_lesante_cdr_db_name: str = "asterisk"
    cdr_db_user: str = "asterisk"
    asterisk_lesante_cdr_db_user: str = "asterisk"
    cdr_db_password: str = ""
    asterisk_lesante_cdr_db_password: str = ""
    cdr_db_url: str = ""
    cdr_db_ro_url: str = ""
    cdr_db_schema: str = "public"
    asterisk_lesante_cdr_db_schema: str = "public"
    cdr_db_table: str = "cdr"
    asterisk_lesante_cdr_db_table: str = "cdr"
    cdr_db_archive_table: str = "cdr_antigo"
    asterisk_lesante_cdr_db_archive_table: str = "cdr_antigo"
    cdr_db_timezone: str = "America/Sao_Paulo"
    asterisk_lesante_cdr_db_timezone: str = "America/Sao_Paulo"
    cdr_db_sslmode: str = "disable"
    asterisk_lesante_cdr_db_sslmode: str = "disable"
    cdr_secret_prefix: str = "ASTERISK_LESANTE_CDR_DB"
    cdr_default_limit: int = 25
    cdr_max_limit: int = 200


@lru_cache
def get_settings() -> Settings:
    return Settings()
