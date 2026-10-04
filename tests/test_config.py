import pytest

from app.config import Settings


@pytest.mark.parametrize(
    "url",
    [
        "postgres://user:pw@host/db?sslmode=require",
        "postgresql://user:pw@host/db?sslmode=require",
        "postgresql+psycopg://user:pw@host/db?sslmode=require",
    ],
)
def test_postgres_urls_use_psycopg_driver(url: str) -> None:
    settings = Settings(_env_file=None, database_url=url)

    assert settings.database_url == "postgresql+psycopg://user:pw@host/db?sslmode=require"


def test_sqlite_url_is_left_alone() -> None:
    settings = Settings(_env_file=None, database_url="sqlite:////app/db/magazine.db")

    assert settings.database_url == "sqlite:////app/db/magazine.db"
