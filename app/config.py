import os
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ENV_FILE lets the Cloud Run deployment point at a .env mounted from
    # Secret Manager (it can't be mounted over /app/.env without shadowing
    # the app directory). Real environment variables still take precedence.
    model_config = SettingsConfigDict(
        env_file=os.environ.get("ENV_FILE", ".env"), env_file_encoding="utf-8", extra="ignore"
    )

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

    # Full resource name of the Cloud Run Job that runs the pipeline
    # (projects/P/locations/R/jobs/J). When set, "Run now" starts that job
    # instead of running inline, and the schedule is owned by Cloud Scheduler
    # rather than the cron expression in `settings`. Blank everywhere except
    # the Cloud Run deployment.
    pipeline_job_name: str = ""

    @field_validator("database_url")
    @classmethod
    def _use_psycopg_driver(cls, value: str) -> str:
        # Hosted Postgres providers (Neon etc.) hand out postgres:// or
        # postgresql:// URLs, which SQLAlchemy maps to psycopg2 — point them
        # at the psycopg (v3) driver this project actually installs.
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix) :]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
