from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./magazine.db"

    anthropic_api_key: str = ""
    guardian_api_key: str = ""

    x_client_id: str = ""
    x_client_secret: str = ""
    x_user_id: str = ""
    x_access_token: str = ""
    x_refresh_token: str = ""

    opds_basic_auth_user: str = ""
    opds_basic_auth_password: str = ""

    data_dir: str = "./data"
    issues_dir: str = "./output"
    ntfy_topic: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
