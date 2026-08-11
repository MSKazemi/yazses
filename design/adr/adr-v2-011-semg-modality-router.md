# ADR-v2-011 — sEMG Command Layer & Modality Role Router

**Status:** Accepted (2026-07-02) · Wave C (experimental)
**Context links:** [[adr-v2-000-interaction-layer]], [[adr-v04-003-emg-serial]] (EMG intake), [[adr-011]] (offline)

## Context

YazSes already reads a USB-serial EMG band as a *push-to-talk* trigger (`platform/emg`,
ADR-v04-003). The AR/wearables research (internal)
shows Meta's Nature 2025 sEMG wristband decoding discrete gestures at high bandwidth, and
gaze-HCI work shows eye-gaze is the fastest *pointing* channel but a poor *selection* one
("Midas touch"). The lesson: each input modality has a role it is fastest at — **gaze for
targeting, EMG for discrete commands, voice for dictation, keyboard for activation** —
and a good multimodal system routes each action to the right channel rather than forcing
one modality to do everything.

## Decision

Add an opt-in **Modality Role Router**: a pure policy layer that, given the set of
currently-available modalities and a configured role map, decides which modality owns
each role and arbitrates conflicts by a priority order. Ship named **presets**
(`balanced`, `hands-free`, `voice-only`). The router is pure and hardware-agnostic; the
EMG serial intake and any gaze intake stay opt-in and lazy (no new base deps).

- Roles: `dictation`, `command`, `targeting`, `activate`.
- Defaults: `voice→dictation`, `emg→command`, `gaze→targeting`, `keyboard→activate`.
- Conflicts (two modalities claim one role) resolve by `priority`.
- New package `modality/` (pure router) + `[modality]` config. **EXPERIMENTAL**, off by
  default, `features enable` requires `--force`.

## Consequences

- Promotes EMG from a single trigger to a first-class command channel without touching
  the base install; dormant unless a band is configured.
- Pure policy → fully testable; the real modality intakes are wired incrementally behind
  their existing opt-in configs (`[emg]`, `[gaze]`).
- Honours ADR-011: routing is local metadata; no signal leaves the machine.
