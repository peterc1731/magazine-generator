from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, JobStatus
from app.worker import JOB_ID, build_scheduler, execute_run
from pipeline import settings_store


@pytest.fixture
def session_factory(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path}/worker-test.db")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


def test_build_scheduler_reads_default_cron_expression(session_factory) -> None:
    scheduler = build_scheduler(scheduler_cls=BackgroundScheduler, session_factory=session_factory)

    job = scheduler.get_job(JOB_ID)
    assert job is not None
    assert str(job.trigger.fields[5]) == "8"  # hour field, matches DEFAULT_CRON_EXPRESSION


def test_build_scheduler_picks_up_custom_cron_expression(session_factory) -> None:
    with session_factory() as db:
        settings_store.set_cron_expression(db, "0 6 * * *")

    scheduler = build_scheduler(scheduler_cls=BackgroundScheduler, session_factory=session_factory)

    job = scheduler.get_job(JOB_ID)
    assert str(job.trigger.fields[5]) == "6"


@patch("app.worker.notify_failure")
@patch("app.worker.run_pipeline")
@patch("app.worker.anthropic.Anthropic")
def test_execute_run_notifies_on_failure(
    mock_anthropic: MagicMock,
    mock_run_pipeline: MagicMock,
    mock_notify: MagicMock,
    session_factory,
) -> None:
    mock_run_pipeline.return_value = MagicMock(
        status=JobStatus.FAILED, articles_included=0, error_summary="boom"
    )

    execute_run(session_factory=session_factory)

    assert mock_notify.called
    message = mock_notify.call_args[0][0]
    assert "boom" in message


@patch("app.worker.notify_failure")
@patch("app.worker.run_pipeline")
@patch("app.worker.anthropic.Anthropic")
def test_execute_run_does_not_notify_on_success_with_articles(
    mock_anthropic: MagicMock,
    mock_run_pipeline: MagicMock,
    mock_notify: MagicMock,
    session_factory,
) -> None:
    mock_run_pipeline.return_value = MagicMock(
        status=JobStatus.SUCCESS, articles_included=3, error_summary=None
    )

    execute_run(session_factory=session_factory)

    assert not mock_notify.called
