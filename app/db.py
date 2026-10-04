from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import Base

settings = get_settings()

if settings.database_url.startswith("sqlite"):
    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
else:
    # Serverless Postgres (Neon) drops idle connections when it scales to
    # zero, so check each pooled connection before handing it out.
    engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
