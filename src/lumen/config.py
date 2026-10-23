from datetime import timedelta
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://lumen:lumen@localhost:5432/lumen"
    test_database_url: str = "postgresql+psycopg://lumen:lumen@localhost:5432/lumen_test"
    log_level: str = "INFO"

    # Sessions (env values accept ISO 8601 durations, e.g. SESSION_IDLE_TIMEOUT=PT12H).
    session_idle_timeout: timedelta = timedelta(hours=12)
    session_absolute_timeout: timedelta = timedelta(days=7)
    session_touch_interval: timedelta = timedelta(minutes=5)


@lru_cache
def get_settings() -> Settings:
    return Settings()
