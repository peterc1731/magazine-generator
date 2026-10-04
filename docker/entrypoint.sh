#!/bin/sh
set -e

# Idempotent — safe to run on every container start, including the worker
# alongside the web service, without needing to coordinate startup order.
# The Cloud Run deployment sets RUN_MIGRATIONS_ON_START=false and runs
# migrations as a separate job step before rolling out new code instead.
if [ "${RUN_MIGRATIONS_ON_START:-true}" = "true" ]; then
    alembic upgrade head
fi

exec "$@"
