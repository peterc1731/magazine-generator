import os
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base

# Set TEST_DATABASE_URL (e.g. postgresql+psycopg://...) to run the DB-backed
# tests against a real Postgres instead of in-memory SQLite — CI does this to
# match the Cloud Run deployment's database.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    if TEST_DATABASE_URL:
        engine = create_engine(TEST_DATABASE_URL)
        Base.metadata.drop_all(bind=engine)
    else:
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)

    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        if TEST_DATABASE_URL:
            Base.metadata.drop_all(bind=engine)
        engine.dispose()
