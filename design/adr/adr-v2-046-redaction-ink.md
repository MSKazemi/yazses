# ADR-v2-046 — Redaction Ink

**Status:** Accepted (2026-07-02) · Wave G
**Context links:** [[adr-012-self-improvement-loop]] (corpus redact_patterns — distinct: storage vs output), [[adr-v2-018-voice-biometric-guard]] (who vs what), [[adr-011]]

## Context

Wave G research (#4) — detect PII/secrets in the transcript **before it is typed** and mask or
hold them, so a spoken card number, SSN, password, or API key never lands in the wrong window
(a shared doc, a chat, a screenshared terminal). Anchors: GLiNER2-PII (arXiv 2605.09973),
gliner-pii-edge (quantized ONNX, 60+ categories, CPU), Microsoft Presidio structured detectors.

Distinct from the learning corpus's `redact_patterns`, which scrubs text **at storage time**
for the private corpus; this scrubs on the **injection/output path**, protecting what actually
gets typed into other apps. Distinct from Voice Biometric Guard (authenticates *who* speaks —
this filters *what* is written).

## Decision

Add an opt-in **Redaction Ink**: `[redaction] enabled=false, mode="mask"`. The pure core
`redact(text, mode)` ships dependency-free structured detectors: credit-card numbers validated
by the **Luhn checksum**, US SSN, emails, phone numbers, IPv4, and common secret-key shapes
(`sk-…`, `AKIA…`, `ghp_…`). `mode="mask"` replaces each hit with a category tag (`[CARD]`,
`[SSN]`, …); `mode="hold"` leaves text intact but returns the categories found so the caller can
require a confirm. Wired guarded on the DICTATE path. Free-form PII (names/addresses) via GLiNER
is deferred behind a `pii` extra.

## Consequences

- Ships now with **no new dependency** — regex + Luhn; the whole point is secrets never leave
  the local output buffer.
- Distinct from corpus redaction (output path vs storage path).
- Privacy (ADR-011): detection is fully local; nothing is sent anywhere.
- Caveat: regex detectors have recall limits → Luhn cuts card false positives; free-form PII is
  the deferred neural tier; off by default.
