# ADR-v2-013 — Glasses↔Desktop Dictation Bridge

**Status:** Accepted (2026-07-02) · Wave C (experimental)
**Context links:** [[adr-v2-000-interaction-layer]], [[adr-009-remote-injection]] (remote agent), [[adr-011]]

## Context

The AR/wearables research (internal) shows the
near-term wearable-mic reality: smart glasses and phones are better *microphones* than
laptops (closer to the mouth, always present), but their text has to land on the desktop
where the work happens. YazSes already has a remote-injection path (`remote/`,
`yazses-agent`, ADR-009) that forwards typed text over an SSH reverse tunnel — the same
shape a glasses/phone bridge needs.

## Decision

Add an opt-in **bridge** that lets a companion device (phone as mic today; glasses when
they expose an audio stream) capture speech and inject the transcript into the desktop
session. Reuse the `remote/` forwarder + local-proxy injector rather than a new transport;
the companion runs the lightweight capture, the desktop runs STT + injection (so no model
ships to the phone). Pair over the existing authenticated tunnel. **EXPERIMENTAL**, off by
default; nothing leaves the paired local link (ADR-011).

## Consequences

- Reuses the proven remote-injection transport — minimal new surface, no new base deps.
- Keeps STT on the desktop (companion stays thin; no cloud).
- Glasses support lands for free once a device exposes a mic stream; phone-as-mic works now.
