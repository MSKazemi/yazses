# ADR-v2-129 — Killer Features 10x: gaze deixis, sotto-voce channel, activation-source seam, pluggable STT

**Status:** Accepted (2026-08-07) · implemented in the same change
**Context links:** [[adr-v2-010-gaze-routed-dictation]] (wires its `needs_confirm` at last),
[[adr-v2-100-whisper-aware-mode]] (its detector, repurposed as a command channel),
[[adr-v04-003-emg-serial]] (the EMG backend finally constructed),
[[adr-011]] (on-device, zero telemetry), [[adr-v04-001-slm-inference]] (lazy-extra pattern),
study: an internal SoA study (+ the three SOTA
dossiers beside it)

## Context

A 2026-08-07 web-refreshed SOTA + competitor study (competitor landscape, local STT
engines, gaze/EMG/BCI input) and a full codebase reachability audit converged on four
findings:

1. **Voice+gaze deixis is an open niche.** The published recipe (GazePointAR, CHI 2024;
   SemanticScanpath 2025) is late fusion — serialize the gaze target next to the
   transcript — with a measured +26.5% coreference win on demonstratives. No desktop
   open-source system does it; Talon has precise gaze but no deixis grammar. YazSes
   already computed everything needed at hold-start and threw it away.
2. **The default gaze backend's confidence was fake.** `targeter.py` hard-coded
   `confidence=1.0` for MediaPipe samples, so `[gaze] confidence_min` gated nothing and
   ADR-v2-010's destructive-confirm policy (`needs_confirm`) had never been wired.
3. **Whispered-vs-voiced is a CPU-trivial, product-absent mode switch.** DualVoice
   (UIST 2022) showed whisper=command / voiced=text on a plain mic; whisper has no F0,
   so an autocorrelation voicing check suffices. The `whispermode` package already
   held the tested DSP — unreachable from any runtime path.
4. **EMG was advertised but never constructed.** `EMGBackend` (YESP serial) is complete
   and tested, `[emg]` config loads, doctor checks the port — and no code path ever
   built the backend. Wake word, mouth-switch, breath and vocal-joystick all wait on
   the same missing seam: a pluggable non-keyboard activation source.
5. **faster-whisper is hard-wired** (no protocol, no factory, and `StreamingEngine`
   consumes the private `_model`), while 2025–26 SOTA (Parakeet TDT 0.6B: 6.32% WER vs
   large-v3's 7.44% at ~30x realtime CPU, CC-BY-4.0, pure-Python `onnx-asr`) beats it
   on both axes for English dictation.

## Decision

Ship four surgical changes, all obeying the v2 invariants (off/opt-in by default,
fully local, guard-and-fallback, lazy heavy deps):

- **Real gaze confidence.** The MediaPipe backend returns a `GazeSample` whose
  confidence is left/right **eye-agreement** (the two eyes measure the same gaze
  independently; divergence = landmark quality). The targeter consumes it via an
  optional `estimate_sample` seam — l2cs keeps its internal gating unchanged.
- **Gaze deixis** (`gaze/deixis.py`, pure): whole-utterance demonstrative commands
  ("close this", "focus that window", "switch to this one", "minimize that") resolve
  against the burst's gaze snapshot (`GazeTargeter.last_decision`). Destructive
  actions on a gaze-routed target confirm via an actionable toast
  (`[gaze] confirm_destructive`, wiring ADR-v2-010's `needs_confirm`); without
  actionable-notification support the window is left untouched and the toast says so.
  `[gaze] deixis = true` is a sub-flag of the opt-in gaze feature; with
  `route_dictation` off, the targeter snapshots without focusing.
- **Sotto-voce command channel** (`[whispermode] command_channel = true`, active only
  when the opt-in `[whispermode] enabled` is set): `burst_is_whispered` frames the
  burst, drops silent frames, and takes median voicing/tilt so one breathy word can't
  flip a voiced burst; a whispered burst is routed into command mode exactly like the
  dedicated command key. Detection failure degrades to dictation.
- **Activation-source seam + EMG for real.** The daemon builds a list of non-keyboard
  `HotkeyBackend` duck-types (`_build_activation_sources`); `[emg] device_port` set →
  an `EMGBackend` whose squeeze drives the command-key callbacks (`mode="command"`,
  default) or plain hold-to-talk (`full_text`). Each source runs like the command-key
  listener and is stopped at shutdown. The seam is where wake word / mouth-switch /
  breath plug in later.
- **Pluggable STT** (`stt/base.py` Protocol + `stt/factory.py`, `[stt] engine`):
  faster-whisper stays the default; **Parakeet TDT 0.6B v2** ships as the opt-in
  high-accuracy engine behind `yazses features enable stt-parakeet` (lazy `onnx-asr`
  install; honest fallback to faster-whisper with a named fix when deps are missing).
  `StreamingEngine` now consumes the engine's public `decode_window` seam instead of
  the private `_model`.

## Consequences

- `[gaze] confidence_min` finally does what it says for the default backend; gaze
  misroutes on low-quality frames fall back to focus instead of stealing it.
- "Close this" is the first shipped desktop voice+gaze deixis anywhere; its grammar is
  strict whole-utterance so it can never consume dictation, and it is only reachable
  in command mode.
- Whisper-to-command gives a hands-free, socially-silent mode switch with zero new
  dependencies; the known limit (whispered STT WER is worse than voiced) only affects
  command phrases, which are short and grammar-matched.
- EMG stops being a paper feature; the false-activation rate can now be measured from
  the learning corpus (the metric the Nature 2025 sEMG paper omitted).
- A second engine now costs ~200 lines, not a refactor. Deferred to follow-ups:
  decode-time hotword boosting (replaces `initial_prompt` biasing on Parakeet),
  Moonshine v2 streaming, implicit gaze calibration from clicks, the hands-free
  accessibility bundle (dwell-to-talk, face-gesture switches), offline Command Mode
  for selected text.

## Rejected

Consumer-EEG "thought" triggers (artifact-grade only; ~0.10 FP/min best case ≈ dozens
of phantom mic-openings a day — strictly dominated by the EMG electrode), lip-reading
/ AVSR (non-commercial weights, no CPU-real-time path), silent-speech sEMG (~68% WER,
research-grade), Meta Neural Band integration (no raw EMG, no Linux, not sold
standalone).
