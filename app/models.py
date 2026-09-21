import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


class SourceType(enum.StrEnum):
    RSS = "rss"
    GUARDIAN_API = "guardian_api"
    WEB_ARCHIVE = "web_archive"
    X_BOOKMARKS = "x_bookmarks"


class ArticleStatus(enum.StrEnum):
    PENDING = "pending"
    INCLUDED = "included"
    EXCLUDED = "excluded"


class JobStatus(enum.StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[SourceType] = mapped_column(Enum(SourceType), nullable=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(default=True)
    last_cursor: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    articles: Mapped[list["Article"]] = relationship(back_populates="source")


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (UniqueConstraint("source_id", "content_hash", name="uq_article_source_hash"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    author: Mapped[str | None] = mapped_column(String, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    raw_content_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    cleaned_content_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    plaintext: Mapped[str | None] = mapped_column(Text, nullable=True)
    relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    section: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[ArticleStatus] = mapped_column(
        Enum(ArticleStatus), default=ArticleStatus.PENDING
    )
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    source: Mapped["Source"] = relationship(back_populates="articles")
    issue_links: Mapped[list["IssueArticle"]] = relationship(back_populates="article")


class Issue(Base):
    __tablename__ = "issues"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    issue_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    file_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    cover_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    article_count: Mapped[int] = mapped_column(Integer, default=0)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    articles: Mapped[list["IssueArticle"]] = relationship(
        back_populates="issue", order_by="IssueArticle.chapter_order"
    )


class IssueArticle(Base):
    __tablename__ = "issue_articles"

    issue_id: Mapped[str] = mapped_column(ForeignKey("issues.id"), primary_key=True)
    article_id: Mapped[str] = mapped_column(ForeignKey("articles.id"), primary_key=True)
    section: Mapped[str | None] = mapped_column(String, nullable=True)
    chapter_order: Mapped[int] = mapped_column(Integer, default=0)

    issue: Mapped["Issue"] = relationship(back_populates="articles")
    article: Mapped["Article"] = relationship(back_populates="issue_links")


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.RUNNING)
    articles_found: Mapped[int] = mapped_column(Integer, default=0)
    articles_included: Mapped[int] = mapped_column(Integer, default=0)
    articles_excluded: Mapped[int] = mapped_column(Integer, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
