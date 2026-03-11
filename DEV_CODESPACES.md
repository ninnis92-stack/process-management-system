Codespaces / Dev Container setup
===============================

Quick guide to open and use this repo in GitHub Codespaces or VS Code Dev Containers.

1) Open in GitHub Codespaces
- Push your branch to GitHub (we already pushed earlier). Then click **Code → Codespaces → New codespace** on the GitHub UI for this repo.

2) Local devcontainer (VS Code)
- Install the Remote - Containers extension in VS Code and choose `Remote-Containers: Open Folder in Container...`.

What the devcontainer provides
- Python 3.11 base image
- Installs Python dependencies from `requirements.txt` in the container on first start
- Attempts to install `flyctl` (the Fly CLI) during container setup
- Forwards ports `5001` (Flask dev server) and `8080` (gunicorn internal port)

Common commands
- Start dev server:
  ```bash
  python3 run.py
  ```

- Run the test release helper (migrations + seed):
  ```bash
  python3 scripts/release_tasks.py
  ```

- Deploy to Fly (requires `flyctl` and that you're logged in):
  ```bash
  flyctl auth login
  git push origin HEAD
  flyctl deploy -a <your-fly-app-name>
  ```

  > **Note:** the first time you deploy, the app needs a Postgres volume named
  > `pg_data`. Your Makefile (and `scripts/ensure_volume.sh`) will create it
  > automatically, but you can also run this by hand:
  >
  > ```bash
  > flyctl volume create pg_data -a <your-fly-app-name> --size 1
  > ```
  >
  > After the volume exists, it is reused on every subsequent deploy; you only
  > ever create it once. Teammates running the app locally should be aware of
  > this step and can skip it once it’s done.

Environment & secrets
- For local work set `DATABASE_URL` (if using Postgres), `SECRET_KEY`, and any SMTP or SSO vars in your Codespaces secrets or by exporting in the terminal.

Notes
- The container `postCreateCommand` may skip installing some optional tooling if the network or upstream script is unavailable; install manually if needed.
- Avoid exposing production secrets in Codespaces; use GitHub Codespaces secrets for private values.

If you want, I can also add a small `dev` Makefile with common commands (run, test, seed) — tell me if you'd like that.
