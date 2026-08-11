# ADR-v2-076 — Voice Git Choreographer (reversibility-gated)

**Status:** Accepted (2026-07-02) · Wave J
**Context links:** [[adr-v2-065-terminal-command-safety-gate]] (classifies formed cmd vs builds intent), [[adr-011]]

## Context

Wave J research (#5) — drive git via a structured argv grammar (never free-form shell); a
reversibility classifier runs reflog-recoverable ops (`commit`, `checkout`, `merge`) immediately
but gates truly destructive ones (`push --force`, `reset --hard`, `branch -D`, `clean -fd`) behind
a spoken confirm, and always speaks the exact undo command. Distinct from the Terminal Command
Safety Gate, which classifies an *already-formed* command — this *builds* git-porcelain intent and
uses a git-specific reversibility taxonomy. Impossible/unsafe in a cloud tool. Anchors: NaSh (arXiv
2506.13028, Develop→Run→Inspect→Revert guardrails), arXiv 2510.06445 (confirm-before-irreversible).

## Decision

Add an opt-in **Voice Git Choreographer**: `[gitvoice] enabled=false`. Three pure cores:
`build_git_argv(text)` → a git argv list (commit/message, add, checkout/branch, merge, push/pull,
status, reset, stash, …) with the commit message as a single quoted arg (never shell-interpolated),
`reversibility(argv)` → `safe` | `confirm`, and `undo_hint(argv)` → the exact recovery command.
Dependency-free with **no deferred backend** (the executor is a plain `git` subprocess). OFF by
default.

## Consequences

- Safe hands-free git; reversible ops flow, destructive ops confirm, undo always spoken.
- Structured argv (message as one arg) removes shell-injection risk entirely.
- Distinct from Terminal Safety Gate (builds intent vs classifies a string).
- Privacy (ADR-011): local `git` subprocess; nothing leaves the box.
- Caveat: the grammar covers common porcelain → uncommon subcommands fall through to `None`
  (no action); off by default.
