# magazine-generator

Weekly ePub magazine generator: pulls from defined sources (news sites,
newsletters, X bookmarks), extracts and classifies articles against a
personal interest profile, builds an ePub issue, and serves it to an
e-reader over OPDS.

See `docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/TASKS.md`, and
`docs/TESTING.md` for the full design and build plan.

## Development

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-groups
cp .env.example .env  # fill in API keys as needed

uv run uvicorn app.main:app --reload   # dev server, GET /health to check
uv run pytest                          # tests
uv run ruff check .                    # lint

uv run alembic upgrade head             # apply migrations (creates magazine.db)
uv run python scripts/seed_dev_data.py  # seed the sources from docs/PRD.md §6 (idempotent)
```

After changing `app/models.py`, generate a migration with:

```bash
uv run alembic revision --autogenerate -m "describe the change"
```

### Build a real issue (Phase 2 end-to-end slice)

Requires `GUARDIAN_API_KEY` in `.env` (free key: https://open-platform.theguardian.com/access/).

```bash
uv run python scripts/build_issue.py --section technology --days 7
```

Writes an `.epub` to `output/`, fetching Guardian articles and running them
straight through the ePub builder (no DB persistence or classification yet —
that comes in later phases).

### X bookmarks connector setup

Once you have X API credits and an OAuth 2.0 app registered at
https://developer.x.com/ (redirect URI `http://127.0.0.1:8080/callback`),
set `X_CLIENT_ID` (and `X_CLIENT_SECRET` if your app is "confidential") in
`.env`, then run:

```bash
uv run python scripts/x_oauth_setup.py
```

Follow the printed instructions and paste the resulting `X_ACCESS_TOKEN`,
`X_REFRESH_TOKEN`, and `X_USER_ID` into `.env`.

### Running the real pipeline

Requires `ANTHROPIC_API_KEY` in `.env`, plus at least one enabled `Source`
(the seed script above adds the sources from `docs/PRD.md` §6).

```bash
uv run python scripts/run_now.py     # one manual run, independent of the schedule
uv run python -m app.worker          # standalone scheduler process (blocks; Ctrl-C to stop)
```

Both run the same pipeline (`pipeline/orchestrator.run_pipeline`): fetch
every enabled source, classify/dedup pending articles against the interest
profile (`pipeline/settings_store`), and build an `.epub` in `ISSUES_DIR`
from whatever's newly included. Check the `job_runs` table for status/counts
/errors from the last run. The schedule itself is a cron expression stored
in `settings` (`pipeline.settings_store.get_cron_expression`, default weekly
Monday 08:00) — edit it directly in the DB until the web UI (Phase 8) exists,
and restart the worker to pick up a change.

### OPDS catalog

With the dev server running (`uv run uvicorn app.main:app --reload`), point
an OPDS client (or `curl`) at:

```
GET /opds/               # catalog of generated issues, newest first
GET /opds/issues/{id}/download
GET /opds/issues/{id}/cover
```

Set `OPDS_BASIC_AUTH_USER`/`OPDS_BASIC_AUTH_PASSWORD` in `.env` to require
basic auth (left open if both are blank). HTTPS is a deploy-time concern
(Caddy, Phase 9) — the dev server here is plain HTTP.

### Web UI

With the dev server running, visit `/ui/sources` (or just `/ui/`, which
redirects there): manage sources (add/edit/enable/disable, per-type config
forms, a "test fetch" preview that doesn't touch the DB), edit the interest
profile/relevance threshold/cron schedule at `/ui/settings`, view run
history and trigger a manual run at `/ui/runs`, and browse generated issues
at `/ui/issues`. Same basic-auth setting as the OPDS catalog applies here
too (it's not currently split out separately).
