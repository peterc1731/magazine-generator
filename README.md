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
