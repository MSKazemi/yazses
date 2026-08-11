# ADR-v2-024 — Pure-Vision Screen Commanding (VLM)

**Status:** Accepted — design only, implementation deferred (2026-07-02) · Wave D (research tier)
**Context links:** [[adr-v2-007-atspi-pilot]] (AT-SPI primary), [[adr-v2-003-gaze-routed]], [[adr-011]]

## Context

The Wave D research (#10) proposes commanding the screen by voice where the accessibility
tree is empty or wrong — "click the blue Export button" resolved by *looking at pixels*.
Anchors: Microsoft OmniParser V2, ShowUI, Florence-2 (on-device screen-grounding VLMs). This
is the vision fallback to the AT-SPI Voice Pilot (ADR-v2-007), which fails on canvas/game/
remote-desktop surfaces that expose no element tree.

## Decision

**Design accepted; implementation deferred until an on-device VLM path is viable.** The
intended shape: `[screenvision]` config (`enabled=false`, `backend`, `confidence_min`), an
experimental feature (`--force`), and a VLM backend lazy behind a `screenvision` extra.
AT-SPI stays the primary resolver; the VLM is invoked **only** when the tree yields no
match. The *pure* seam that can ship first (a future iteration) is the arbitration logic —
"AT-SPI match? use it; else, if screenvision enabled, hand off to the VLM" — mirroring the
existing `pilot.plan_action` scoring, plus the same ordinal/ambiguity confirm guard.
Critically, per ADR-011: **frames are processed in-RAM during the command and never stored
or sent** (same invariant as Glance-Type gaze, ADR-v2-003). On-device VLM latency + accuracy
are the bottleneck, so no code lands now — only this ADR and the research record.

## Consequences

- Complements, never replaces, AT-SPI Pilot — used only when the tree is empty.
- Reuses the Pilot's confirm/ordinal guard, so destructive clicks still confirm.
- Strong privacy invariant: screen frames are ephemeral, in-RAM, never persisted (ADR-011).
- Caveat: on-device VLM grounding is latency-heavy → scope to icon+text grounding, keep
  experimental, and prefer AT-SPI whenever it resolves.
