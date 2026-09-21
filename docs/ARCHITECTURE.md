# Magazine Generator — Technical Architecture

## 1. Overview

Single-user, single-host system. A weekly scheduled job fetches content from
pluggable source connectors, extracts and cleans article content, classifies
it against a user interest profile with an LLM, assembles it into an ePub
"issue," and publishes it through an OPDS catalog. A web UI provides source
management, schedule control, and issue history on top of the same database.

```
                    ┌─────────────────────────────────────┐
                    │              Web App                 │
                    │  (FastAPI: REST API + server-rendered│
                    │   UI for sources / schedule / issues) │
                    └───────────────┬───────────────────────┘
                                    │ reads/writes
                                    ▼
                    ┌─────────────────────────────────────┐
                    │              SQLite DB                │
                    │  sources, articles, issues, job_runs  │
                    └───────────────┬───────────────────────┘
                                    ▲
                                    │ reads/writes
        ┌───────────────────────────┴───────────────────────────┐
        │                     Scheduler / Worker                  │
        │  (APScheduler process, triggered by cron expr in DB      │
        │   or manual "run now")                                   │
        └───────────────────────────┬───────────────────────────┘
                                    │ runs weekly pipeline
                                    ▼
   ┌───────────┐   ┌───────────────┐   ┌────────────────┐   ┌─────────────┐
   │  Source   │→→│  Extraction    │→→│ Classification  │→→│  ePub       │
   │ Connectors│   │  (trafilatura/ │   │ (Claude API,    │   │  Builder    │
   │ (plugins) │   │  Guardian API/ │   │  batch scoring) │   │ (ebooklib)  │
   └───────────┘   │  email parse)  │   └────────────────┘   └──────┬──────┘
                    └───────────────┘                                │
                                                                      ▼
                                                          ┌──────────────────┐
                                                          │  File storage      │
                                                          │ (local disk or R2) │
                                                          └────────┬───────────┘
                                                                   ▼
                                                          ┌──────────────────┐
                                                          │   OPDS Server      │
                                                          │ (catalog + files,  │
                                                          │  or Calibre server)│
                                                          └────────┬───────────┘
                                                                   ▼
                                                             e-reader (HTTPS
                                                             + basic auth)
```

## 2. Tech Stack Summary

| Concern | Choice | Why |
|---|---|---|
| Web API + UI | Python, FastAPI (+ Jinja2/HTMX or a small React admin panel) | One language across pipeline and web layer; minimal ceremony for a CRUD admin app |
| Scheduling | APScheduler, persistent job store in SQLite | Weekly cadence doesn't need Celery/Redis; survives restarts, schedule editable from DB |
| Extraction | `trafilatura` (primary), Playwright + readability.js (fallback for JS-rendered pages) | Best-maintained boilerplate-removal + metadata library available |
| Guardian content | Guardian Open Platform API (free tier) | Structured, clean article bodies — no scraping needed |
| Newsletter content | RSS/web-archive if published; otherwise inbound email via Cloudflare Email Routing/Mailgun → webhook → BeautifulSoup parse | Prefer RSS path; email path only as fallback |
| X bookmarks | X API v2 bookmarks endpoint, OAuth 2.0 user-context | Needs one-time OAuth flow (see §5.4) |
| Dedup/similarity | Embeddings (e.g. `voyage-3-lite` or similar) + cosine similarity clustering | Avoid classifying near-duplicate stories separately |
| Classification | Claude API, batched prompts (Haiku for bulk scoring) | Cheap, fast relevance scoring against a free-text interest profile |
| ePub generation | `ebooklib` (+ Pillow for cover generation) | Full control over chapters/sections/nav/metadata, unlike Pandoc |
| OPDS serving | Hand-rolled Atom/OPDS routes in FastAPI, **or** feed epubs into a Calibre library and use `calibre-server` | Calibre shortcut avoids writing/maintaining OPDS XML by hand |
| Database | SQLite via SQLAlchemy | Single user, weekly writes — no need for Postgres |
| File storage | Local disk volume, optionally Cloudflare R2/Backblaze B2 | Cheap, simple; DB stores metadata + path/URL only |
| Hosting | Single small VPS (Hetzner CX22 / DigitalOcean), Docker Compose | Always-on, cheap, full control; avoids serverless cold-start/storage complications |
| Reverse proxy / auth | Caddy, HTTPS + HTTP basic auth | Simplest access control the e-reader's OPDS client will support |
| Notifications | ntfy.sh or email on job failure | Lightweight, no extra infra |

## 3. Components

### 3.1 Web App
FastAPI app serving both the JSON API and the UI (server-rendered + HTMX for
interactivity, or a thin React panel if preferred). Responsibilities:
sources CRUD, interest-profile editing, schedule editing, run history view,
issue list/download links, manual "run now" and "test fetch" actions.

### 3.2 Scheduler / Worker
A long-running process (separate from the web process, same container or a
sibling one) hosting APScheduler. Reads the cron expression from the DB,
triggers the pipeline, and writes a `job_runs` row (status, timings, counts,
errors) for the UI to display. The web app can also enqueue an immediate run
by writing a "run requested" flag the worker polls, or via a direct call if
co-located.

### 3.3 Source Connectors (plugin interface)
Each source implements a common interface, e.g.:

```python
class SourceConnector(Protocol):
    def fetch_since(self, cursor: SourceCursor) -> list[RawItem]: ...
```

`RawItem` carries whatever the source naturally gives (RSS entry + link,
API JSON payload, email MIME body, bookmark tweet ID/URL) plus enough to
resume from (`cursor` — e.g. last-seen timestamp, last bookmark ID, RSS
`etag`/`Last-Modified`). Connector types for MVP:

- **RSSConnector** — generic, config = feed URL. Used for BBC and any
  newsletter that publishes a feed.
- **GuardianAPIConnector** — config = API key + section/query filters.
- **EmailConnector** — polls a webhook-fed inbox table populated by the
  inbound email provider; config = expected sender address(es).
- **XBookmarksConnector** — see §5.4.

### 3.4 Extraction Pipeline
Given a `RawItem`, produce a normalized `Article` (title, author, published_at,
source, canonical_url, cleaned_html, plaintext, images[]):
1. If the connector already provides clean structured content (Guardian API),
   skip extraction.
2. Otherwise fetch the full page and run `trafilatura.extract()` with
   metadata extraction enabled.
3. If extraction yields low-confidence/short output (JS-rendered page),
   retry via Playwright render + readability.js.
4. Download and re-host images referenced in the cleaned content so the
   ePub doesn't depend on live hotlinks.
5. Store raw + cleaned content in the DB/object storage keyed by a content
   hash, for caching and reprocessing.

### 3.5 Classification Pipeline
1. **Dedup**: embed each article's title+summary, cluster near-duplicates
   (cosine similarity above a threshold), keep the best/most complete
   version per cluster (or merge later as a nice-to-have).
2. **Scoring**: batch N articles into a single Claude prompt alongside the
   user's interest profile; ask for a relevance score (0-10), a
   include/exclude recommendation, and a section/category label per
   article. Batching keeps token cost down vs. one call per article.
3. **Selection**: articles above the configurable relevance threshold are
   marked `included`; the rest are marked `excluded` but retained in the DB
   for visibility in the UI.
4. **Grouping**: included articles are grouped by the assigned section for
   the issue's table of contents/chapter order.

### 3.6 ePub Builder
Takes the finalized, grouped article set for a run and builds the issue:
- Cover image generated with Pillow (issue date/number, simple design).
- One XHTML chapter per article: title, byline (source/author/date), body.
- Nav/TOC grouped by section.
- Embedded images added to the manifest.
- Output written to file storage; a row is created in `issues` with path,
  size, article count, and generation timestamp.

### 3.7 OPDS Server
Either:
- **(a) Hand-rolled**: FastAPI routes returning an OPDS-compliant Atom feed
  listing `issues` (title, updated, cover link, acquisition link to the
  ePub file), plus a route serving the ePub bytes; or
- **(b) Calibre-backed**: a post-generation step runs `calibredb add` to
  import the new ePub into a Calibre library, and `calibre-server` (run
  as a container) serves OPDS + covers + search natively.

Recommendation: start with (b) to avoid hand-writing/maintaining OPDS XML;
revisit (a) only if Calibre's catalog structure becomes limiting.

### 3.8 Storage
- **SQLite** tables (see §4) for all structured state.
- **File storage** (local volume or R2/B2) for generated ePubs, cached raw
  article HTML, and cover images. DB rows reference paths/URLs, not blobs.

## 4. Data Model (initial sketch)

- `sources`: id, name, type, config (JSON), enabled, last_cursor, created_at
- `articles`: id, source_id, canonical_url, content_hash, title, author,
  published_at, raw_content_ref, cleaned_content_ref, plaintext,
  relevance_score, section, status (`pending`/`included`/`excluded`),
  fetched_at
- `issues`: id, issue_date, file_ref, cover_ref, article_count, size_bytes,
  created_at
- `issue_articles`: issue_id, article_id, section, chapter_order (join table)
- `job_runs`: id, started_at, finished_at, status, articles_found,
  articles_included, articles_excluded, error_summary
- `settings`: key/value (interest profile text, relevance threshold, cron
  expression)

## 5. Source-Specific Notes

### 5.1 BBC News
RSS feed for discovery only (title/link/pubDate); fetch full article page
and run through the extraction pipeline (§3.4).

### 5.2 The Guardian
Guardian Open Platform API (free registration for a personal API key).
Query by section/tag, request `show-fields=body,byline,thumbnail`. Response
is already clean HTML — extraction step is skipped for this connector.

### 5.3 Newsletters (Dense Discovery, bytes.dev)
Spike first: check each for a public web archive or RSS feed of past
issues. If present, treat as an `RSSConnector` and run full extraction on
the archived issue page. If absent, use `EmailConnector`:
- Dedicated inbound address via Cloudflare Email Routing (or Mailgun/
  Postmark inbound parsing) forwarding to a webhook on the web app.
- Webhook stores the raw MIME message; a parser extracts the HTML body,
  strips tracking pixels/unsubscribe footers/social icons, and produces a
  cleaned `Article` directly (no trafilatura needed — the email IS the
  content).

### 5.4 X Bookmarks
User bookmarks threads/articles on X during the week; the connector pulls
bookmarks added since the last run's cursor.
- Requires the X API v2 `GET /2/users/:id/bookmarks` endpoint, which needs
  **OAuth 2.0 user-context** authorization (not an app-only bearer token) —
  a one-time OAuth flow where the user authorizes the app, with the
  resulting refresh token stored securely and refreshed automatically.
- API access tier requirements for this endpoint should be re-verified at
  implementation time (pricing/tier gating has changed repeatedly); treat
  this as a short validation spike before committing to the approach in
  the MVP.
- Cursor = last-seen bookmark ID; each new bookmark's tweet/thread URL is
  fetched and run through standard extraction (thread text pulled via the
  API response itself rather than scraping x.com).

## 6. Scheduling Design

`settings.cron_expression` (default weekly) is read by the APScheduler
process at startup and on every edit (the web app calls a "reschedule"
endpoint on the worker, or the worker polls for changes). Each firing:
1. Creates a `job_runs` row (`status=running`).
2. Runs connectors → extraction → classification → ePub build → publish,
   in sequence, with per-stage error isolation (one broken source shouldn't
   abort the whole run).
3. Updates the `job_runs` row with final counts/status/errors.
4. Sends a failure notification if the run errored or produced zero
   articles.

Manual "run now" from the UI takes the same code path, invoked directly
rather than waiting for the schedule.

## 7. Deployment

Single VPS, Docker Compose with services:
- `web` (FastAPI app)
- `worker` (APScheduler process, same image different entrypoint)
- `calibre-server` (if using the Calibre OPDS shortcut)
- `caddy` (reverse proxy, HTTPS via Let's Encrypt, HTTP basic auth)

Volumes: SQLite DB file, file storage directory (or R2/B2 credentials if
using object storage instead of local disk), Calibre library directory.

## 8. Security & Access

- OPDS + web UI both sit behind Caddy with HTTPS + HTTP basic auth —
  sufficient since this is a single-user system and the e-reader's OPDS
  client supports basic auth in the catalog URL.
- Secrets (Guardian API key, X OAuth client secret/refresh token, Claude
  API key, email webhook signing secret) stored as environment variables /
  Docker secrets, never committed.

## 9. Observability

- `job_runs` table + UI page is the primary observability surface.
- Failure notification via ntfy.sh (simple HTTP push) or email on any run
  that errors or completes with zero included articles.
- Structured logging (stdout, captured by Docker) for debugging individual
  connector/extraction failures.

## 10. Open Technical Risks

- X bookmarks API access tier/auth requirements (§5.4) — validate before
  building the connector.
- Newsletter RSS availability (§5.3) — validate before deciding whether the
  email-ingestion path is needed for MVP.
- JS-rendered pages requiring the Playwright fallback add latency/resource
  cost to the weekly run — worth capping per-source fetch time so one slow
  source doesn't block the whole issue.
