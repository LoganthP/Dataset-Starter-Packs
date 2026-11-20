# Deploying to Vercel

Everything runs from the Vercel link. The app needs one thing besides Vercel's own storage: a Neon Postgres database (free through the Vercel Marketplace).

| What | Where it runs |
| :--- | :--- |
| Pages, search, API | Vercel |
| **Starter-pack samples** (Bike Demand, Bengaluru Weather, Exoplanets, Dry Bean, Olist) and **dataset sample analyses** | **Vercel itself**: when you click Run, the site starts the job and the page shows progress (about 4 minutes maximum per run, `DSP_INLINE_BUDGET_SECONDS`) |
| **Large jobs**: full analyses of big datasets (up to 2 GB), real-data starter-pack runs | An optional **worker** (any always-on machine or hosted container). Without one, these runs say "Waiting for a worker" and start when one connects |

No Docker or PC needs to stay on for samples. Add a worker only if you want full analyses or real-data pack runs on the live site (step 6).

---

## 1. Create the Vercel project

1. Push this repository to GitHub.
2. Vercel → **Add New → Project** → import the repository. Leave **Root Directory** as the repository root and **Framework Preset** as detected (FastAPI). Don't change the build or output settings: `vercel.json` and `pyproject.toml` set them.
3. Deploy once. The site loads, but runs won't work yet.

## 2. Connect Neon Postgres (required)

1. Project → **Storage** → **Create Database** (or **Connect Store**) → **Neon**.
2. Tick **Production** (and **Preview** if you use previews). Leave the **environment variable prefix empty**, so it creates `DATABASE_URL`. (A custom prefix such as `STORAGE_` also works now, as long as there's only one.)
3. Check **Settings → Environment Variables** lists `DATABASE_URL` for **Production**.

## 3. Connect Vercel Blob (for uploads larger than 95 MB)

1. Project → **Storage** → **Create** → **Blob**. Choose **Private** access.
2. Connect it to **Production** (and Preview). This creates `BLOB_READ_WRITE_TOKEN`.

## 4. Add the remaining environment variables

Project → **Settings → Environment Variables**, environment **Production** (and Preview):

| Name | Value |
| :--- | :--- |
| `DSP_SECRET_KEY` | Generate once: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` and keep it. Changing it later disconnects saved Kaggle accounts. |
| `DSP_PUBLIC_URL` | `https://<your-project>.vercel.app` (needed for Kaggle sign-in) |
| Provider keys (optional) | See `.env.example` (e.g. `BRAVE_SEARCH_API_KEY`) |

Don't set `DSP_RUN_MODE`: Vercel uses `queue` automatically. On a **Pro** plan you can raise `maxDuration` in `vercel.json` (up to 800 s) and `DSP_INLINE_BUDGET_SECONDS` to match (keep it about 60 s below `maxDuration`).

## 5. Redeploy and check

Environment variables only apply to **new** deployments: **Deployments → ⋯ → Redeploy** on the latest production deployment.

Open these on your site:

| URL | Must show |
| :--- | :--- |
| `/api/health` | `"storage":"postgres"` and `"runMode":"queue"`. If it says `"sqlite"`, Neon isn't connected to Production; go back to step 2 and redeploy. |
| `/api/diagnostics` | Only the "no worker has connected" problem, until step 6 is done |

## 6. Optional: start a worker for large jobs

Skip this if samples are enough. The worker needs the **same values** as Vercel Production for these three variables:

```
DATABASE_URL=...            # from Vercel: Settings → Environment Variables → DATABASE_URL → reveal (or DATABASE_URL_UNPOOLED; same database)
BLOB_READ_WRITE_TOKEN=...
DSP_SECRET_KEY=...
```

Copy them with the Vercel CLI (`npm i -g vercel`, then in the repo: `vercel link` and `vercel env pull .env --environment=production`), or paste them into a `.env` file in the repo root by hand. **Never commit `.env`.**

### Option A: a hosted container service (no PC needed): Render, Railway, Fly.io, …

Create a **background worker** service from this repository's `Dockerfile` (no public port):

- **Start command:** `sh -c "cd /app/backend && exec python -m app.worker"`
- **Environment:** the three variables above
- Turn off any HTTP health check.

### Option B: Docker on your own computer or a VM

```bash
docker compose build app
docker compose run --rm worker python -m app.worker --doctor   # every line should be [ok] or [info]
docker compose --profile worker up -d --no-deps worker
docker compose logs -f worker                                  # "worker … polling every 2.0s (postgres)"
```

The worker only runs while that machine is on. Jobs submitted while it's off wait (up to `DSP_QUEUE_MAX_AGE_HOURS`, default 24) and start as soon as it's back.

### Option C: plain Python (no Docker)

```bash
cd backend
python -m venv .venv && . .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-api.txt -r requirements-packs.txt
python -m app.worker --doctor
python -m app.worker
```

## 7. Verify end to end

1. `/api/diagnostics?deep=1` shows `"ok": true` and `"inlineRuns": true` (a note says no worker is connected; that's fine for samples).
2. **Curated packs → Bengaluru Weather Explorer → Run on sample**: it runs on the site, shows charts, and they're still there after a refresh.
3. A Discover dataset → **Run sample** completes.
4. Upload a small CSV on a dataset's Run view: it uploads to Blob and is analyzed.
5. With a worker (step 6): `/api/worker/status` shows `"state":"online"`, and a **Full analysis** or **Real data** pack run completes.

## Troubleshooting

| Symptom | Cause | Fix |
| :--- | :--- | :--- |
| `/api/health` shows `"storage":"sqlite"` | `DATABASE_URL` missing for Production, or no redeploy since adding it | Step 2, then redeploy |
| "Waiting for a worker: none is connected" on a full analysis or real-data pack run | These are too large for the site itself | Start a worker (step 6) or use **Sample** |
| A sample run stays queued | The browser tab was closed before it started, or `/api/diagnostics` shows `inlineRuns:false` | Reopen the run page (it restarts); check `DATABASE_URL` is set for Production |
| Build fails with a size error | The Python bundle (about 450 MB with the starter-pack libraries) is over Vercel's limit | Add env `VERCEL_SUPPORT_LARGE_FUNCTIONS=1` (large functions), or set `DSP_INLINE_RUNS=0` and use a worker |
| "The worker and this app have different DATABASE_URL / BLOB_READ_WRITE_TOKEN / DSP_SECRET_KEY values" | Worker `.env` differs from Vercel Production | Copy the value from Vercel again and restart the worker |
| Upload says the token expired or was rejected | Wrong or rotated `BLOB_READ_WRITE_TOKEN` | Reconnect Blob in Vercel, redeploy, update the worker |
| Pack runs are disabled on the site | No database on this deployment | Step 2 and redeploy |
| `--doctor` says `[FAIL] Blob` | Token belongs to another store or was revoked | Use the Production token from Vercel |
