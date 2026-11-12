# SolarWise DZ - common tasks. "make" or "make help" lists them.
#
# The targets expect to be run from the root of the repository. They use the virtual environment in .venv
# (created by "make install") and the Node packages in frontend/node_modules.

PYTHON ?= python3
VENV   := .venv
BIN    := $(CURDIR)/$(VENV)/bin
PORT   ?= 8000

.DEFAULT_GOAL := help
.PHONY: help install install-backend install-frontend build run dev-api dev-web \
        test test-backend test-frontend lint typecheck check e2e \
        openapi fixtures demo-data generated presentation docker-build up down clean

help: ## list the tasks
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ------------------------------------------------------------------------------------------------- set-up
install: install-backend install-frontend ## install the backend (in .venv) and the interface's packages

install-backend: ## create .venv and install the backend with its development tools
	test -x $(BIN)/python || $(PYTHON) -m venv $(VENV)
	$(BIN)/pip install -q --upgrade pip
	$(BIN)/pip install -q -e "backend[dev]"

install-frontend: ## install the packages of the web interface
	cd frontend && npm ci --no-audit --no-fund

build: ## build the web interface into frontend/dist (the backend serves it)
	cd frontend && npm run build

# ------------------------------------------------------------------------------------------------- running
run: ## run the application with the demonstration on http://localhost:8000 (PORT=8080 to change)
	SOLARWISE_DEMO_MODE=true $(BIN)/solarwise serve --port $(PORT)

dev-api: ## development: the API with automatic restart on port 8000
	SOLARWISE_DEMO_MODE=true $(BIN)/solarwise serve --reload --port 8000

dev-web: ## development: the interface with hot reload on port 5173 (needs "make dev-api")
	cd frontend && npm run dev

# ------------------------------------------------------------------------------------------------- checks
test: test-backend test-frontend ## every automated test

test-backend: ## backend tests
	cd backend && $(BIN)/pytest

test-frontend: ## interface tests
	cd frontend && npm test

lint: ## ruff and eslint
	cd backend && $(BIN)/ruff check .
	cd frontend && npm run lint

typecheck: ## mypy and the TypeScript compiler
	cd backend && $(BIN)/mypy
	cd frontend && npm run typecheck

check: lint typecheck test build ## everything that must pass before a change is shared

e2e: ## browser checks against a throw-away server (needs CHROMIUM_PATH and "make build")
	frontend/e2e/all.sh

# ------------------------------------------------------------------------------------------------- generated files
openapi: ## after an API change: frontend/openapi.json and the TypeScript types
	cd backend && $(BIN)/solarwise openapi --out ../frontend/openapi.json
	cd frontend && npm run gen:api

fixtures: ## after an engine or API change: the canned answers used by the interface tests
	cd backend && $(BIN)/python -m tests.frontend_fixtures

demo-data: ## after a generator change: data/demo
	cd backend && $(BIN)/solarwise export-demo --out ../data/demo

generated: openapi fixtures demo-data ## all three

presentation: ## rebuild the pitch (needs CHROMIUM_PATH; see presentation/README.md)
	node presentation/src/build.cjs
	$(BIN)/python presentation/src/build_pptx.py

# ------------------------------------------------------------------------------------------------- Docker
docker-build: ## build the image
	docker build -t solarwise-dz .

up: ## start the application and PostgreSQL (needs .env, see .env.example)
	docker compose up --build

down: ## stop them (the data stay in the volume)
	docker compose down

clean: ## remove build output and caches (not .venv, not node_modules, not your data)
	rm -rf frontend/dist frontend/*.tsbuildinfo frontend/node_modules/.tmp presentation/.work
	find backend -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf backend/.pytest_cache backend/.mypy_cache backend/.ruff_cache .ruff_cache
