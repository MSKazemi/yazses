# ADR-v2-060 — Clipboard-History by Voice

**Status:** Accepted (2026-07-02) · Wave H
**Context links:** [[adr-v2-036-smart-paste]] (single paste vs multi-item history), [[adr-011]]

## Context

Wave H research (#7) — recall recent copies by spoken index or description: "paste the second
thing I copied", "paste the URL I copied". Windows/macOS clipboard history exists but has no
voice recall — a motor-accessibility win.

Distinct from Smart-Paste (adapts formatting on a *single* paste) — this is *multi-item history*
navigation.

## Decision

Add an opt-in **Clipboard-History by Voice**: `[cliphistory] enabled=false, capacity=20`. Two
pure cores: `ClipboardRing` (a bounded, consecutive-dedup ring buffer of recent entries,
newest-first) and `resolve_reference(query, items)` (maps a spoken recall — ordinals
last/second/third, "first/oldest", "number N", and keyword filters url/email — to one entry).
Both dependency-free; the on-device sentence embedding for semantic recall ("the address I
copied") is deferred. OFF by default.

## Consequences

- Multi-item clipboard recall by voice; pure buffer + resolver, no model.
- Distinct from Smart-Paste (history vs single paste).
- Privacy (ADR-011): the buffer lives in local process memory, opt-in and purgeable; nothing
  leaves the machine.
- Caveat: keyword/ordinal grammar covers the common case → semantic recall deferred to the
  embedding tier; off by default.
