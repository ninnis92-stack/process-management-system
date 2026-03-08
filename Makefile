PY=python3
PIP=$(PY) -m pip
REQ=requirements.txt
FLY_APP ?= process-management-prototype-lingering-bush-6175

.PHONY: install run seed migrate deploy test

install:
	$(PIP) install --upgrade pip
	$(PIP) install -r $(REQ)

run:
	$(PY) run.py

seed:
	$(PY) seed.py

migrate:
	@echo "Running alembic upgrade head (requires alembic configured)"
	alembic upgrade head

deploy:
	@git push origin HEAD
	@echo "Deploying to Fly app: $(FLY_APP)"
	@flyctl deploy -a $(FLY_APP)

deploy-safe:
	@echo "Running tests before deploy"
	@make test
	@echo "Tests passed — deploying"
	@make deploy

test:
	pytest -q

smoke:
	@echo "Running smoke tests against local server (http://127.0.0.1:5000)"
	@bash scripts/smoke_test.sh http://127.0.0.1:5000

smoke-clean:
	@echo "Clearing development database (SQLite)"
	@rm -f instance/app.db
PYTHON?=python3
PIP?=pip
VENV?=.venv

.PHONY: help venv install test run seed db-init db-migrate db-upgrade db-stamp worker compose-up compose-down

help:
	@echo "Makefile commands:"
	@echo "  make venv           # create a virtualenv in .venv"
	@echo "  make install        # install python requirements into venv"
	@echo "  make test           # run pytest"
	@echo "  make run            # run the local Flask dev server"
	@echo "  make seed           # seed sample data"
	@echo "  make db-init        # initialize alembic migrations (one-time)"
	@echo "  make db-migrate     # autogenerate a migration (requires FLASK_APP)"
	@echo "  make db-upgrade     # apply migrations to the configured DB"
	@echo "  make db-stamp       # stamp the DB as head without applying DDL"
	@echo "  make worker         # run the RQ worker (requires redis)"
	@echo "  make compose-up     # start docker-compose services"
	@echo "  make compose-down   # stop docker-compose services"

venv:
	$(PYTHON) -m venv $(VENV)

install: venv
	$(VENV)/bin/$(PIP) install -r requirements.txt

test:
	PYTHONPATH=. $(VENV)/bin/pytest -q -s

run:
	$(VENV)/bin/$(PYTHON) run.py

seed:
	$(VENV)/bin/$(PYTHON) seed.py

db-init:
	@echo "Run this only once to create migrations/ (installs required)"
	FLASK_APP=run.py $(VENV)/bin/flask db init

db-migrate:
	FLASK_APP=run.py $(VENV)/bin/flask db migrate -m "autogen"

db-upgrade:
	FLASK_APP=run.py $(VENV)/bin/flask db upgrade

db-stamp:
	FLASK_APP=run.py $(VENV)/bin/flask db stamp head

worker:
	REDIS_URL=${REDIS_URL:-redis://localhost:6379/0} RQ_ENABLED=1 $(VENV)/bin/$(PYTHON) scripts/rq_worker.py

compose-up:
	docker compose up --build

compose-down:
	docker compose down
