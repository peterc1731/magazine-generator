# Magazine Generator — Testing Strategy

## 1. Philosophy

This is a personal-scale project, so the goal isn't exhaustive coverage —
it's confidence that each piece built in `TASKS.md` actually works before
moving to the next, without a manual "run the whole pipeline and eyeball
the ePub" cycle every time. Two things make that non-trivial here:

- The pipeline talks to several **external, uncontrolled surfaces**
  (news sites, newsletter archive pages, Guardian API, X API, Claude API)
  that can change shape at any time — this is the actual risk in the
  system, more than the orchestration code around it.
- Several stages are **inherently non-deterministic** (LLM classification,
  live web content) and can't be asserted on exactly.

So the strategy leans on: mock/record the external boundary for fast,
deterministic tests that run on every change, and keep a separate, sparser
layer that checks the real external world hasn't drifted out from under
those recordings.

**Definition of done for each phase in `TASKS.md` includes its tests** —
a phase isn't finished when the code runs once manually, it's finished
when there's an automated test that would catch it breaking later.

## 2. Test Layers

### 2.1 Unit tests
Pure logic, no I/O, fully mocked dependencies. Fast enough to run
constantly while building.
- Cursor/pagination logic per connector (`fetch_since` given a cursor
  returns only new items) against canned response objects.
- Extraction normalization (`RawItem` → `Article`) against saved HTML
  fixtures (see §4) — assert title/author/date/body extracted correctly,
  boilerplate stripped.
- Dedup clustering logic against synthetic embedding vectors (no real
  embedding calls).
- Classification response parsing (given a canned Claude response,
  correct scores/sections/status are assigned) and threshold filtering at
  boundary values.
- Cron/schedule computation (use `time-machine`/`freezegun` to control the
  clock rather than waiting on real time).
- OPDS catalog XML generation against expected structure, independent of
  file serving.
- ePub builder output structure (chapter count, TOC entries, manifest
  images) given a fixed set of `Article` objects — reopen the generated
  file with `ebooklib` and assert on it. Deterministic and fully offline,
  so it belongs here even though it exercises a "real" library.

### 2.2 Integration tests
Multiple components together, against a real (temp) SQLite DB and
recorded/mocked external responses — still fully offline and
deterministic, but exercising real wiring.
- Connector → extraction → DB: run a connector against a recorded fixture
  and assert the right `articles` rows land in a real test DB.
- Classification → DB: run the classification pipeline against a small
  fixed article set with a mocked Claude client, assert `status`/`section`
  updates persist correctly.
- Issue generation: build an ePub from DB-backed articles, assert a row
  lands in `issues` with a valid file reference.
- OPDS + web routes: use FastAPI's `TestClient`/`httpx.AsyncClient` against
  the app with a test DB — source CRUD, schedule updates, run history,
  OPDS catalog + download routes, basic-auth enforcement.
- Worker orchestration: trigger a full run with all external calls mocked,
  assert `job_runs` is created/updated correctly and that **one connector
  raising doesn't abort the others** (this is a specific architectural
  guarantee from `ARCHITECTURE.md` §6 worth testing directly, not just
  hoping the `try/except` is right).

### 2.3 End-to-end (e2e) — offline
The full weekly pipeline, start to finish, with every external call
mocked (HTTP for sources, Claude API, X OAuth) but everything internal
real: real DB, real extraction, real classification-response parsing,
real ePub bytes, real OPDS route serving those bytes over HTTP. Asserts
the system as a whole works, not just its parts. Fully deterministic and
offline, so it runs on every push like the rest.

### 2.4 External contract / drift checks — separate, sparser layer
Because the fragile part of this system is "does the real Guardian API /
BBC RSS / newsletter archive page / X API still look like our fixtures
assume," keep a small, separate suite that hits the **real** external
services:
- Guardian API: one real call, assert the response shape still matches
  what the connector expects.
- BBC RSS: fetch the real feed, assert it parses.
- Dense Discovery / bytes.dev archive pages: fetch the real page, assert
  the issue-link selector still finds entries (this is the one most
  likely to silently break — a site redesign won't throw an exception, it
  will just stop finding issues).
- X API: a minimal authenticated call (e.g. fetch 1 bookmark) to catch
  auth/scope/endpoint changes.
- Claude API: a real call with a fixed prompt, sanity-checked against
  loose expectations (e.g. "response is valid JSON with an expected key"),
  not exact output — LLM output isn't asserted on precisely.

This suite is **not** part of the fast loop — see §5 for how it's run.
When it catches drift, the fix is usually: re-record the affected fixture
and update the parser/selector, not "the test was wrong."

## 3. Tooling

| Concern | Tool | Notes |
|---|---|---|
| Test runner | `pytest` (+ `pytest-asyncio`) | FastAPI routes and connectors are async |
| HTTP mocking/recording | `respx` (httpx) or `vcrpy` | Record real responses once into cassettes, replay in CI — this is what keeps connector/extraction tests realistic without live calls |
| Time control | `time-machine` | For cron/schedule logic without real waits |
| Test DB | SQLite temp file or `:memory:` via SQLAlchemy | Matches production DB engine, no separate test infra |
| API test client | FastAPI `TestClient` / `httpx.AsyncClient` | For route-level integration tests |
| Coverage | `pytest-cov` | Reported in CI, not gated on a hard threshold given project size |
| Test data | Plain fixtures/factories (`pytest` fixtures, or `factory_boy` if models get complex) | Keep simple until it isn't |

## 4. Test Data & Fixtures

- `tests/fixtures/html/` — saved real HTML pages (one BBC article, one
  Guardian API response, one newsletter archive index + one issue page,
  a JS-rendered example for the Playwright fallback) used by extraction
  unit tests.
- `tests/fixtures/cassettes/` — recorded HTTP interactions (via
  `respx`/`vcrpy`) for connector and classification integration tests.
- `tests/fixtures/claude_responses/` — canned Claude API responses for
  classification parsing tests.
- **Refresh process**: fixtures/cassettes are checked into the repo and
  don't expire on their own — they're refreshed manually when the drift
  suite (§2.4) catches a mismatch, or periodically on suspicion of a site
  change. A short script (`scripts/refresh_fixtures.py` or similar, added
  when the connectors exist) re-fetches real content and overwrites the
  relevant fixture/cassette.

## 5. CI Structure

- **Fast suite** (unit + integration + offline e2e, §2.1-2.3): runs on
  every push/PR. Fully mocked, no network, no API costs, no flakiness
  from real sites. This is the loop for "verify incrementally as we
  build."
- **Drift suite** (§2.4): runs on a schedule (e.g. weekly) and can also be
  triggered manually before/after touching a connector. Not required to
  pass for a PR to merge — a failure here means "go re-check that source,"
  not "the code is broken." Failures should surface as a notification
  (same failure channel as job-run failures, per `ARCHITECTURE.md` §9)
  rather than blocking work.
- Live-LLM and live-X-API calls in the drift suite cost real money/quota,
  so they're deliberately infrequent (scheduled, not per-commit) and
  minimal (one call each, not a full run).

## 6. Mapping to the Task List

Each phase in `TASKS.md` should add its own tests as it's built, not as a
follow-up phase:
- Phase 1 (data layer) → model/query unit tests against a test DB.
- Phase 2 (first end-to-end slice) → this is also where the fixture/
  cassette pattern and the offline e2e harness get established, since
  everything after it reuses them.
- Phase 3 (remaining connectors) → each new connector ships with its own
  fixture + cursor/pagination unit tests, and one entry in the drift suite.
- Phase 4 (classification) → parsing/threshold unit tests with canned
  responses; one drift-suite entry for a real Claude call.
- Phase 5 (ePub generation) → structural assertions on generated output.
- Phase 6 (orchestration) → the error-isolation and `job_runs` integration
  tests described in §2.2.
- Phase 7 (OPDS) → catalog/route tests, plus a manual (not automatable)
  check against the actual e-reader noted in the phase itself.
- Phase 8 (web UI) → route-level integration tests for each new page/action.
- Phase 9 (deployment) → out of scope for this test strategy; validated by
  the phase's own "confirm e-reader can pull the issue" step.

## 7. What's Explicitly Not Automated

- Whether the generated ePub *looks good* and reads well on the actual
  e-reader (Phase 2 and Phase 7 call this out as a manual check).
- Whether classification results *feel* right against personal taste —
  this is tuned by using the system (Phase 10), not asserted in a test.
- Exact LLM output — only structural/shape expectations are tested, never
  exact generated text.
