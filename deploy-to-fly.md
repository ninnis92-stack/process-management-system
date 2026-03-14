# Deploying to Fly.io

This project is ready for Fly.io. `run.py` and `Dockerfile` are configured to use the `$PORT` environment variable.

---

## Option A — Deploy from your phone (no CLI needed)

Deployments can be triggered directly from the GitHub website — no terminal or installed tooling required.

### One-time setup (do this once from any device)

1. **Generate a Fly.io API token**
   - Open [fly.io/dashboard](https://fly.io/dashboard) in your browser.
   - Go to **Account → Access Tokens → Create token** and copy the value.

2. **Add the token to GitHub**
   - Open the repository on GitHub → **Settings → Secrets and variables → Actions**.
   - Create a secret named `FLY_API_TOKEN` and paste the token.

### Trigger a deploy from your phone

1. Open the repository on GitHub (mobile browser or the GitHub app).
2. Tap **Actions** → select **"Deploy to Fly"**.
3. Tap **"Run workflow"** → choose the `main` branch → tap **"Run workflow"**.

The workflow runs tests and then deploys to Fly.io automatically.  Tap the running
job to watch live logs.

---

## Option B — Deploy from a terminal (desktop / laptop / cloud shell)

Quick deploy steps (run from repo root):

1. Install `flyctl` and login:

```bash
curl -L https://fly.io/install.sh | sh
flyctl auth login
```

2. (Optional) Launch an app if you don't have one yet:

```bash
flyctl launch --name your-app-name --region ord --no-deploy
```

3. Set required secrets (example). Replace values with your credentials:

```bash
flyctl secrets set SECRET_KEY='replace_me' DATABASE_URL='postgres://user:pass@host:5432/dbname' REDIS_URL='redis://:pass@host:6379/0' FLASK_DEBUG=0
```

4. Deploy (uses your `Dockerfile`):

```bash
flyctl deploy
```

5. Tail logs and check status:

```bash
flyctl logs
flyctl status
```

---

## Notes

- `run.py` reads `$PORT` and binds `0.0.0.0`. The `Dockerfile` runs Gunicorn binding to `$PORT`.
- Set `FLASK_DEBUG=0` in production.
- Every push to `main` also triggers an automatic deploy (see `.github/workflows/deploy.yml`).
- The `release_command` in `fly.toml` runs `scripts/release_tasks.py` on each deploy to migrate the
  database, apply safe schema changes, and seed baseline data.
- If you want Fly-managed Postgres or Redis, use `flyctl postgres create` or add managed services and
  update `DATABASE_URL`/`REDIS_URL` accordingly.
