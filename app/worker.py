import functools
import logging
from collections.abc import Callable

import anthropic
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models import JobStatus
from pipeline.notifications import notify_failure
from pipeline.orchestrator import run_pipeline
from pipeline.settings_store import get_cron_expression

logger = logging.getLogger(__name__)

JOB_ID = "weekly-run"


def execute_run(session_factory: Callable[[], Session] = SessionLocal) -> None:
    """Runs one pipeline cycle end-to-end and notifies on failure or empty
    output (ARCHITECTURE.md §6, §9). This is the single code path for both
    the scheduled job and the manual "run now" trigger (scripts/run_now.py)
    — there's no separate logic to keep in sync between the two.
    """
    settings = get_settings()
    db = session_factory()
    try:
        anthropic_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        job_run = run_pipeline(db, anthropic_client, settings)

        if job_run.status == JobStatus.FAILED or job_run.articles_included == 0:
            message = (
                f"Magazine run {job_run.status.value}: "
                f"{job_run.articles_included} article(s) included."
            )
            if job_run.error_summary:
                message += f" Errors: {job_run.error_summary}"
            notify_failure(message, settings.ntfy_topic)
    finally:
        db.close()


def build_scheduler(
    scheduler_cls: type = BackgroundScheduler,
    session_factory: Callable[[], Session] = SessionLocal,
) -> BackgroundScheduler:
    """Builds (but does not start) a scheduler with the weekly job wired up,
    reading the cron expression from settings at build time. Editing the
    schedule via the (future) web UI requires rebuilding/restarting this
    worker to pick it up — a live-reschedule endpoint is a Phase 8 concern.
    """
    db = session_factory()
    try:
        cron_expression = get_cron_expression(db)
    finally:
        db.close()

    scheduler = scheduler_cls()
    scheduler.add_job(
        functools.partial(execute_run, session_factory=session_factory),
        CronTrigger.from_crontab(cron_expression),
        id=JOB_ID,
    )
    return scheduler


def run_worker() -> None:
    """Entry point for the standalone worker process."""
    scheduler = build_scheduler(scheduler_cls=BlockingScheduler)
    logger.info("Starting scheduler")
    scheduler.start()  # blocks until interrupted


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_worker()
