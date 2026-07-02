PYTHON := .venv/bin/python
PIP    := .venv/bin/pip
PY     := python3.12   # interpreter used to create the venv

.PHONY: help
help:
	@echo "Targets:"
	@echo "  install     Create .venv (Python 3.12) and install requirements"
	@echo "  db-up       Start Postgres+pgvector (docker compose)"
	@echo "  db-down     Stop the database"
	@echo "  init-db     Create the schema"
	@echo "  db-reset    Drop and re-create the schema (destructive)"
	@echo "  ingest      Ingest every PDF in data/raw/"
	@echo "  ask q=\"...\"  Answer a question (add ARGS=\"--json\" / \"--retrieve-only\")"
	@echo "  stats       Show document/chunk counts"
	@echo "  api         Run the FastAPI server on :8000"
	@echo "  test        Run the test suite"
	@echo "  clean       Remove caches"

.PHONY: install
install:
	$(PY) -m venv .venv
	$(PIP) install --upgrade pip wheel
	$(PIP) install -r requirements.txt
	@echo "Done. Copy .env.example to .env and adjust as needed."

.PHONY: db-up
db-up:
	docker compose up -d db

.PHONY: db-down
db-down:
	docker compose down

.PHONY: init-db
init-db:
	$(PYTHON) -m src.cli init-db

.PHONY: db-reset
db-reset:
	$(PYTHON) -m src.cli reset-db --yes

.PHONY: ingest
ingest:
	$(PYTHON) -m src.cli ingest

.PHONY: ask
ask:
	$(PYTHON) -m src.cli ask "$(q)" $(ARGS)

.PHONY: stats
stats:
	$(PYTHON) -m src.cli stats

.PHONY: api
api:
	$(PYTHON) -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

.PHONY: test
test:
	$(PYTHON) -m pytest -q

.PHONY: clean
clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache
