from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://lumen:lumen@localhost:5432/lumen"
    test_database_url: str = "postgresql+psycopg://lumen:lumen@localhost:5432/lumen_test"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
