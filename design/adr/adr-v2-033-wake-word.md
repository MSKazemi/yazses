# ADR-v2-033 — Wake-Word Activation

**Status:** Accepted (2026-07-02) · Wave E (experimental)
**Context links:** [[adr-v2-029-semantic-autostop]] (pairs for zero-touch), [[adr-v2-012-accessibility-continuum]], [[adr-011]]

## Context

All YazSes activation paths assume a physical hotkey (keyboard/EMG) or gaze. The Wave E
research (#8) proposes a low-power always-listening keyword spotter ("Hey Yaz") to start a
dictation turn with no key — a new activation modality for severe motor impairment. Paired
with Semantic Auto-Stop (ADR-v2-029) it yields fully zero-touch dictation. Anchors:
openWakeWord (dscripka), microWakeWord (OHF-Voice, TFLite-micro) — on-device keyword spotters.

## Decision

Add an opt-in **wake-word activation**: `[wakeword] enabled=false, keyword, threshold,
cooldown_ms`. The pure core `should_activate(score, since_last_ms, config)` fires only when
the spotter score clears `threshold` **and** a `cooldown_ms` debounce has elapsed (false-accept
guard). The openWakeWord ONNX model is lazy behind a `wakeword` extra and processes only a
short rolling buffer; nothing is transcribed or stored until the wake word fires.
**EXPERIMENTAL** — the only always-listening feature → hardest opt-in (`--force`), off by
default, hard local-only guarantee.

## Consequences

- New zero-touch activation modality; composes with Auto-Stop + Voice Mouse Grid.
- Pure debounce/threshold decision → fully testable; the spotter model stays deferred.
- Privacy-critical (ADR-011): keyword spotting is 100% local on a rolling buffer, nothing
  persisted, explicit loud opt-in required.
- Caveat: false-accepts would trigger spurious recording → conservative threshold + cooldown,
  experimental, off by default.
