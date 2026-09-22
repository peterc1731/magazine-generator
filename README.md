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
from whatever's newly included. Check the `job_runs` table (or `/ui/runs`)
for status/counts/errors from the last run. The schedule itself is a cron
expression stored in `settings` — edit it at `/ui/settings` and restart the
worker to pick up a change.

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

## Deployment

Three containers, all built from the same image (`Dockerfile`): `web`
(FastAPI — OPDS + the UI), `worker` (the scheduler), and `caddy` (HTTPS
reverse proxy + automatic Let's Encrypt certs). One SQLite DB, shared
between `web` and `worker` via a named volume — fine at this project's
weekly-batch, low-concurrency scale (ARCHITECTURE.md §7).

I built and validated the Compose config (`docker compose config`) and
manually verified the exact migration/path behavior the containers depend
on, but couldn't run an actual `docker build`/`docker compose up` or
provision real Oracle infrastructure from this environment — no Docker
daemon or cloud account access here. The steps below are instructions to
follow, not something I ran end-to-end myself; if anything doesn't match,
that's the gap.

### 1. Provision the server

Any machine that can run Docker works; these steps assume Oracle Cloud's
Always Free tier (see the chat history in this project for why — it's a
genuine persistent VM, unlike sleep-based PaaS free tiers, and the free ARM
shape is wildly oversized for this workload).

1. Create an **Ampere A1 (ARM)** compute instance — 1 OCPU / 6GB RAM is
   plenty for this. Ubuntu 24.04 is the easiest image to find Docker
   documentation for.
2. **Reserve a static public IP** for the instance (free within the tier) —
   without this, the IP can change on reboot and break DNS.
3. **Open ports 80 and 443** in *both* places Oracle gates traffic — this
   trips up most first-time Oracle users:
   - Console → your VCN → Security Lists → Add Ingress Rules: TCP 80 and
     443 from `0.0.0.0/0`.
   - On the instance itself, Ubuntu images on OCI often ship with `iptables`
     rules that *also* block non-SSH inbound traffic by default. Check
     `sudo iptables -L INPUT -n` after provisioning; if 80/443 aren't
     accepted, add rules for them (e.g. `sudo iptables -I INPUT -p tcp
     --dport 80 -j ACCEPT`, same for 443) and persist them (`sudo
     netfilter-persistent save` if that's installed, otherwise check
     Ubuntu's current recommended way to persist iptables rules).

### 2. Point a domain at it

Caddy's automatic HTTPS needs a real domain — it can't issue a certificate
for a bare IP. If you don't already own one, a free option like
[DuckDNS](https://www.duckdns.org/) works fine for a personal project.
Create an A record (or DuckDNS subdomain) pointing at the static IP from
step 1, and confirm it resolves (`dig +short yourdomain.example`) before
continuing — Caddy will fail to get a certificate if DNS isn't live yet.

### 3. Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # log out/in after this
```

### 4. Get the code and configure it

```bash
git clone <this-repo-url>
cd magazine-generator
cp .env.example .env
```

Edit `.env`:
- Fill in `ANTHROPIC_API_KEY`, `GUARDIAN_API_KEY`, X credentials, etc. as
  covered above.
- Set `OPDS_BASIC_AUTH_USER`/`OPDS_BASIC_AUTH_PASSWORD` — don't deploy this
  publicly reachable without them.
- Set `DOMAIN` to the domain from step 2.
- **Override these three to the paths under the containers' mounted
  volumes** (the `.env.example` defaults are for local dev, where they
  resolve relative to the repo root instead):
  ```
  DATABASE_URL=sqlite:////app/db/magazine.db
  DATA_DIR=/app/data
  ISSUES_DIR=/app/output
  ```
  (Four slashes in `DATABASE_URL` is correct — three for `sqlite://` plus
  the leading `/` of the absolute path.)

### 5. Build and start

```bash
docker compose build
docker compose up -d
docker compose logs -f   # watch startup; Ctrl-C to stop watching (containers keep running)
```

Each container runs migrations on startup (`docker/entrypoint.sh`) before
starting its actual process, so the DB schema is always current — no
separate migration step to remember.

### 6. Verify

- `curl -u user:pass https://yourdomain.example/health` → `{"status":"ok"}`
- `https://yourdomain.example/ui/sources` in a browser → the web UI, prompting for basic auth
- `https://yourdomain.example/opds/` → the (empty, until the first run) OPDS catalog
- Trigger a first run from `/ui/runs` (or `docker compose exec worker python scripts/run_now.py`)
  and confirm an issue shows up in `/ui/issues` and `/opds/`
- Add `https://yourdomain.example/opds/` as an OPDS catalog on your
  e-reader (with the basic auth credentials) and confirm it can see and
  download the issue — **this last check needs your actual e-reader**, not
  something verifiable any other way.

### Updating

```bash
git pull
docker compose build
docker compose up -d
```

### Not covered here

Backups (the named volumes hold everything — `docker run --rm -v
magazine-generator_db:/data -v $(pwd):/backup alpine tar czf
/backup/db-backup.tar.gz /data` is a reasonable starting point), log
rotation, and monitoring beyond the ntfy.sh failure notifications from
Phase 6 are all left as follow-ups, not attempted here.
