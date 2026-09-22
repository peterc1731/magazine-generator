#!/bin/sh
set -e

# Idempotent — safe to run on every container start, including the worker
# alongside the web service, without needing to coordinate startup order.
alembic upgrade head

exec "$@"
