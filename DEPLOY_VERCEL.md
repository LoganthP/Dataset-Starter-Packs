# Deploying to Vercel

The app has two parts that must share one Postgres database:

| Part | Runs on | Does |
| :--- | :--- | :--- |
| **Web app + API** | Vercel (one Python function + the built React app) | Search, pages, upload tokens; records analysis and pack-run jobs in Postgres |
| **Worker** | Any always-on machine or container (your PC with Docker, a VM, Render, Railway, Fly.io…) | Claims jobs from Postgres, downloads data, runs analyses and starter packs, saves reports and charts back to Postgres |

Vercel functions stop after 300 s and can't run the ML stack, so **nothing runs until a worker is connected**. The site says so ("Waiting for a worker: none is connected").

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

Don't set `DSP_RUN_MODE`: Vercel uses `queue` automatically.

## 5. Redeploy and check

Environment variables only apply to **new** deployments: **Deployments → ⋯ → Redeploy** on the latest production deployment.

Open these on your site:

| URL | Must show |
| :--- | :--- |
| `/api/health` | `"storage":"postgres"` and `"runMode":"queue"`. If it says `"sqlite"`, Neon isn't connected to Production; go back to step 2 and redeploy. |
| `/api/diagnostics` | Only the "no worker has connected" problem, until step 6 is done |

## 6. Start the worker

The worker needs the **same values** as Vercel Production for these three variables:

```
DATABASE_URL=...            # from Vercel: Settings → Environment Variables → DATABASE_URL → reveal (or DATABASE_URL_UNPOOLED; same database)
BLOB_READ_WRITE_TOKEN=...
DSP_SECRET_KEY=...
```

Copy them with the Vercel CLI (`npm i -g vercel`, then in the repo: `vercel link` and `vercel env pull .env --environment=production`), or paste them into a `.env` file in the repo root by hand. **Never commit `.env`.**

### Option A: Docker on your own computer or a VM

```bash
docker compose build app
docker compose run --rm worker python -m app.worker --doctor   # every line should be [ok] or [info]
docker compose --profile worker up -d --no-deps worker
docker compose logs -f worker                                  # "worker … polling every 2.0s (postgres)"
```

The worker only runs while that machine is on. Jobs submitted while it's off wait (up to `DSP_QUEUE_MAX_AGE_HOURS`, default 24) and start as soon as it's back.

### Option B: a hosted container service (Render, Railway, Fly.io, …)

Create a **background worker** service from this repository's `Dockerfile` (no public port needed):

- **Start command:** `sh -c "cd /app/backend && exec python -m app.worker"`
- **Environment:** the three variables above
- Turn off any HTTP health check; the worker doesn't serve web traffic.

### Option C: plain Python (no Docker)

```bash
cd backend
python -m venv .venv && . .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-api.txt -r requirements-packs.txt
python -m app.worker --doctor
python -m app.worker
```

## 7. Verify end to end

1. `/api/worker/status` shows `"state":"online"`.
2. `/api/diagnostics?deep=1` shows `"ok": true` (no `problems`).
3. **Curated packs → Bengaluru Weather Explorer → Run on sample**: it runs, shows charts, and they're still there after a refresh.
4. A Discover dataset → **Run sample** completes.
5. Upload a small CSV on a dataset's Run view: it uploads to Blob and the worker analyzes it.

## Troubleshooting

| Symptom | Cause | Fix |
| :--- | :--- | :--- |
| `/api/health` shows `"storage":"sqlite"` | `DATABASE_URL` missing for Production, or no redeploy since adding it | Step 2, then redeploy |
| "Waiting for a worker: none is connected" | No worker running, or it uses a different database | Step 6; compare with `/api/diagnostics` |
| "The worker and this app have different DATABASE_URL / BLOB_READ_WRITE_TOKEN / DSP_SECRET_KEY values" | Worker `.env` differs from Vercel Production | Copy the value from Vercel again and restart the worker |
| Upload says the token expired or was rejected | Wrong or rotated `BLOB_READ_WRITE_TOKEN` | Reconnect Blob in Vercel, redeploy, update the worker |
| Pack runs are disabled on the site | No database on this deployment | Step 2 and redeploy |
| `--doctor` says `[FAIL] Blob` | Token belongs to another store or was revoked | Use the Production token from Vercel |
