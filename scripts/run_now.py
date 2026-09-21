"""Manually trigger one pipeline run, independent of the weekly schedule.

Runs the exact same code path as the scheduled job (app.worker.execute_run),
so there's nothing separate to keep in sync. Useful for testing a source or
interest-profile change, or for an out-of-band issue.

Usage: uv run python scripts/run_now.py
"""

import logging

from app.db import init_db
from app.worker import execute_run


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    init_db()
    execute_run()
    print("Run complete — check job_runs / the output directory for results.")


if __name__ == "__main__":
    main()
