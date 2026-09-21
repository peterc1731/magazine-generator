# Magazine Generator — Product Requirements Document

## 1. Vision

Turn a personal reading list — news sites, email newsletters, and X bookmarks —
into a single weekly ePub "magazine" that lands on an e-reader via OPDS, already
filtered and grouped for what the reader actually cares about. The goal is to
replace ad-hoc browsing and inbox triage with one curated, distraction-free
reading session per week.

## 2. Problem Statement

Interesting content arrives scattered across an inbox, a phone feed, and a
handful of news sites, each with its own ads, popups, and irrelevant stories.
There's no single place to read it, and no filter for significance or personal
relevance. An e-reader is a great distraction-free reading device, but nothing
gets it there automatically, cleanly, and pre-filtered.

## 3. Goals

- Automatically pull content weekly from a defined set of sources.
- Extract clean, readable article content (strip ads/boilerplate, keep
  structure, capture metadata: title, author, source, date, URL).
- Filter and group content by significance and personal interest, using AI
  classification against a user-defined interest profile.
- Package the result as a well-structured ePub "issue" (cover, sections,
  table of contents).
- Serve issues to an e-reader through a standard OPDS catalog.
- Let the user manage sources, review past issues, and control the schedule
  through a web UI.

## 4. Non-Goals (for now)

- Multi-user support — this is a single-reader system.
- Real-time/continuous delivery — weekly cadence only.
- Full-text search across historical issues (nice-to-have, not MVP).
- Replacing the newsletters' own web archives or the original sites — this is
  a personal digest, not a publishing platform.
- Perfect X ingestion via the official firehose/streaming API — see §9 open
  questions.

## 5. User

One user (the project owner), reading on one e-reader that supports OPDS
catalogs with HTTP basic auth.

## 6. Initial Sources

| Source | Type | Notes |
|---|---|---|
| Dense Discovery | Web archive scrape | No RSS feed; all past issues are published on the site — scrape the issue archive/index page |
| bytes.dev | Web archive scrape | No RSS feed; all past issues are published on the site — scrape the issue archive/index page |
| BBC News | RSS + web scrape | Full article body not in RSS, needs extraction |
| The Guardian | API | Use the free Guardian Open Platform API for clean article bodies |
| X (personal feed) | Bookmarks (X API v2) | User bookmarks threads/articles on X; scraper pulls bookmarks added since the last issue via the official Bookmarks API (OAuth 2.0 user-context, pay-per-use pricing — see Architecture doc §5.4) |

Sources must be pluggable — the user should be able to add/remove/pause
sources from the web UI without a code change for common source types
(RSS, API-backed, email-based).

## 7. MVP Feature Set

### 7.1 Source management (Web UI)
- List, add, edit, enable/disable sources.
- Per-source config: type (RSS/API/email/bookmarks), URL/credentials,
  fetch frequency override, category/tag hint.
- Manual "test fetch" action to sanity-check a source before the next run.

### 7.2 Content ingestion & extraction
- Fetch new items per source since the last successful run.
- Extract clean article content: strip ads, nav, popups, tracking pixels;
  preserve headings/paragraphs/images/links; capture title, author, byline,
  publish date, source, canonical URL.
- Deduplicate near-identical coverage of the same story across sources.
- Cache raw + cleaned content so a run can be re-processed without
  re-fetching.

### 7.3 Curation & classification (AI-assisted)
- User maintains an editable "interest profile" (free text + explicit
  topics/keywords) in the web UI.
- Each candidate article is scored for relevance/significance against the
  profile and tagged with a section/category.
- Articles below a configurable relevance threshold are excluded from the
  issue (but remain visible in the UI as "skipped this week").
- Included articles are grouped into sections (e.g. Tech, World News,
  Newsletters) for the issue's table of contents.

### 7.4 Issue generation (ePub)
- One ePub "issue" per run, with:
  - a generated cover (issue date/number)
  - a table of contents grouped by section
  - one chapter per article with title, byline/source/date, and cleaned body
  - images re-hosted/embedded in the ePub (not hot-linked)
- Issues are versioned/dated and stored for later retrieval.

### 7.5 Distribution (OPDS)
- OPDS catalog listing generated issues, newest first, each with cover
  thumbnail and download link.
- Reachable over HTTPS with basic auth, compatible with the target e-reader's
  OPDS client.

### 7.6 Scheduling
- User sets/edits the run schedule (default: weekly) from the web UI.
- Manual "run now" trigger for testing or an out-of-band issue.
- Run history visible in the UI: status, start/end time, articles
  found/included/excluded, errors.

### 7.7 Issue history
- Web UI page listing past issues with basic stats (article count, sections,
  size) and a re-download/regenerate option.

## 8. Success Criteria

- A new issue is generated and downloadable via OPDS every week without
  manual intervention, for all sources except X.
- Article content is clean enough to read without noticing ads, cookie
  banners, or nav cruft in >90% of included articles.
- The included/excluded split feels right without manual tuning after the
  first few weeks of adjusting the interest profile.
- Adding a new RSS-based or API-based source takes configuration only, no
  code changes.

## 9. Source Access — Resolved

Both open questions from the initial draft have been resolved:

- **X bookmarks ingestion**: uses the official X API v2 Bookmarks endpoint
  (`GET /2/users/:id/bookmarks`), authorized via a one-time OAuth 2.0 +
  PKCE user-context flow. As of Feb 2026, X moved to pay-per-use pricing
  with no free tier and no monthly minimum — at personal, weekly-digest
  volume (tens of bookmarks a week) this costs a few dollars a month, not
  the $100s/month legacy tier pricing originally assumed. Full details in
  Architecture doc §5.4.
- **Newsletter access**: neither Dense Discovery nor bytes.dev publish an
  RSS feed, but both publish every past issue on their website. The
  connector scrapes each newsletter's issue archive/index page for new
  issue URLs since the last run and extracts the issue page content
  directly — no email ingestion infrastructure needed for MVP. Full
  details in Architecture doc §5.3.

## 10. Remaining Risks

- **Paywalls**: BBC/Guardian are assumed accessible; any future source
  behind a hard paywall is out of scope unless the user has a personal
  subscription/cookie to use.
- **Archive page structure**: Dense Discovery's and bytes.dev's exact
  archive URL pattern/pagination need to be confirmed against the live
  site during implementation (see Architecture doc §5.3) — the scraping
  approach is sound, but site-specific selectors aren't finalized yet.
- **X API pricing/policy drift**: pay-per-use pricing and endpoint access
  rules have changed more than once in the past; the low weekly volume
  here should stay cheap, but worth a quick pricing sanity-check
  periodically rather than assuming it never changes.

## 11. Post-MVP / Nice-to-Have Extensions

- **Feedback loop**: thumbs up/down on articles in the web UI that nudges
  the interest profile/classification weights over time instead of relying
  purely on a static prompt.
- **Multiple issues per week / on-demand issue** for breaking news.
- **More source types**: podcasts (transcript + summary), YouTube channels,
  Reddit/HN, additional newsletters.
- **Per-article read tracking** (mark as read, reading time estimate).
- **Full-text search** across historical issues.
- **Alternate output formats**: Kindle-compatible (AZW3/MOBI), PDF.
- **Digest email** as an alternative/additional delivery channel alongside
  OPDS.
- **Multi-profile support** (e.g. a "deep tech" week vs. a "light reading"
  week) selectable per run.
- **Smarter deduplication/merging**: combine multiple sources covering the
  same story into a single synthesized article with citations.
- **Mobile-friendly web UI** for reviewing/curating from a phone.
