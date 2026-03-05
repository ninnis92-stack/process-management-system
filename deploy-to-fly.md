# Deploying to Fly.io

This project is ready for Fly.io. `run.py` and `Dockerfile` are configured to use the `$PORT` environment variable.

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

Notes:
- `run.py` reads `$PORT` and binds `0.0.0.0`. The `Dockerfile` runs Gunicorn binding to `$PORT`.
- Set `FLASK_DEBUG=0` in production.
- If you want Fly-managed Postgres or Redis, use `flyctl postgres create` or add managed services and update `DATABASE_URL`/`REDIS_URL` accordingly.

If you want, I can generate a suggested `fly.toml` snippet tuned for this app or run `flyctl launch` here — you'll need to authenticate interactively for that. Which do you prefer?
