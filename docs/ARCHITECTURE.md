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
| Newsletter content | Scrape each newsletter's public issue archive page (trafilatura on each issue URL) | Neither Dense Discovery nor bytes.dev publish RSS, but both publish every past issue on their site — no email infra needed |
| X bookmarks | X API v2 Bookmarks endpoint (`GET /2/users/:id/bookmarks`), OAuth 2.0 user-context + PKCE | One-time OAuth flow, refresh token stored; pay-per-use pricing, no free tier — cheap at personal volume (see §5.4) |
| Classification + dedup | Claude API, batched prompts (`claude-haiku-4-5` for bulk scoring) | One batched call scores relevance and flags duplicate stories — no separate embeddings vendor/dependency |
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

- **RSSConnector** — generic, config = feed URL. Used for BBC.
- **GuardianAPIConnector** — config = API key + section/query filters.
- **WebArchiveConnector** — generic, config = archive/index page URL +
  a site-specific rule for extracting issue links and their dates/numbers
  from that page. Used for Dense Discovery and bytes.dev (see §5.3).
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
1. **Scoring + dedup**: batch N articles (ordered by source preference) into
   a single Claude prompt alongside the user's interest profile; ask for a
   relevance score (0-10), a section/category label, and a `duplicate_of`
   field per article — set on a later article when it covers the same story
   as an earlier one in the batch. Dedup rides along on this same call
   rather than being a separate embeddings/clustering step: it avoids a new
   vendor dependency, and an LLM judgment call handles "same story,
   different headline wording" across outlets at least as well as cosine
   similarity on embeddings would, at this batch's scale (tens of articles
   a week). Batching all articles into one call (instead of one call per
   article) keeps token cost down.
2. **Selection**: articles above the configurable relevance threshold are
   marked `included`; anything flagged `duplicate_of` another article is
   always `excluded`, regardless of its own score. The rest are marked
   `excluded` but retained in the DB for visibility in the UI.
3. **Grouping**: included articles are grouped by the assigned section for
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
Confirmed: neither publishes an RSS feed, but both publish every past
issue on their website (an issue archive/index page). No email-ingestion
infrastructure is needed for MVP — use a `WebArchiveConnector`:
- `fetch_since(cursor)` loads the archive/index page, lists issue links
  (and whatever date/number is exposed alongside each), and returns only
  issues newer than the cursor (last-seen issue URL or date).
- Each new issue's own page is then run through the standard extraction
  pipeline (§3.4, trafilatura) like any other web article — an issue page
  is just an article-shaped HTML page once ads/nav are stripped.
- The exact archive URL and pagination pattern differ per site and aren't
  nailed down yet — confirming those (and whether the archive page lists
  every issue or needs pagination through older ones) is a small
  implementation task, not an open design question: the connector
  contract above holds regardless of the site-specific selector details.
- `cursor` = the last-seen issue URL or published date per source, stored
  in `sources.last_cursor`.

### 5.4 X Bookmarks
User bookmarks threads/articles on X during the week; the connector pulls
bookmarks added since the last run's cursor, using the official
[X API v2 Bookmarks endpoints](https://docs.x.com/x-api/posts/bookmarks/introduction).

- **Endpoint**: `GET /2/users/:id/bookmarks`, paginated via `max_results`
  (cap 100) and `pagination_token` from the previous page's
  `meta.next_token`. Bookmarks are returned newest-first, scoped to the
  authenticated user only (there's no way to read anyone else's
  bookmarks, which matches the intended use exactly).
- **Auth**: requires **OAuth 2.0 user-context with PKCE** — an app-only
  bearer token is not sufficient. One-time authorization flow where the
  user logs in and grants the app scopes; the resulting access + refresh
  token pair is stored (refresh token used to mint new access tokens
  automatically, via the `offline.access` scope).
- **Scopes needed**: `tweet.read`, `users.read`, `bookmark.read`,
  `offline.access`.
- **Pricing**: as of Feb 2026 X retired tiered plans (Free/Basic/Pro) for
  new developers in favor of **pay-per-use credits** — no free tier, but
  also no monthly minimum/subscription. Reads are billed per call (on the
  order of $0.005/post read, $0.010/user read at time of writing; verify
  current rates in the X developer console before enabling billing).
  At this project's volume — a weekly check of a personal bookmarks list,
  likely tens of items — cost should land in the low single-digit
  dollars/month, not the $100s/month a legacy Basic-tier subscription
  would have implied. Credits must be purchased upfront in the developer
  portal before the first call.
- **Cursor**: last-seen bookmark ID; each new bookmark's post/thread
  content comes back directly in the API response (text, author, media),
  so no separate scrape of x.com is needed. If a bookmarked post links out
  to an external article, that URL is run through the standard extraction
  pipeline (§3.4) like any other web link.
- **Practical note**: pricing and access rules for this API have shifted
  more than once; treat the numbers above as directional and re-check the
  X developer console at implementation time rather than hardcoding this
  doc's figures into billing assumptions.

## 6. Scheduling Design

`settings.cron_expression` (default weekly) is read by the APScheduler
process at startup (`app/worker.py`). A schedule change made from the future
web UI takes effect on the next worker restart — a live-reschedule endpoint
that picks up an edit without restarting is deferred to Phase 8. Each firing:
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

Source access for all five initial sources is now resolved (§5.1-§5.4).
Remaining risks are implementation details rather than open design
questions:

- Dense Discovery's and bytes.dev's exact archive URL/pagination pattern
  need confirming against the live site when the `WebArchiveConnector` is
  built (§5.3).
- X API pay-per-use pricing/access rules have shifted before and may again
  — re-check current rates before enabling billing on the developer
  account (§5.4).
- JS-rendered pages requiring the Playwright fallback add latency/resource
  cost to the weekly run — worth capping per-source fetch time so one slow
  source doesn't block the whole issue.
