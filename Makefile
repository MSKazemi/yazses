# YazSes development Makefile (Python — the shipping product on `main`)
#
# Quick start for contributors:
#   make install    — install dev dependencies (uv sync)
#   make check      — tests + lint + types, the whole gate
#   make test       — run the test suite
#   make lint       — ruff
#   make types      — mypy (advisory)
#   make docs       — regenerate the generated reference docs
#
# Everything here runs offline. `make test` needs no microphone, no Whisper
# model, and none of the optional extras.

LOG_FILE := $(HOME)/.local/state/yazses/log/daemon.log

.PHONY: all install check test lint lint-fix types docs docs-serve man inbox \
        start stop restart status logs doctor overlay build clean help

all: check

# ── Setup ─────────────────────────────────────────────────────────────────────

install:
	@echo "▶  Installing dependencies…"
	uv sync

# ── Quality gate ──────────────────────────────────────────────────────────────

# The gate a PR must pass. `types` is advisory (currently clean) and is reported
# separately so it never blocks the green/red signal.
check: test lint hygiene
	@echo ""
	@echo "✓  Gate passed (tests + lint). Type check is advisory:"
	@$(MAKE) --no-print-directory types || true

test:
	@echo "▶  Running tests…"
	uv run python -m pytest tests/ -q

test-cov:
	@echo "▶  Running tests with coverage…"
	uv run python -m pytest tests/ --cov=yazses --cov-report=term-missing

lint:
	@echo "▶  Linting…"
	uv run ruff check src tests scripts

lint-fix:
	@echo "▶  Linting (auto-fix)…"
	uv run ruff check src tests scripts --fix

hygiene:
	@echo "▶  Checking repo hygiene (file sizes)…"
	uv run python scripts/check_repo_size.py

types:
	@echo "▶  Type checking (advisory — currently clean; don't add errors)…"
	uv run mypy src

# ── Documentation ─────────────────────────────────────────────────────────────

# Regenerate docs/features.md, docs/configuration.md, docs/command-index.md.
# Required after any CLI, feature-registry, or config change — a test enforces it.
docs:
	@echo "▶  Regenerating reference docs…"
	uv run python scripts/gen-docs.py

docs-serve:
	@echo "▶  Serving the docs site at http://127.0.0.1:8000 …"
	uv run --group docs mkdocs serve

# Regenerate man/yazses.1 from the CLI. Same drill as `docs` — a test enforces
# it stays in sync, so run this after any CLI change and commit the result.
man:
	@echo "▶  Regenerating man/yazses.1…"
	uv run python scripts/gen-man.py

# ── Maintainer ────────────────────────────────────────────────────────────────

# Every open thread whose last word is somebody else's — issues, PRs, inline review
# threads and discussions. GitHub's notification inbox answers "what have I not read?";
# this answers "what have I not replied to?", which is the question that actually loses
# contributors. Add ARGS=--all to include bot threads.
inbox:
	@uv run python scripts/inbox.py $(ARGS)

# ── Daemon lifecycle ──────────────────────────────────────────────────────────

start:
	uv run yazses start

stop:
	uv run yazses stop

restart:
	uv run yazses restart

status:
	uv run yazses status

doctor:
	uv run yazses doctor

logs:
	uv run yazses logs

overlay:
	@echo "▶  Running the voice-activity overlay (needs the overlay extra)…"
	uv run --extra overlay yazses overlay

# ── Packaging ─────────────────────────────────────────────────────────────────

build:
	@echo "▶  Building wheel + sdist…"
	uv build

clean:
	@echo "▶  Cleaning build artefacts…"
	@rm -rf dist build .pytest_cache .mypy_cache .ruff_cache .coverage
	@find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true

# ── Help ──────────────────────────────────────────────────────────────────────

help:
	@echo ""
	@echo "  YazSes dev Makefile"
	@echo ""
	@echo "  Setup"
	@echo "    make install     install dev dependencies (uv sync)"
	@echo ""
	@echo "  Quality gate"
	@echo "    make check       tests + lint + hygiene (+ advisory type check)"
	@echo "    make test        run the test suite"
	@echo "    make test-cov    run the test suite with coverage"
	@echo "    make lint        ruff"
	@echo "    make lint-fix    ruff with auto-fix"
	@echo "    make hygiene     fail on tracked files big enough to slow every clone"
	@echo "    make types       mypy (advisory)"
	@echo ""
	@echo "  Documentation"
	@echo "    make docs        regenerate the generated reference docs"
	@echo "    make docs-serve  serve the docs site locally"
	@echo "    make man         regenerate man/yazses.1 from the CLI"
	@echo ""
	@echo "  Maintainer"
	@echo "    make inbox       open threads waiting on YOUR reply (ARGS=--all for bots)"
	@echo ""
	@echo "  Daemon"
	@echo "    make start       start the daemon"
	@echo "    make stop        stop the daemon"
	@echo "    make restart     restart the daemon"
	@echo "    make status      query the daemon over IPC"
	@echo "    make doctor      check OS prerequisites"
	@echo "    make logs        show the daemon log at $(LOG_FILE)"
	@echo "    make overlay     run the voice-activity overlay"
	@echo ""
	@echo "  Packaging"
	@echo "    make build       build wheel + sdist"
	@echo "    make clean       remove build artefacts and caches"
	@echo ""
