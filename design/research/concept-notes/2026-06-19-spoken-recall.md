# Spoken Recall — origin note

> **Written:** 2026-06-19 · **Owner:** Mohsen Seyedkazemi Ardebili
> **Shipped as:** [ADR-v2-005 — Spoken Recall & Ambient Scratch](../../adr/adr-v2-005-spoken-recall.md)
> **Tier:** `design/` — public. Historical origin note; the ADR above is the current
> source of truth.

## The idea

The pitch was that a year of dictation history is a write-only diary: everything spoken
into the daemon is captured, and none of it can be asked back. The dream was to close the
loop — hold the key, ask "what did I dictate about the auth bug last Tuesday?", and hear
the relevant past dictation back, with no window, no grep, no scrolling a log. The framing
was explicit that the north star here is not "type faster" but "never lose a thought once
expressed" — memory as the substrate of the tool, not just its output.

## What shipped

The recall side shipped as `src/yazses/recall/`, ranking past dictations by relevance to a
spoken query, exposed as `yazses recall "<query>"` under the `recall` feature toggle
(**off by default**, learning category). It operates entirely over the existing encrypted,
on-device learning corpus (ADR-012) — no new capture path, no data leaving the machine.
The ADR bundles a second capability, "Ambient Scratch" (spoken notes-to-self), alongside
recall as one coherent feature.
