<!-- Thanks for contributing to YazSes! Keep this short — delete sections that don't apply. -->

## What does this PR do?

<!-- One or two sentences on the change and the motivation. -->

## Related issue

<!-- e.g. Closes #123 -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Documentation
- [ ] Refactor / internal
- [ ] Build / CI / packaging

## How I tested it

<!-- Commands you ran and the platform you ran them on. For behaviour changes, say how you
     verified it live, not just that tests pass. -->

```sh
uv run python -m pytest tests/ -v
uv run ruff check src tests scripts
uv run mypy src
```

## AI assistance

<!-- Using a coding agent is fine and increasingly common — it never changes whether we
     accept a PR, only how carefully we read it. Say which tool, if any, and what you
     checked yourself. Delete this section if you wrote it all by hand. -->

Tool used:
What I verified personally:

## Checklist

<!-- Docs-only PR (a translation, an example config, a typo, adding yourself to a list)?
     Tick the last three, ignore the rest and delete this comment — that is a complete PR
     and we will not ask you for tests. -->

- [ ] I have read every changed line and can explain why it is there
- [ ] Tests added or updated, and `uv run python -m pytest tests/ -v` passes locally
- [ ] Docs updated if behaviour, CLI, or config changed
- [ ] Change is cross-platform aware (Linux / macOS / Windows) where relevant
- [ ] The change is offline-first — no new network calls or telemetry
- [ ] No secrets, credentials, or personal data added
- [ ] Every commit is signed off (`git commit -s`) — the [DCO](../DCO.md) check fails
      without it. Forgot? `git commit --amend --signoff && git push --force-with-lease`

## Notes for reviewers

<!-- Anything worth calling out: trade-offs, follow-ups, screenshots. -->
