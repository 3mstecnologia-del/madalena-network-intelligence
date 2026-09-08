from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.cdr.secret_runtime import hydrate_infisical_identity
from collectors.common.infisical import InfisicalClient, fetch_all_cached


settings = get_settings()
_db_secret_prefix = settings.cdr_secret_prefix or "ASTERISK_LESANTE_CDR_DB"
_engine = None
_SessionLocal = None


def _db_secret_map() -> dict[str, str]:
    hydrate_infisical_identity()
    try:
        return fetch_all_cached(InfisicalClient())
    except Exception:
        return {}


def _secret_value(prefix: str, suffix: str) -> str:
    env_key = f"{prefix}_{suffix}"
    value = (os.getenv(env_key) or "").strip()
    if value:
        return value
    values = _db_secret_map()
    return (values.get(env_key) or "").strip()


def _build_database_url() -> str:
    if settings.cdr_db_ro_url:
        return settings.cdr_db_ro_url
    if settings.cdr_db_url:
        return settings.cdr_db_url
    user = _secret_value(_db_secret_prefix, "USER") or settings.asterisk_lesante_cdr_db_user or settings.cdr_db_user
    password = _secret_value(_db_secret_prefix, "PASSWORD") or settings.asterisk_lesante_cdr_db_password or settings.cdr_db_password
    host = _secret_value(_db_secret_prefix, "HOST") or settings.asterisk_lesante_cdr_db_host or settings.cdr_db_host
    port_raw = _secret_value(_db_secret_prefix, "PORT")
    port = int(port_raw or settings.asterisk_lesante_cdr_db_port or settings.cdr_db_port or 5432)
    name = _secret_value(_db_secret_prefix, "NAME") or settings.asterisk_lesante_cdr_db_name or settings.cdr_db_name
    sslmode = _secret_value(_db_secret_prefix, "SSLMODE") or settings.asterisk_lesante_cdr_db_sslmode or settings.cdr_db_sslmode
    if not user or not password or not host or not name:
        raise RuntimeError(f"cdr db credentials unavailable for prefix {_db_secret_prefix}")
    return (
        f"postgresql+psycopg://{user}:{password}"
        f"@{host}:{port}/{name}"
        f"?options=-cdefault_transaction_read_only%3Don&sslmode={sslmode}"
    )


def _get_session_local():
    global _engine, _SessionLocal
    if _SessionLocal is None:
        _engine = create_engine(
            _build_database_url(),
            pool_pre_ping=True,
            pool_size=1,
            max_overflow=0,
        )
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _SessionLocal


def get_cdr_db() -> Generator[Session, None, None]:
    SessionLocal = _get_session_local()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
