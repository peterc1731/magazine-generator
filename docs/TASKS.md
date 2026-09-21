# Magazine Generator — Task List

Working plan for building the system described in `PRD.md` and
`ARCHITECTURE.md`, broken into phases in roughly the order we'll build and
validate them. Each phase is a top-level task; as we start one, break it
into subtasks under it with more detail than we have right now.

Status legend: `[ ]` not started · `[~]` in progress · `[x]` done

Phases are ordered so we get one source end-to-end (fetch → extract →
build an ePub) before fanning out to every source, and get the pipeline
working headlessly before building the web UI on top of it.

## Phase 0 — Project Scaffolding
- [x] Repo layout (`app/`, `connectors/`, `pipeline/`, `docs/`, etc.), package/dependency management (uv), lint/format config — `pyproject.toml` (uv + ruff), `app/`, `connectors/`, `pipeline/`, `tests/`
- [x] Config & secrets handling (env vars for API keys, `.env.example`) — `app/config.py` (pydantic-settings), `.env.example`
- [x] Base FastAPI app skeleton (no routes yet, just health check) — `app/main.py`, `GET /health`
- [x] CI: basic lint + test run on push — `.github/workflows/ci.yml` (uv sync, ruff check, pytest)

## Phase 1 — Data Layer
- [x] SQLAlchemy models for `sources`, `articles`, `issues`, `issue_articles`, `job_runs`, `settings` (Architecture §4) — `app/models.py`
- [x] Migrations setup (Alembic) — `alembic/`, initial migration generated and verified against a clean DB
- [x] Seed/fixture data for local dev — `scripts/seed_dev_data.py` (idempotent, seeds the 5 PRD §6 sources)
- [x] Model unit tests — `tests/test_models.py`, `tests/conftest.py` (in-memory SQLite `db_session` fixture, per `TESTING.md` §2.1)

## Phase 2 — First End-to-End Slice (single source)
Goal: prove fetch → extract → ePub works before adding every source.
- [x] Source connector interface (`SourceConnector` protocol, `RawItem`, `FetchResult`, cursor handling) — Architecture §3.3 — `connectors/base.py`
- [x] `GuardianAPIConnector` (simplest source — structured content, no extraction needed) — Architecture §5.2 — `connectors/guardian.py`, tested against a recorded fixture response with `respx`
- [x] Extraction pipeline wrapper around trafilatura, `Article` normalization — Architecture §3.4 — `pipeline/extraction.py`, tested against a saved HTML fixture (boilerplate stripped, metadata extracted)
- [x] Minimal ePub builder with ebooklib: one chapter per article, no sections/cover yet — Architecture §3.6 — `pipeline/epub_builder.py`
- [x] Manual script/CLI to run the slice end-to-end and produce a real `.epub` file to sanity-check on the e-reader — `scripts/build_issue.py`. **Verified with a real `GUARDIAN_API_KEY` run** (user ran it locally after this environment's egress policy blocked the live Guardian API): produced a readable `.epub` with real articles, opened correctly. One follow-up found: articles have no images — `pipeline/epub_builder.py` doesn't embed images yet, so any `<img>` tags from Guardian's article HTML point at remote URLs an offline e-reader can't fetch. This is exactly the Phase 5 "image re-hosting" task below, not a bug in Phase 2.

## Phase 3 — Remaining Source Connectors
- [x] `RSSConnector` for BBC News, incl. full-article fetch through the extraction pipeline — Architecture §5.1 — `connectors/rss.py`, tested against a recorded feed + two article-page fixtures
- [x] `WebArchiveConnector` — generic connector (archive page → issue links → extraction), tested against fixtures — `connectors/web_archive.py`. **Archive URL/link-selector still unverified against the live sites** (egress to both domains is blocked in this environment) — `connectors/newsletters.py` docstring flags this explicitly; confirm before a real run.
- [x] `WebArchiveConnector` config for bytes.dev (reuse connector, site-specific selectors) — `connectors/newsletters.py` (same live-verification caveat as above)
- [x] `XBookmarksConnector`: OAuth 2.0 + PKCE authorization flow, token storage/refresh, bookmarks fetch + cursor — Architecture §5.4 — `connectors/x_oauth.py` (PKCE + token exchange/refresh), `connectors/x_bookmarks.py` (paginated fetch, stops at cursor, auto-refreshes on 401), all tested against mocked responses. `scripts/x_oauth_setup.py` is the one-time interactive flow to populate `.env`.
- [ ] Set up X developer account/credits, do a small live test call before wiring into the pipeline — **requires the user's own X developer account/credits; not something this environment can do.**

## Phase 4 — Curation & Classification
- [x] Interest profile storage + a way to edit it (can be a raw settings row before the UI exists) — `pipeline/settings_store.py`, backed by the `settings` table (also stores the relevance threshold)
- [x] Dedup: embeddings + similarity clustering across articles from different sources — `pipeline/dedup.py` (cosine similarity + greedy clustering, tested with synthetic vectors). **The embedding provider itself isn't wired up**: Anthropic has no first-party embeddings endpoint, and Voyage AI's current SDK/model name wasn't verified against live docs in this environment — `EmbeddingProvider` is a documented `Protocol` a real provider plugs into later, not a guessed implementation.
- [x] Claude batch classification: relevance scoring + section/category tagging against the interest profile — Architecture §3.5 — `pipeline/classification.py`, model `claude-haiku-4-5`, one batched call per run. Tested against a fake client (no live Anthropic calls in the test suite — that's the drift-suite's job later).
- [x] Inclusion threshold config + article status tracking (`pending`/`included`/`excluded`) — `pipeline/curation.py`, threshold from `settings_store`

## Phase 5 — Full ePub Generation
- [ ] Section-grouped table of contents / chapter ordering
- [ ] Generated cover image (Pillow, issue date/number)
- [ ] Per-article byline/source/date front-matter in each chapter
- [ ] Image re-hosting: download and embed images referenced in cleaned content

## Phase 6 — Job Orchestration
- [ ] APScheduler worker process, cron expression read from `settings`
- [ ] `job_runs` tracking (status, timings, counts, errors) around the full pipeline
- [ ] Per-stage error isolation (one broken source shouldn't kill the run)
- [ ] Manual "run now" trigger (callable independent of the schedule)
- [ ] Failure notification (ntfy.sh or email)

## Phase 7 — OPDS Server
- [ ] Decide hand-rolled vs. Calibre-backed (Architecture §3.7) and spike the chosen approach
- [ ] Catalog listing generated issues with cover + acquisition link
- [ ] HTTPS + basic auth in front of it
- [ ] Validate against the actual e-reader's OPDS client

## Phase 8 — Web UI
- [ ] Source management: list/add/edit/enable/disable, per-source config forms
- [ ] Manual "test fetch" action per source
- [ ] Interest profile editor
- [ ] Schedule editor (writes the cron expression the worker reads)
- [ ] Run history view (from `job_runs`)
- [ ] Issue history view (list, stats, re-download)
- [ ] Manual "run now" button wired to Phase 6

## Phase 9 — Deployment
- [ ] Dockerfiles for web/worker (+ Calibre server if used)
- [ ] Docker Compose stack, volumes for DB/file storage/Calibre library
- [ ] Caddy reverse proxy: HTTPS + basic auth
- [ ] VPS provisioning (Hetzner/DigitalOcean), secrets management
- [ ] First real scheduled run in production, confirm e-reader can pull the issue

## Phase 10 — Hardening
- [ ] Tune classification threshold / interest profile against a few real weekly runs
- [ ] Cap per-source fetch time so a slow/broken source can't block the whole run
- [ ] Basic logging/observability pass
- [ ] Review secrets handling and access control end-to-end

## Backlog (post-MVP, not scheduled)
Tracked in `PRD.md` §11 — pull individual items in here as phases once MVP is stable: feedback loop on classification, multiple issues/week, additional source types, read tracking, full-text search, alternate output formats, digest email delivery, multi-profile support, smarter cross-source dedup/merging, mobile-friendly UI.
