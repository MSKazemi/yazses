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

# `campaign` and `hygiene` must be listed: `campaign/` is also a directory, so without
# this make sees an up-to-date file target and silently does nothing.
.PHONY: all install check test lint lint-fix types docs docs-serve man inbox \
        feature-sizes research-watch \
        start stop restart status logs doctor overlay build clean help \
        hygiene campaign campaign-generate campaign-stats campaign-queue campaign-validate

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

# Contributor task inventory. `tests/test_campaign.py` runs the same check, so this is
# for working on the inventory itself rather than an extra gate.
campaign:
	@echo "▶  Validating the contributor task inventory…"
	uv run python scripts/campaign.py --check

campaign-generate:
	uv run python scripts/campaign.py --generate

# Read-only funnel measurement: attributed contributors, uncredited merged authors,
# per-cohort conversion. Degrades to local git history with no network.
campaign-stats:
	uv run python scripts/campaign_stats.py

# Who is waiting on a human, and which task claims have lapsed back to the pool.
campaign-queue:
	uv run python scripts/campaign_queue.py
	uv run python scripts/campaign_queue.py --claims

# The per-family validators a contributor's task points at.
campaign-validate:
	uv run python scripts/check-compatibility.py
	uv run python scripts/check-app-profile.py

types:
	@echo "▶  Type checking (advisory — currently clean; don't add errors)…"
	uv run mypy src

# ── Documentation ─────────────────────────────────────────────────────────────

# Regenerate docs/features.md, docs/configuration.md, docs/command-index.md AND the
# architecture figures. Required after any CLI, feature-registry or config change —
# tests enforce both, so leaving the figures out of this target meant `make docs`
# produced a tree that `make check` then rejected.
docs:
	@echo "▶  Regenerating reference docs…"
	uv run python scripts/gen-docs.py
	@echo "▶  Regenerating architecture figures…"
	uv run python scripts/gen-arch-figures.py

docs-serve:
	@echo "▶  Serving the docs site at http://127.0.0.1:8000 …"
	uv run --group docs mkdocs serve

# Regenerate man/yazses.1 from the CLI. Same drill as `docs` — a test enforces
# it stays in sync, so run this after any CLI change and commit the result.
man:
	@echo "▶  Regenerating man/yazses.1…"
	uv run python scripts/gen-man.py

# Per-feature download sizes for `yazses features` (ADR-018). Slow — it resolves every
# feature's full dependency closure against a clean environment and prices each
# distribution — so it is deliberately NOT part of `docs`. Run it when a feature's
# dependencies change; a test fails when the table no longer covers them.
feature-sizes:
	@echo "▶  Regenerating the per-feature download-size table…"
	uv run python scripts/gen-feature-sizes.py

# Sweep the literature and write a dated digest (design/research/watch/). Maintainer
# tooling, not part of the product: ADR-019 keeps the daemon's outbound paths to the
# five it has. Every entry lands "(unreviewed)" and must be annotated or deleted before
# it is committed — a test enforces that, because a feed nobody prunes is a feed nobody
# reads.
research-watch:
	@echo "▶  Sweeping for new research…"
	uv run python scripts/research-watch.py --inbox .mohsen.note.md $(ARGS)
	@echo "   Entries are marked unreviewed — annotate or delete before committing."

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
	@echo "    make campaign          validate the contributor task inventory"
	@echo "    make campaign-validate run the per-family record validators"
	@echo "    make campaign-stats    measure the contributor funnel (read-only)"
	@echo "    make campaign-queue    who is waiting on a human; lapsed claims"
	@echo "    make campaign-generate rewrite campaign/generated/ (open-tasks, dashboard, stats)"
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
