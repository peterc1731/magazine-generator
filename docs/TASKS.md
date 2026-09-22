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
- [x] Dedup — decided against a separate embeddings step (considered Voyage AI, local sentence-transformers, and pure lexical matching; see chat history for the tradeoffs) in favor of **folding it into the classification call**: no new vendor/dependency, reuses a call already being made, and an LLM judgment call handles "same story, different headline wording" at least as well as cosine similarity would. `pipeline/classification.py`'s prompt now also asks for a `duplicate_of` field per article (pointing at the earlier article in the batch covering the same story); `pipeline/curation.py` excludes any article flagged as a duplicate regardless of its own relevance score. Callers must order `articles` by source preference so the preferred outlet's version wins. (The embeddings-based `pipeline/dedup.py` from the earlier approach was removed as dead code — never wired into anything — rather than left unused.)
- [x] Claude batch classification: relevance scoring + section/category tagging against the interest profile — Architecture §3.5 — `pipeline/classification.py`, model `claude-haiku-4-5`, one batched call per run (also does dedup, see above). Tested against a fake client (no live Anthropic calls in the test suite — that's the drift-suite's job later).
- [x] Inclusion threshold config + article status tracking (`pending`/`included`/`excluded`) — `pipeline/curation.py`, threshold from `settings_store`; duplicates are always excluded regardless of threshold

## Phase 5 — Full ePub Generation
- [x] Section-grouped table of contents / chapter ordering — `EpubArticleInput.section`, chapters grouped into nested `epub.Section` TOC entries in order of first appearance
- [x] Generated cover image (Pillow, issue date/number) — `_generate_cover_image`. Found and fixed a real bug while eyeballing the output: Pillow's bundled fallback font can't render "—", so the cover showed a broken glyph box; now prefers a real system TTF (DejaVu/Liberation, both present on this box) and normalizes dashes as a safety net if neither is installed on the deploy target.
- [x] Per-article byline/source/date front-matter in each chapter — unchanged from Phase 2, carried into the section-grouped structure
- [x] Image re-hosting: download and embed images referenced in cleaned content — `_rehost_images`: downloads each `<img>`'s bytes, adds them to the epub manifest, rewrites `src` to the local file; an image that fails to fetch or isn't a recognized image type is dropped rather than left as a dangling remote link. This closes the gap found during the real Guardian API run in Phase 2.

## Phase 6 — Job Orchestration
- [x] The actual pipeline wiring (not previously its own bullet, but needed to make the rest of this phase meaningful): `pipeline/orchestrator.py` — `run_pipeline()` fetches every enabled source, ingests new items (`pipeline/ingest.py`, dedup via the `(source_id, content_hash)` constraint from Phase 1, cleaned HTML written to disk via `pipeline/storage.py`), classifies all PENDING articles in one batch, and builds an ePub from newly-INCLUDED articles not already linked to a past issue. `pipeline/connector_factory.py` builds the right connector per `Source` row, pulling account-level secrets from settings rather than `source.config`.
- [x] APScheduler worker process, cron expression read from `settings` — `app/worker.py` (`build_scheduler`/`run_worker`), cron expression via `pipeline/settings_store.get_cron_expression`. Note: schedule changes require a worker restart to take effect — a live-reschedule endpoint is deferred to Phase 8 (web UI).
- [x] `job_runs` tracking (status, timings, counts, errors) around the full pipeline — `run_pipeline()` creates the row up front and finalizes status/counts/`error_summary` at the end
- [x] Per-stage error isolation (one broken source shouldn't kill the run) — verified with a real integration test (one working + one unmocked/broken RSS source in the same run: the broken one's error lands in `error_summary`, the working one's article still gets ingested/classified/published)
- [x] Manual "run now" trigger (callable independent of the schedule) — `scripts/run_now.py`, same code path as the scheduled job (`app.worker.execute_run`)
- [x] Failure notification (ntfy.sh or email) — `pipeline/notifications.py`, fires when a run fails or produces zero included articles (ARCHITECTURE.md §9)

Found and fixed a real bug while writing this phase's tests: `app/db.py`'s engine/session are bound once at import time from whatever `DATABASE_URL` was active then, so monkeypatching the env var per-test silently didn't redirect it — a test run leaked a real `magazine.db` file into the repo root. Fixed by making `app/worker.py`'s functions accept an injectable `session_factory` (same DI pattern used everywhere else in this codebase) instead of importing `SessionLocal` directly; cleaned up the leaked file (gitignored, never committed).

Verified end-to-end as a real script (not just library-level tests): ran `scripts/run_now.py` against a seeded `Source` row with the Guardian connector mocked and a fake Anthropic client, confirmed a real `job_runs` row, a real `Issue` row, and a valid, re-openable `.epub` with the right section grouping — the full CLI → worker → orchestrator → DB → ePub path, not simulated.

## Phase 7 — OPDS Server
- [x] Decide hand-rolled vs. Calibre-backed (Architecture §3.7) and spike the chosen approach — went hand-rolled; this dev environment can't install/verify a Calibre binary, and hand-rolled is fully testable with the same FastAPI `TestClient` tooling as the rest of the app. Calibre-backed remains an option for Phase 9 if the catalog proves limiting.
- [x] Catalog listing generated issues with cover + acquisition link — `app/opds.py`: `GET /opds/` (OPDS 1.2 Atom acquisition feed, newest issue first), `GET /opds/issues/{id}/download` (the epub), `GET /opds/issues/{id}/cover`. Verified the generated feed is well-formed XML with the right namespaces/link `rel`s by parsing it back.
- [x] HTTPS + basic auth in front of it — basic auth implemented in the app itself (`require_auth`, open access if unconfigured, matching how other optional settings behave); HTTPS termination is still Caddy's job at deploy time (Phase 9) — the app-level auth is defense in depth, not a replacement for that.
- [ ] Validate against the actual e-reader's OPDS client — **needs the user's real e-reader once this is deployed somewhere reachable (Phase 9)**; not something this environment can do.

## Phase 8 — Web UI
- [x] Source management: list/add/edit/enable/disable, per-source config forms — `app/web.py` + `app/templates/sources/`. Each source type gets its own fieldset (Guardian: section; RSS: feed_url; web archive: archive_url/link_selector/initial_fetch_limit; X bookmarks: none, credentials are account-level) shown/hidden with a small vanilla-JS toggle — no JSON blob to hand-edit. Type can't be changed after creation (delete-and-recreate instead) since each connector's config shape is different.
- [x] Manual "test fetch" action per source — `POST /ui/sources/{id}/test-fetch`, HTMX partial. Deliberately a preview only: doesn't persist articles or move `last_cursor`, verified by a test. Article titles come from external, untrusted sources, so the result is HTML-escaped — verified with a dedicated XSS-attempt test.
- [x] Interest profile editor — part of `/ui/settings`
- [x] Schedule editor (writes the cron expression the worker reads) — part of `/ui/settings`; still requires a worker restart to take effect (noted in the UI itself), per the Phase 6 limitation
- [x] Run history view (from `job_runs`) — `/ui/runs`
- [x] Issue history view (list, stats, re-download) — `/ui/issues`, cover thumbnail + download link reuse the Phase 7 OPDS routes directly rather than duplicating file-serving logic
- [x] Manual "run now" button wired to Phase 6 — `/ui/runs`, calls `app.worker.execute_run()` directly; blocks the request until the run finishes (no job queue — fine at this project's scale for an occasional manual click)

Found and fixed a real gap while writing the README: initially wrote up
`/ui/*` as sharing the OPDS basic-auth setting, then realized while
double-checking that claim that it wasn't actually true yet — `app/web.py`'s
router had no `require_auth` dependency at all, so the whole web UI (source
editing, run-now, everything) was wide open even with basic auth configured
for OPDS. Fixed by adding the same `require_auth` dependency at the router
level and added a dedicated test proving `/ui/*` now returns 401 without
credentials once configured.

Verified as a real running app, not just route-level tests: started the dev
server, seeded the 5 PRD sources, and fetched every page over HTTP — all
render correctly (checked the raw HTML, since this sandboxed environment has
no browser to screenshot against a locally running server). Exercised the
interactive bits for real: toggling a source's enabled state via the HTMX
partial swap, and "test fetch" against a real (blocked-by-this-environment)
network call, which correctly surfaced as a clean `403 Forbidden` message in
the UI rather than a crash — a genuine, non-mocked exercise of the
error-handling path. **Not verified**: the actual look/feel in a real
browser (interactive HTMX behavior, responsive layout) — that needs a human
with a browser, which this environment doesn't have.

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
