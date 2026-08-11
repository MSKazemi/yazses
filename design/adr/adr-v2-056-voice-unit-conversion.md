# ADR-v2-056 — Voice Unit Conversion

**Status:** Accepted (2026-07-02) · Wave H
**Context links:** [[adr-v2-045-entity-itn]] (format vs evaluate), [[adr-v2-032-spoken-math]] (render vs compute), [[adr-011]]

## Context

Wave H research (#4) — evaluate a spoken unit conversion inline: "twenty miles in kilometers" →
"32.19 km", "three cups to milliliters", "100 fahrenheit to celsius". A private, offline
alternative to asking a cloud assistant. Anchor: the `pint` unit registry as the general engine.

Distinct from Entity ITN (*formats* numbers) and Spoken Math→LaTeX (*renders* equations) —
neither *computes* a conversion.

## Decision

Add an opt-in **Voice Unit Conversion**: `[convert] enabled=false`. The pure core
`apply_conversions(text)` finds "<number> <unit> (in|to) <unit>" spans and replaces them with the
computed value, using a built-in **dependency-free** factor table (length/mass/volume + a
temperature special-case for C/F/K). This ships now with zero new dependencies; the full `pint`
registry (thousands of units) + a bundled offline FX snapshot for currency are deferred behind a
`units` extra. Wired on the DICTATE path. OFF by default.

## Consequences

- Ships with **no new dependency** — a small factor table + temperature formulae.
- Distinct from ITN/Spoken Math (evaluate vs format/render).
- Privacy (ADR-011): computed locally; no network (currency FX ships as a static snapshot when added).
- Caveat: built-in table covers common units only → `pint` deferred for the long tail; off by default.
