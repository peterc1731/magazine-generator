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
