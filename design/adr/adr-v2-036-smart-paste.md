# ADR-v2-036 — Smart-Paste Format Adaptation

**Status:** Accepted (2026-07-02) · Wave F
**Context links:** [[adr-v2-007-atspi-pilot]] (window/role introspection), [[adr-v2-002-prosody-autoformat]] (distinct: tone), [[adr-011]]

## Context

The Wave F research (#4) proposes adapting injected syntax to the *target surface*: markdown
editor vs code comment vs email vs terminal vs rich text — `- ` vs `•` bullets, no prose
casing in code, autolinking URLs. YazSes already introspects the active window class and
AT-SPI role (AT-SPI Voice Pilot / injector path), so no model is needed. Distinct from
Tone-Aware Formatting (register/tone) — this adapts *syntax to the destination app*.

## Decision

Add an opt-in **Smart-Paste**: `[smartpaste] enabled=false`. Two pure cores:
`classify_surface(app_hint, role_hint)` maps window/role hints to a surface label
(`terminal|code|email|markdown|rich|plain`), and `adapt(text, surface)` applies a
per-surface format policy (normalize bullets to `- ` in markdown/rich, autolink bare URLs,
leave code/terminal syntax untouched). A tiny-SLM tiebreak for ambiguous surfaces is a
deferred enhancement. OFF by default.

## Consequences

- Fully ship-now with **no new dependency** — a detector + policy table over local window metadata.
- Distinct from Tone Formatting (syntax-to-app, not voice punctuation).
- Privacy (ADR-011): uses only local window metadata; no content leaves the machine.
- Caveat: surface detection is heuristic → conservative default (`plain` passthrough) and off
  by default.
