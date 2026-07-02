# ─────────────────────────────────────────────────────────────────────────────
# RAG POC — root orchestration
#   Backend  (FastAPI + Postgres/pgvector) runs in Docker.
#   Frontend (React + Vite chat UI) runs locally with yarn.
#
# Quick start:
#   make setup      # one-time: create .env files + install frontend deps
#   make up         # start backend (db + api) in Docker on :8000
#   make fe         # start the chat frontend on :5173
# ─────────────────────────────────────────────────────────────────────────────

BACKEND_DIR  := rag-orc-dbvector-python
FRONTEND_DIR := frontend-ai-poc
COMPOSE      := docker compose
# Run compose from inside the backend dir so it picks up its .env for ${VAR} substitution.
BACKEND_COMPOSE := cd $(BACKEND_DIR) && $(COMPOSE)

.DEFAULT_GOAL := help

.PHONY: help
help:
	@echo ""
	@echo "  Setup"
	@echo "    make setup            Create .env files (from examples) + install frontend deps"
	@echo ""
	@echo "  Backend (Docker)"
	@echo "    make up               Build & start db + api in Docker (http://localhost:8000)"
	@echo "    make down             Stop and remove the backend containers"
	@echo "    make logs             Follow the API container logs"
	@echo "    make rebuild          Rebuild the API image and restart"
	@echo "    make db-up            Start only Postgres/pgvector"
	@echo "    make ingest           Ingest every file in $(BACKEND_DIR)/data/raw/ (inside the container)"
	@echo "    make backend-shell    Open a shell in the API container"
	@echo ""
	@echo "  Frontend (local, Vite)"
	@echo "    make fe               Start the chat UI dev server (http://localhost:5173)"
	@echo "    make fe-install       Install frontend dependencies (yarn)"
	@echo "    make fe-build         Production build of the frontend"
	@echo ""
	@echo "  Combined"
	@echo "    make dev              Start backend in Docker (detached), then run the frontend"
	@echo "    make clean            Stop backend + remove frontend build output"
	@echo ""

# ── Setup ────────────────────────────────────────────────────────────────────
.PHONY: setup
setup:
	@test -f $(BACKEND_DIR)/.env || (cp $(BACKEND_DIR)/.env.example $(BACKEND_DIR)/.env && \
		echo "Created $(BACKEND_DIR)/.env — paste your OPENAI_API_KEY into it.")
	@test -f $(FRONTEND_DIR)/.env || cp $(FRONTEND_DIR)/.env.example $(FRONTEND_DIR)/.env
	@$(MAKE) fe-install
	@echo ""
	@echo "Setup done. Next: put your OpenAI key in $(BACKEND_DIR)/.env, then 'make up' and 'make fe'."

# ── Backend (Docker) ─────────────────────────────────────────────────────────
.PHONY: up
up:
	$(BACKEND_COMPOSE) --profile app up --build -d
	@echo "Backend running: API http://localhost:8000  ·  Postgres :5432"

.PHONY: down
down:
	$(BACKEND_COMPOSE) --profile app down

.PHONY: logs
logs:
	$(BACKEND_COMPOSE) --profile app logs -f app

.PHONY: rebuild
rebuild:
	$(BACKEND_COMPOSE) --profile app up --build -d app

.PHONY: db-up
db-up:
	$(BACKEND_COMPOSE) up -d db

.PHONY: ingest
ingest:
	$(BACKEND_COMPOSE) --profile app exec app python -m src.cli ingest

.PHONY: backend-shell
backend-shell:
	$(BACKEND_COMPOSE) --profile app exec app bash

# ── Frontend (local) ─────────────────────────────────────────────────────────
.PHONY: fe
fe:
	cd $(FRONTEND_DIR) && yarn dev

.PHONY: fe-install
fe-install:
	cd $(FRONTEND_DIR) && yarn install

.PHONY: fe-build
fe-build:
	cd $(FRONTEND_DIR) && yarn build

# ── Combined ─────────────────────────────────────────────────────────────────
.PHONY: dev
dev: up fe

.PHONY: clean
clean:
	-$(BACKEND_COMPOSE) --profile app down
	-rm -rf $(FRONTEND_DIR)/dist
