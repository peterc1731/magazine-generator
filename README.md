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

There are two supported ways to deploy this:

- **Google Cloud Run (recommended).** Serverless: the web UI/OPDS
  catalog scales to zero, the weekly run is a Cloud Run Job started by
  Cloud Scheduler, and everything is defined in `deploy/terraform/` and
  deployed by `.github/workflows/deploy.yml` on every push to `main`.
  Fits inside GCP's free tiers at this project's scale.
- **A VM running Docker Compose.** One persistent machine, SQLite on a
  volume, no code or infra tooling beyond Docker. See
  [Deploying to a VM with Docker Compose](#deploying-to-a-vm-with-docker-compose).

### Deploying to Google Cloud Run

What gets deployed (all in `deploy/terraform/`):

| Piece | GCP resource |
|---|---|
| Web UI + OPDS | Cloud Run service `magazine-web` (public URL, HTTPS built in; app-level basic auth gates access) |
| Weekly pipeline run | Cloud Run Job `magazine-pipeline`, started by Cloud Scheduler on `schedule` in `deploy/terraform/variables.tf` |
| Schema migrations | Cloud Run Job `magazine-migrate`, run by the deploy workflow before each rollout |
| Database | External Postgres — [Neon](https://neon.tech)'s free tier (scales to zero) is the intended choice |
| Article HTML, covers, epubs | Cloud Storage bucket, mounted into the service and jobs at `/mnt/storage` |
| Secrets | The whole production `.env`, as one Secret Manager secret (`magazine-env`), mounted as a file |
| Images | Artifact Registry repo `magazine` |
| CI → GCP auth | Workload Identity Federation (no service account keys in GitHub), restricted to this repo's `main` branch |

The deploy workflow runs tests (`ci.yml`, including against Postgres),
`terraform apply`, builds and pushes the image, runs migrations, then rolls
the new image out to the pipeline job and the web service, and finally
hits `/health`.

I validated the Terraform (`terraform validate` and an offline `terraform
plan` — 39 resources, no errors), built the image, and ran it locally the
way Cloud Run will (Postgres, `.env` mounted at `/secrets/env`, migrations
as a separate container, then the web service and a pipeline run). I did
**not** run any of this against a real GCP project — no cloud account
access from this environment — so the first real `bootstrap.sh` run is the
first time it touches GCP.

#### 1. One-time setup

Prerequisites: [gcloud](https://cloud.google.com/sdk/docs/install) and
[Terraform](https://developer.hashicorp.com/terraform/install) (>= 1.6)
installed locally.

1. **Create a GCP project** with billing linked (needed even to use the
   free tiers). Use a project dedicated to this app — the deployer service
   account gets admin-level roles in it (see `deploy/terraform/github.tf`).
2. **Create a Postgres database.** On Neon: create a project (any region;
   one near your Cloud Run region is nicer), and copy the connection string
   (`postgresql://...?sslmode=require`). It works as-is — the app swaps in
   the right driver.
3. **Authenticate locally:**
   ```bash
   gcloud auth login
   gcloud auth application-default login
   ```
4. **Optionally edit `deploy/terraform/variables.tf`** — `schedule` and
   `time_zone` for the weekly run (defaults: Monday 08:00 UTC), `region`
   (default `us-central1`; stay in us-central1/us-east1/us-west1 to keep
   the bucket in Cloud Storage's free tier). Commit any change.
5. **Run the bootstrap script** (creates the Terraform state bucket and
   applies the Terraform once with your own credentials):
   ```bash
   deploy/bootstrap.sh <project-id> [region]
   ```
   If the first apply fails on a permission error for the new service
   accounts, that's usually IAM propagation lag — wait a minute and rerun.
6. **Upload the production `.env`.** Start from `.env.example`, fill in
   API keys and X tokens as covered above, set `DATABASE_URL` to the Neon
   connection string, and **set `OPDS_BASIC_AUTH_USER`/`PASSWORD`** — the
   service is publicly reachable. Leave `DATA_DIR`/`ISSUES_DIR` alone and
   skip `DOMAIN` (both are set by the deployment / not used). Then:
   ```bash
   gcloud secrets versions add magazine-env --project <project-id> --data-file=.env.production
   ```
   (`.env.production` is gitignored.)
7. **Set the GitHub repository variables** the script printed (Settings →
   Secrets and variables → Actions → *Variables* tab, not Secrets — none of
   them are sensitive): `GCP_PROJECT_ID`, `GCP_REGION`, `TF_STATE_BUCKET`,
   `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_DEPLOYER_SERVICE_ACCOUNT`.
8. **Deploy:** push to `main`, or run the *Deploy* workflow manually from
   the Actions tab.

#### 2. Verify

`terraform -chdir=deploy/terraform output web_url` gives the service URL
(`https://magazine-web-....run.app`).

- `curl https://<url>/health` → `{"status":"ok"}`
- `https://<url>/ui/sources` → the web UI, behind basic auth. Seed the
  default sources by running `scripts/seed_dev_data.py` locally with
  `DATABASE_URL` pointed at the Neon database, or add them in the UI.
- Trigger a run from `/ui/runs` — on Cloud Run, "Run now" starts the
  pipeline job and returns immediately; refresh to watch it appear. Job
  logs are under Cloud Run → Jobs → `magazine-pipeline` in the console.
- Add `https://<url>/opds/` to your e-reader as an OPDS catalog. The first
  request after the service has been idle takes a few seconds (cold start).

#### Day to day

- **Deploying:** merge to `main`. Infra changes go in `deploy/terraform/`
  and are applied by the same workflow.
- **Changing the schedule:** edit `schedule`/`time_zone` in
  `deploy/terraform/variables.tf` and push. The cron field in
  `/ui/settings` is hidden on this deployment, since Cloud Scheduler owns it.
- **Changing secrets:** add a new version of `magazine-env` (same command
  as step 6). Every pipeline run reads the latest version; a running web
  instance keeps the settings it started with until it's replaced, which
  happens on the next deploy or whenever it scales to zero.
- **X tokens:** after the first refresh, the current X access/refresh
  tokens live in the database (`settings` table), not the `.env`, because
  X rotates the refresh token on every use. Re-running
  `scripts/x_oauth_setup.py` and uploading a `.env` with the new tokens
  takes over automatically.
- **Custom domain:** the `run.app` URL works as-is. For your own domain,
  Cloud Run domain mappings (available in a subset of regions, including
  us-central1) or Firebase Hosting
  in front are the free options; the HTTPS load balancer route costs ~$18/mo.

### Deploying to a VM with Docker Compose

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

#### 1. Provision the server

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

#### 2. Point a domain at it

Caddy's automatic HTTPS needs a real domain — it can't issue a certificate
for a bare IP. If you don't already own one, a free option like
[DuckDNS](https://www.duckdns.org/) works fine for a personal project.
Create an A record (or DuckDNS subdomain) pointing at the static IP from
step 1, and confirm it resolves (`dig +short yourdomain.example`) before
continuing — Caddy will fail to get a certificate if DNS isn't live yet.

#### 3. Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # log out/in after this
```

#### 4. Get the code and configure it

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

#### 5. Build and start

```bash
docker compose build
docker compose up -d
docker compose logs -f   # watch startup; Ctrl-C to stop watching (containers keep running)
```

Each container runs migrations on startup (`docker/entrypoint.sh`) before
starting its actual process, so the DB schema is always current — no
separate migration step to remember.

#### 6. Verify

- `curl -u user:pass https://yourdomain.example/health` → `{"status":"ok"}`
- `https://yourdomain.example/ui/sources` in a browser → the web UI, prompting for basic auth
- `https://yourdomain.example/opds/` → the (empty, until the first run) OPDS catalog
- Trigger a first run from `/ui/runs` (or `docker compose exec worker python scripts/run_now.py`)
  and confirm an issue shows up in `/ui/issues` and `/opds/`
- Add `https://yourdomain.example/opds/` as an OPDS catalog on your
  e-reader (with the basic auth credentials) and confirm it can see and
  download the issue — **this last check needs your actual e-reader**, not
  something verifiable any other way.

#### Updating

```bash
git pull
docker compose build
docker compose up -d
```

#### Not covered here

Backups (the named volumes hold everything — `docker run --rm -v
magazine-generator_db:/data -v $(pwd):/backup alpine tar czf
/backup/db-backup.tar.gz /data` is a reasonable starting point), log
rotation, and monitoring beyond the ntfy.sh failure notifications from
Phase 6 are all left as follow-ups, not attempted here.
