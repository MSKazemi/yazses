# ADR-v2-001 — Confidence Ink & Voice Re-pick

**Status:** Accepted (2026-07-02) · Wave A
**Context links:** [[adr-v2-000-interaction-layer]], [[adr-011]] (offline), overlay work

## Context

`faster-whisper` computes per-token log-probabilities and (with beam search) n-best
alternatives, but YazSes — like Dragon/Talon/Apple Dictation — discards them. The ambient
research (internal) notes that **ASR token probabilities
are a *calibrated* uncertainty source**, unlike LLM verbalized confidence which is
systematically miscalibrated. Homophone/near-miss correction today forces a full re-dictation.

## Decision

Surface confidence and enable voice re-pick:
1. Capture per-token `avg_logprob`/token probabilities from the decode (already available
   in `stt/faster_whisper.py`). Map to a normalized confidence per word span.
2. **Confidence Ink (display):** words below a configurable threshold get a subtle,
   dismissible marker via the existing overlay (opt-in; off by default). No change to the
   injected text itself unless the user acts.
3. **Voice re-pick (correction):** a command ("the other one", "spell it T-H-E-I-R") re-picks
   the flagged span from the beam alternatives, or accepts a spelled replacement, without
   re-dictating the whole burst. Falls back to spell-out when beam diversity is insufficient.

Config: `[confidence] enabled=false`, `threshold=<float>`, `mark_in_overlay=true`. Pure
post-processing over decode output; new module `postprocess/confidence.py`.

## Consequences

- **+** Fixes the most common dictation error (homophones) fast; honest, grounded uncertainty.
- **+** Cheap: reuses decode outputs + overlay + command grammar; no new model.
- **−** Confidence is an imperfect error proxy → validate flagged-word/error correlation on the
  corpus before relying on it; keep markers subtle and off by default.
- **−** Whisper beam alternatives have limited diversity → spell-out fallback is mandatory.
