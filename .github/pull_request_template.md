<!-- Thanks for contributing to YazSes! Keep this short — a couple of sentences is fine. -->

## What & why
<!-- What does this change, and what problem does it solve? Link any issue: "Closes #123". -->

## How I tested it
<!-- Commands you ran, platform you tested on. For behaviour changes, how you verified it live. -->

```
uv run python -m pytest tests/ -v
uv run ruff check src tests
uv run mypy src
```

## Checklist
- [ ] Tests pass locally (`uv run python -m pytest tests/`)
- [ ] Added/updated tests for the change (if it touches behaviour)
- [ ] Updated docs / `--help` / CHANGELOG if user-facing
- [ ] The change is offline-first — no new network calls or telemetry
