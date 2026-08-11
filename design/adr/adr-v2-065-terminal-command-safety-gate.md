# ADR-v2-065 — Terminal Command Safety Gate

**Status:** Accepted (2026-07-02) · Wave I
**Context links:** [[adr-v2-047-field-aware-dictation]] (refuses password fields), [[adr-v2-050-redaction-ink]], [[adr-011]]

## Context

Wave I research (#6) — when dictation targets a terminal, a destructive command
(`rm -rf`, `dd of=…`, `mkfs`, `git push --force`, `curl … | sh`, fork bomb) should be held until
you say "confirm", so a misrecognition can't fire an irreversible action. Distinct from every
existing feature: none inspects *command semantics* before injection (Field-Aware refuses
password *fields*; Redaction masks *PII text*).

## Decision

Add an opt-in **Terminal Command Safety Gate**: `[cmdsafety] enabled=false`. The pure core
`assess_command(text)` returns a `RiskAssessment(level, reason)` where level is
`safe` | `caution` | `dangerous`, from an ordered regex ruleset (destructive deletes, disk
writes, filesystem format, force-push/hard-reset, pipe-to-shell, fork bomb, recursive chmod 777;
`sudo`/`mv`-overwrite → caution). A `ConfirmGate` state machine holds a dangerous command until
`confirm()` is called (spoken "confirm"). Dependency-free. Focus-is-a-terminal detection and an
optional small classifier for fuzzy cases are deferred. OFF by default.

## Consequences

- First execution-risk gate; a safety win a cloud dictation tool structurally cannot offer (it
  has no view of your terminal).
- Pure ruleset + state machine → fully testable with no shell.
- Caveat: regex rules are conservative and can miss obfuscated commands → the gate is an aid, not
  a sandbox; off by default, and only ever *delays* injection pending confirmation.
