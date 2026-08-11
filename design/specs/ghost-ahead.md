# Spec: Ghost Ahead — Endpoint / Turn Anticipation (latency hiding)

| Field | Value |
|---|---|
| **ID** | spec-ghost-ahead |
| **Status** | Proposed (experimental; off by default) |
| **Date** | 2026-06-14 |
| **Module** | `src/yazses/stt/streaming.py`, `src/yazses/audio/vad_calibrated.py`, `src/yazses/core/daemon.py` |
| **Vision card** | the Ghost Ahead vision card (internal) |
| **Supersedes seed** | "Ghost Ahead" predictive content ghost-text (the idea-seeds note (internal) #7) — **rejected, reframed** |

---

## Context

The "Ghost Ahead" seed asked for predictive **content** ghost-text: a small on-device LLM (e.g. Qwen2.5-0.5B GGUF) predicts the next few *words* the user is about to say and shows them dimmed to accept. The research verdict is **too-early** for that feature, and the evidence is strong enough to reject it outright rather than defer it:

- Keyboard predictive text does **not** reliably speed entry — **33 wpm** (prediction) vs **35** (none) vs **43** (autocorrect); per-participant best **+2** / worst **−8 wpm** [paper:Palin-CHI, tier5←2, A].
- Word-prediction suggestions are accepted for only **~1.6%** of words [paper:arXiv2408.10791, tier3/2, B].
- The strongest inline-suggestion precedent — GitHub Copilot ghost text — is accepted only **26–35%** of the time, and that is on *code* (structured, low-entropy); **~⅔ of suggestions are rejected** [paper:arXiv2205.06537, tier2, A].
- Sub-1B GGUF models decode 3–5 words in **<200 ms** on CPU but are **weak at open-ended continuation** [card:Qwen2.5-0.5B, tier4, C].

No source demonstrates useful free-form *spoken*-content prediction. Building a visible word-suggestion UI would ship a feature that the literature predicts users ignore, while adding a generative LM to the hot path. **Content ghost-text is therefore out of scope** (see *Deferred feature* below for the exact kill criterion that re-opens it).

What the literature *does* support is **endpoint / turn anticipation**: predicting *when* an utterance ends rather than *what* it contains. A 25M-parameter model forecasts end-of-turn up to **2.56 s ahead**, cutting response latency **1195 → 690 ms** [paper:arXiv2606.13450, tier3, B+]. This maps directly onto YazSes's real latency bottleneck: on hold-release, `core/daemon.py::_on_hold_end` transitions `RECORDING → TRANSCRIBING`, runs the faster-whisper decode (already instrumented as `decode_ms`), then `INJECTING`. That post-release tail is dead time the user waits on. If the daemon anticipates the end of the utterance a few hundred ms early — from falling vocal energy, a lengthening pause, and a stabilizing partial transcript — it can **pre-warm** the decode path (and, gated, **speculatively finalize**) so text is ready essentially the instant the key is released.

---

## Decision

Build **endpoint anticipation** as an off-by-default, on-device latency-hiding layer. It reuses three components that already exist and adds no cloud dependency and no generative LM on the hot path.

### What it does

1. **Endpoint signal** — a cheap, non-generative scorer combines three signals already produced during a recording burst:
   - **Falling energy / pause** from the calibrated RMS VAD (`vad_calibrated.py`): a short trailing window whose `mean(|audio|)` is dropping toward `accessibility.vad_threshold` indicates the speaker is trailing off.
   - **Partial-transcript stability** from the LocalAgreement `StreamingEngine` (`stt/streaming.py`): when the LocalAgreement-confirmed prefix stops growing across consecutive `partial_interval_ms` passes, the utterance content has flattened.
   - **Sustained low energy** for `endpoint_silence_ms`: a trailing run below threshold.
   The scorer fires `on_endpoint_likely()` when all gates co-occur and a debounce has elapsed. It is a **heuristic/classifier, not a language model** (LOFA-5 in the card: sub-1B LMs are too weak to *generate*, but a tiny classifier over these signals is adequate to *detect*).

2. **Pre-warm (Phase 1)** — on `on_endpoint_likely()`, ensure the faster-whisper model is resident and (when `[streaming] enabled`) the `StreamingEngine` buffer is eagerly decoded so the final commit has minimal cold cost. **Pre-warm changes nothing the user sees and cannot corrupt output** — it only removes setup latency from the post-release path.

3. **Speculative finalize (Phase 2, gated)** — on a *high-confidence* endpoint, kick the final decode early on the buffer captured so far. Its result is held as **speculative** and is **discarded** if the user keeps talking. The **authoritative** transcript and the **only** injection still happen on the real `_on_hold_end` (true hold-release). A wrong prediction can therefore never truncate, double-inject, or corrupt the user's text — it can only waste a decode. This invariant (LOFA-3) is non-negotiable; Phase 2 ships only after it is proven harmless.

### Integration points

- **`stt/streaming.py`** — expose a read-only "is the confirmed prefix still growing?" signal. The `StreamingEngine` already tracks `_last_emitted` / `_prev_hypothesis`; add a `prefix_stable_for_ms()` accessor (no behaviour change to the decode loop). Endpoint anticipation consumes this; it does **not** require `[streaming] enabled` (live-partial injection) to be on — pre-warm targets the default *batch* decode path.
- **`audio/vad_calibrated.py`** — add a pure helper `trailing_energy_falling(audio, config, window_ms)` alongside `is_silent_calibrated` (same `AccessibilityConfig.vad_threshold`); no change to existing behaviour.
- **`core/daemon.py`** — wire an `EndpointAnticipator` that the recording loop feeds audio buffers to (mirroring how `_on_hold_end` already accumulates audio and reads `decode_ms`). Its `on_endpoint_likely`/`on_endpoint_confident` callbacks invoke pre-warm and (gated) speculative finalize. `_on_hold_end` stays the single authoritative commit/inject site — it consumes the speculative result if one is ready and valid, else decodes as today.

### Explicitly deferred — content ghost-text

Lexical content suggestion (the literal seed) is **not built**. Re-open **only** if a peer-reviewed result shows free-form **spoken**-content suggestion acceptance **>30%** (matching code-ghost-text) on CPU-class models. Until then, do not add a generative LM to the dictation path for prediction. This bar is pre-registered in the vision card so a future contributor does not quietly revive a rejected feature.

---

## Rationale

**Predict *when*, not *what*.** The evidence against content prediction is direct and multi-source [paper:Palin-CHI; arXiv2408.10791; arXiv2205.06537]; the evidence *for* endpoint timing is direct and recent [paper:arXiv2606.13450]. The pivot keeps the seed's underlying job (make dictation feel instant) and drops the unproven mechanism (guessing words).

**Reuse beats rebuild.** The three signal sources (LocalAgreement partials, calibrated VAD energy, the `decode_ms`-instrumented `_on_hold_end` tail) already exist [observed:repo]. Endpoint anticipation is mostly wiring, not new ML.

**Correctness dominates latency.** Speculative finalize is strictly an optimization behind an invariant: authoritative commit stays on real hold-release. This is why a wrong prediction is harmless — the worst case is a wasted decode, never wrong text.

**No language model on the hot path.** Sub-1B LMs are fast but weak [card:Qwen2.5-0.5B]; using a heuristic/tiny classifier for *detection* avoids importing a generative model and its latency/quality risk into dictation.

**Off by default.** Consistent with `[streaming]`, `[learning]`, `[emg]`, `[overlay]` — experimental capabilities ship dormant and opt-in (ADR-011 posture: nothing surprising, nothing leaves the machine).

---

## Configuration

New `[endpoint]` section in `config.toml`, all defaults dormant/conservative. Added as an `EndpointConfig` dataclass in `config.py` with a matching `_load` and a field on `Config`.

```toml
[endpoint]
enabled = false              # master switch; false = fully dormant (no scorer runs)
speculative_finalize = false # Phase 2; requires the harmless-discard invariant proven (LOFA-3)
endpoint_silence_ms = 350    # trailing low-energy run that counts as "trailing off"
falling_window_ms = 250      # window over which RMS energy must be decreasing
prefix_stable_ms = 400       # LocalAgreement confirmed prefix unchanged this long = content flat
min_lead_ms = 300            # require predicted endpoint ≥ this far before fire (matches kill bar)
debounce_ms = 500            # min gap between consecutive endpoint fires (anti-thrash; LOFA-4)
prewarm = true               # keep model resident / eagerly decode buffer on endpoint
log_latency = true           # record predicted-vs-actual lead and tail saved, for tuning
```

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | `bool` | `false` | Master switch. `false` = the anticipator is never constructed; zero hot-path cost. |
| `speculative_finalize` | `bool` | `false` | Phase 2. Decode early on high-confidence endpoint; result discarded if the user keeps talking. Authoritative commit still on real release. |
| `endpoint_silence_ms` | `int` | `350` | Trailing sub-threshold run length that signals trailing off. |
| `falling_window_ms` | `int` | `250` | Window over which RMS energy must be decreasing to count as "falling". |
| `prefix_stable_ms` | `int` | `400` | LocalAgreement confirmed prefix unchanged for this long ⇒ content has flattened. |
| `min_lead_ms` | `int` | `300` | Minimum predicted lead before release for a fire to be considered useful (matches the §10 kill bar). |
| `debounce_ms` | `int` | `500` | Minimum interval between endpoint fires; prevents thrashing on micro-pauses. |
| `prewarm` | `bool` | `true` | On endpoint, keep the model resident / eagerly decode the buffer (Phase 1). Harmless. |
| `log_latency` | `bool` | `true` | Emit predicted-vs-actual lead and post-release tail saved (metadata only, no transcript) for tuning. |

`enabled` defaults to `false`; when false the daemon behaves exactly as today.

---

## Dependencies

**No new runtime dependency.** Endpoint anticipation reuses the existing stack:

- `numpy` — already present; RMS/trailing-energy math.
- `faster-whisper` — already present; pre-warm keeps the existing `WhisperModel` resident.
- The existing `StreamingEngine` (`stt/streaming.py`) — extended with a read-only accessor only.

If a *learned* endpoint classifier is ever needed (only if the heuristic fails LOFA-1), the candidate is a tiny ONNX model run via `onnxruntime` (latest stable) under a new optional extra — **deferred**, not part of Phase 1/2. No generative LM (`llama-cpp-python`) is added for prediction.

All existing deps stay at latest stable; this spec pins nothing new.

---

## Phased plan

**Phase 0 — Measurement harness (offline, read-only; the §10 prototype).**
Record ~30 real hold-to-talk bursts capturing audio, per-buffer RMS energy (`vad_calibrated.py`), the LocalAgreement partial timeline (`stt/streaming.py`), and the true hold-release timestamp. Compute the endpoint score offline; report median lead time before release and the false-early-fire rate. **Gate:** LOFA-1 — endpoint fires ≥`min_lead_ms` (300 ms) before real release on ≥60% of bursts at ≤10% false-early-fire. No daemon changes. If this fails, stop — the pivot has no value.

**Phase 1 — Pre-warm only (harmless).**
Add `EndpointConfig`, `EndpointAnticipator`, the `prefix_stable_for_ms()` accessor, and `trailing_energy_falling()`. Wire the anticipator into the recording loop; on `on_endpoint_likely()` keep the model resident / eagerly decode the streaming buffer. No change to what the user sees. **Gate:** measured reduction in post-release `decode_ms` tail without thrashing (LOFA-4: ≤3 fires per real release average).

**Phase 2 — Speculative finalize (gated).**
Only after the harmless-discard invariant (LOFA-3) is proven: on high-confidence endpoint, decode early; hold result speculative; discard cleanly if the user continues; consume it in `_on_hold_end` only when valid. **Gate:** zero truncation/double-injection across a test set including mid-burst pause-then-continue, plus a net latency win.

**Deferred indefinitely — content ghost-text.** Re-opened only on the pre-registered >30% spoken-content acceptance bar.

---

## Testing approach

- **Endpoint scorer unit tests** — synthetic energy/partial-timeline fixtures: a clean trailing-off burst fires; a mid-sentence micro-pause does **not**; debounce suppresses double fires.
- **`trailing_energy_falling` / `prefix_stable_for_ms` unit tests** — pure functions over arrays/strings; deterministic, no model.
- **Harmless-discard invariant test (Phase 2)** — simulate endpoint fire followed by continued speech; assert the speculative result is discarded and `_on_hold_end` produces the same text as the no-prediction path. **Correctness gate: the injected text must be byte-identical to the baseline decode in every continue-after-pause case.**
- **Latency measurement (the success metric)** — with `log_latency = true`, compare median post-release time-to-text with `endpoint.enabled = false` vs `true` over a recorded session, using the existing `decode_ms` instrumentation. The feature succeeds only if it reduces the measured tail; if the baseline tail is already <150 ms (near human turn-taking tolerance [paper:arXiv2508.04721 via dossier]), report and downgrade (LOFA-2).
- **Off-by-default test** — with no `[endpoint]` config, behaviour and timing are unchanged and the anticipator is never constructed.

---

## Risks

| Risk | Mitigation |
|---|---|
| **Wrong early prediction truncates the utterance** | Speculative finalize is discardable; authoritative commit always on real hold-release. Phase 2 ships only after the invariant test passes (LOFA-3). |
| **Thrashing: pre-warm fires on every micro-pause, wasting CPU** | `debounce_ms` + requiring energy-falling AND pause AND prefix-stable to co-occur; kill if >3 fires per release (LOFA-4). |
| **The latency tail is already small — feature is cosmetic** | LOFA-2: measure `decode_ms` first; downgrade to watch if median tail <150 ms or no user reports lag. |
| **End-of-turn evidence is from conversational turn-taking, not release-key dictation** | Phase 0 harness validates the transfer on real YazSes bursts before any build commitment [paper:arXiv2606.13450]. |
| **Reviving content ghost-text by scope creep** | Deferred-feature kill criterion is pre-registered (>30% spoken-content acceptance); recorded in the vision card and this spec so it is not re-litigated casually. |
| **Quiet speakers (hypophonia) trigger false endpoints from low energy** | The scorer requires *falling* energy + prefix-stable, not absolute low energy; reuse the user's calibrated `vad_threshold`; bias toward not-firing on low-confidence. |

**Deferred-feature note.** Lexical content ghost-text is intentionally not built. It is rejected on direct, multi-source evidence [paper:Palin-CHI; arXiv2408.10791; arXiv2205.06537], not merely postponed. The single condition that re-opens it is a peer-reviewed demonstration of free-form **spoken**-content suggestion acceptance **>30%** on CPU-class models — a bar set *before* seeing any new data, on purpose.

---

## Consequences

- **No new runtime dependency and no cloud dependency.** Endpoint anticipation reuses `numpy`, `faster-whisper`, and the existing `StreamingEngine`; it adds no generative LM to the dictation path.
- **Off by default.** `[endpoint] enabled = false` means zero behavioural and zero performance change for existing users; the anticipator is not even constructed.
- **Pre-warm is safe; speculative finalize is gated.** Phase 1 cannot corrupt output. Phase 2 cannot corrupt output either (discardable + authoritative-on-release), but ships only after the invariant is proven.
- **Latency is the measured success metric, not a claim.** The feature must demonstrate a reduced post-release tail via existing `decode_ms` instrumentation; if it does not, it is downgraded, not shipped on faith.
- **A reusable endpoint signal compounds.** The same trailing-off detector can later inform barge-in handling and Mid-Thought Undo timing, even if speculative finalize never ships.
- **The rejected feature is documented, not silently dropped.** Content ghost-text and its re-entry bar live in the vision card and this spec, so the decision is auditable.

---
### Evidence tag legend
`[paper:AuthorYear]` peer-reviewed · `[bench:name]` benchmark (with conditions) · `[card:model]` model card · `[observed:source]` direct repo observation · `[doc:tool]` official docs. Tiers 1 (peer-reviewed) → 7 (forum); grade A–F = argument quality.
