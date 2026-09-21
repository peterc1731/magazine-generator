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
- [ ] Repo layout (`app/`, `connectors/`, `pipeline/`, `docs/`, etc.), package/dependency management (uv/poetry), lint/format config
- [ ] Config & secrets handling (env vars for API keys, `.env.example`)
- [ ] Base FastAPI app skeleton (no routes yet, just health check)
- [ ] CI: basic lint + test run on push

## Phase 1 — Data Layer
- [ ] SQLAlchemy models for `sources`, `articles`, `issues`, `issue_articles`, `job_runs`, `settings` (Architecture §4)
- [ ] Migrations setup (Alembic)
- [ ] Seed/fixture data for local dev

## Phase 2 — First End-to-End Slice (single source)
Goal: prove fetch → extract → ePub works before adding every source.
- [ ] Source connector interface (`SourceConnector` protocol, `RawItem`, cursor handling) — Architecture §3.3
- [ ] `GuardianAPIConnector` (simplest source — structured content, no extraction needed) — Architecture §5.2
- [ ] Extraction pipeline wrapper around trafilatura, `Article` normalization — Architecture §3.4
- [ ] Minimal ePub builder with ebooklib: one chapter per article, no sections/cover yet — Architecture §3.6
- [ ] Manual script/CLI to run the slice end-to-end and produce a real `.epub` file to sanity-check on the e-reader

## Phase 3 — Remaining Source Connectors
- [ ] `RSSConnector` for BBC News, incl. full-article fetch through the extraction pipeline — Architecture §5.1
- [ ] `WebArchiveConnector` for Dense Discovery — confirm archive URL/pagination pattern, implement issue-link discovery — Architecture §5.3
- [ ] `WebArchiveConnector` config for bytes.dev (reuse connector, site-specific selectors)
- [ ] `XBookmarksConnector`: OAuth 2.0 + PKCE authorization flow, token storage/refresh, bookmarks fetch + cursor — Architecture §5.4
- [ ] Set up X developer account/credits, do a small live test call before wiring into the pipeline

## Phase 4 — Curation & Classification
- [ ] Interest profile storage + a way to edit it (can be a raw settings row before the UI exists)
- [ ] Dedup: embeddings + similarity clustering across articles from different sources
- [ ] Claude batch classification: relevance scoring + section/category tagging against the interest profile — Architecture §3.5
- [ ] Inclusion threshold config + article status tracking (`pending`/`included`/`excluded`)

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
