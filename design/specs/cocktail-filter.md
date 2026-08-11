# Spec: Cocktail Filter — Target-Speaker Gate & Suppression

| Field | Value |
|---|---|
| **ID** | spec-cocktail-filter |
| **Status** | Proposed |
| **Date** | 2026-06-14 |
| **Module** | `src/yazses/audio/target_speaker.py` (new) |
| **Vision card** | the Cocktail Filter vision card (internal) |
| **SoA dossier** | the 2026-06-14 ten-feature SoA dossier (internal) (Feature 6) |
| **Verdict** | ready-now (gate, P1) · partial (suppression, P2) · out-of-scope (full separation) |

---

## Context

YazSes dictation assumes a quiet room. The VAD gate in `audio/vad_calibrated.py` is a speaker-agnostic energy threshold (`mean(|audio|) < vad_threshold`): it cannot tell the user's speech from a roommate, a TV, or a background meeting. In a shared room, co-occurring speech passes the energy gate, reaches `faster-whisper`, and produces spurious or mixed transcripts — a stranger's half-sentence glued onto the user's text. For the accessibility users YazSes targets (ALS, RSI, low-vision), "only works when the room is silent" is a recurring dignity and reliability cost, not an edge case.

The state of the art now supports a fix on the CPU/on-device budget YazSes runs on. Target-speaker extraction and speaker-conditioned (personal) VAD have crossed into quantized, streaming, real-time forms in 2024–2026:

- **Personal VAD** — speaker-conditioned per-frame target/non-target classification at **130K params** [paper:arXiv1908.04284, tier2, A].
- **Silero VAD** — speaker-agnostic speech gate, **30 ms chunk in <1 ms CPU (RTF 0.004)** [bench:Picovoice2026, tier3, B].
- **VoiceFilter-Lite** — target-speaker enhancement, **2.2 MB, 8-bit, streaming, real-time on-device, −25.1% WER** overlapping speech / **−14.7%** reverberant, **no clean-speech harm** [paper:arXiv2009.04323 + Google, tier2/3, A].
- **Short-enrollment d-vector** is the standard primitive [paper:arXiv2204.03793, tier2, B].

Crucially, YazSes already owns the two prerequisites this feature reuses: the enrollment wizard (`accessibility/enroll.py`, 20 Harvard sentences) and an encrypted, machine-bound per-user store (`learning/crypto.py` AES-256-GCM `0600` key; `learning/store.py`). A speaker voiceprint (d-vector) is a small artifact that slots into both with no new privacy surface, honouring ADR-011 (nothing leaves the machine).

Full clean source separation (recover both voices) — e.g. SepFormer at **19.4 dB SI-SDRi** but heavy and **not CPU-real-time** [paper:arXiv2303.05023, tier2, A] — is explicitly **out of scope** (see Scope Boundary).

---

## Decision

Add a **target-speaker filter** stage to the audio pipeline that, given a user d-vector captured at enrollment, **gates** (P1) and later optionally **suppresses** (P2) non-target speech *before* the VAD/Whisper stages. This is gate-and-suppress (drop/attenuate interfering frames), **not** source separation.

### New module: `src/yazses/audio/target_speaker.py`

Two collaborating pieces, both pure/mockable (no daemon state):

1. **`SpeakerEmbedder`** — wraps an off-the-shelf speaker encoder (ECAPA-TDNN / GE2E). `embed(audio: np.ndarray, sample_rate: int) -> np.ndarray` returns an L2-normalised d-vector. Used once at enrollment and once at load to warm the model.
2. **`TargetSpeakerGate`** — holds the enrolled d-vector and config. The P1 surface:

   ```python
   class TargetSpeakerGate:
       def __init__(self, dvector: np.ndarray, cfg: CocktailConfig) -> None: ...
       def filter(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
           """Return audio with non-target frames zeroed (P1) or attenuated (P2).

           Frame-windows whose embedding cosine-sim to the enrolled d-vector is
           below `match_threshold` are dropped. Low-confidence frames default to
           KEEP (bias toward the user) so quiet/hypophonic onsets survive.
           """
   ```

   P1 zeroes (or hard-drops) non-target windows so the downstream energy VAD then naturally discards an all-interferer buffer. P2 swaps the zeroing for a VoiceFilter-Lite-style soft mask (`suppress_db` attenuation) when a suppression model is configured.

`TargetSpeakerGate` is a **pure transform** `np.ndarray -> np.ndarray`: it has the same shape contract as `padding.prepend_padding`, so it composes into the existing pipeline without touching recorder/Whisper internals.

### Pipeline placement

The gate runs in `core/daemon.py::_on_hold_end`, **after** padding is prepended and **before** `is_silent_calibrated` and `transcribe`:

```
recorder.stop()
  → padding.prepend_padding(audio)        # existing
  → TargetSpeakerGate.filter(padded)      # NEW — drop/attenuate non-target frames
  → is_silent_calibrated(...)             # existing energy VAD now sees only target speech
  → engine.transcribe(...)                # existing
```

Placing it *before* the energy VAD means an interferer-only buffer collapses to (near) silence and is discarded by the existing `Silent audio -- discarding` path — no new discard branch needed for the common case. The gate is a no-op pass-through when disabled or unenrolled, so the default path is unchanged.

### Enrollment — reuse `accessibility/enroll.py`

The user already reads 20 Harvard sentences in `run_wizard`. That audio is currently used only to derive `vad_threshold`/`min_silence_ms` and then discarded. We **concatenate the per-prompt recordings already captured in the wizard loop**, pass them to `SpeakerEmbedder.embed`, and store the resulting d-vector — **adding zero new prompts** for the user. The d-vector is written encrypted via the existing `learning/crypto.py` cipher to `<data_dir>/voiceprint.dvec.enc` (alongside `corpus.key`), `0600`, machine-bound. A `--voiceprint` flag (or automatic capture when `[cocktail] enabled`) controls whether the wizard computes and writes it.

If LOFA-1 (d-vector separability from 20 short sentences) fails its kill criterion, a short dedicated ~30 s capture pass is added rather than abandoning the gate — but the default reuses existing enrollment.

---

## Configuration

New `[cocktail]` section (new dataclass `CocktailConfig` in `config.py`, wired into `Config` and `load_config` exactly like `EmgConfig`). **OFF by default** — fully dormant, honouring ADR-011.

```toml
[cocktail]
enabled = false                 # master switch; false = gate never runs, no model loaded
mode = "gate"                   # "gate" (P1, drop non-target) | "suppress" (P2, attenuate)
match_threshold = 0.60          # cosine-sim below this => non-target window
frame_ms = 30                   # analysis window for per-frame speaker decision
keep_on_low_confidence = true   # bias toward KEEP near threshold (protect quiet onsets)
embedder = "ecapa"              # "ecapa" | "ge2e" — speaker-encoder backend
voiceprint_path = ""            # empty => <data_dir>/voiceprint.dvec.enc (encrypted)
suppress_model_path = ""        # P2 only: VoiceFilter-Lite-class ONNX checkpoint
suppress_db = 18.0              # P2 only: attenuation applied to non-target frames
```

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | `bool` | `false` | Master switch. False = no model loaded, gate is a pass-through. |
| `mode` | `str` | `"gate"` | `gate` (P1, zero non-target frames) or `suppress` (P2, soft-mask). |
| `match_threshold` | `float` | `0.60` | Cosine-sim to d-vector below which a window is non-target. Tunable per mic/room. |
| `frame_ms` | `int` | `30` | Per-frame decision window (aligns with Silero 30 ms chunking). |
| `keep_on_low_confidence` | `bool` | `true` | Near-threshold frames default KEEP so quiet/hypophonic speech is not clipped. |
| `embedder` | `str` | `"ecapa"` | Speaker-encoder backend selecting the `SpeakerEmbedder` impl. |
| `voiceprint_path` | `str` | `""` | Encrypted d-vector path; empty resolves to the data dir next to `corpus.key`. |
| `suppress_model_path` | `str` | `""` | P2: path to a VoiceFilter-Lite-class checkpoint; empty disables suppression. |
| `suppress_db` | `float` | `18.0` | P2: attenuation (dB) for non-target frames. |

`yazses doctor` reports whether `[cocktail] enabled` is set, whether a voiceprint exists, and (P2) whether `suppress_model_path` resolves to a loadable model — mirroring how it reports the EMG serial port.

---

## Integration points

| File | Change |
|---|---|
| `src/yazses/audio/target_speaker.py` | **New.** `SpeakerEmbedder`, `TargetSpeakerGate`, `load_voiceprint(cfg, cipher)`. |
| `src/yazses/config.py` | Add `CocktailConfig`; wire into `Config` + `load_config` (pattern of `_load_emg`). |
| `src/yazses/core/daemon.py` | Build the gate in `_initialize` (a `build_gate()` returns `None` when disabled/unenrolled, à la `build_writer`); call `gate.filter(padded)` in `_on_hold_end` between padding and `is_silent_calibrated`. Record `event["gate_dropped_secs"]` for the learning corpus. |
| `src/yazses/accessibility/enroll.py` | After the prompt loop, optionally concatenate captured audio → `SpeakerEmbedder.embed` → encrypted `voiceprint.dvec.enc`. Guarded by a flag; no new prompts. |
| `src/yazses/learning/crypto.py` | Reused unchanged — same cipher encrypts the d-vector blob. |
| `src/yazses/system/doctor.py` | Report cocktail status (enabled / voiceprint present / P2 model loadable). |
| `pyproject.toml` | New optional extra `cocktail` (see Dependencies). Not imported unless `[cocktail] enabled`. |

The `build_gate() -> TargetSpeakerGate | None` factory mirrors `learning.capture.build_writer`: returns `None` when `enabled` is false or no voiceprint exists, so the daemon's hot path stays a single `if gate is not None` check and the feature is genuinely dormant when off.

---

## Data flow

```
[enrollment, one-time]
  enroll.run_wizard  → 20 prompt recordings (already captured)
                     → concat → SpeakerEmbedder.embed → d-vector (L2-norm, float32)
                     → crypto.encrypt → voiceprint.dvec.enc (0600, machine-bound)

[runtime, per hold-release]
  recorder.stop → prepend_padding → TargetSpeakerGate.filter:
      for each frame_ms window:
        emb = SpeakerEmbedder.embed(window)
        sim = cosine(emb, dvector)
        keep = sim >= match_threshold  OR  (keep_on_low_confidence and sim near threshold)
        mode=gate     → keep ? window : zeros
        mode=suppress → keep ? window : soft_mask(window, suppress_db)   # P2
   → is_silent_calibrated (interferer-only buffer now collapses to silent → discarded)
   → faster-whisper.transcribe
```

The d-vector loads once at daemon start (decrypt + warm the encoder); per-frame embedding at 30 ms windows is the marginal runtime cost — bounded by the personal-VAD evidence (130K params, per-frame, real-time) [paper:arXiv1908.04284, tier2, A].

---

## Phased plan

**P1 — personal-VAD gate (ready-now).** Ship `SpeakerEmbedder` + `TargetSpeakerGate` in `mode = "gate"`: enroll a d-vector from existing wizard audio, drop non-target frames before the energy VAD. Reuses Silero VAD as a cheap speaker-agnostic pre-gate (reject obvious non-speech first, then speaker-gate the rest) [bench:Picovoice2026; paper:arXiv1908.04284]. This is the full evidence-backed, CPU-real-time deliverable.

**P2 — VoiceFilter-Lite-style suppression (partial).** Add `mode = "suppress"`: replace zeroing with a soft mask from a VoiceFilter-Lite-class 8-bit ONNX model, so a partially-overlapping interferer is attenuated rather than dropped, recovering the user's masked frames (−25% WER target) [paper:arXiv2009.04323]. **Gated on a 1-day spike** (LOFA-4) to confirm a permissively-licensed CPU-real-time checkpoint exists; if not, P2 stays a documented future item and P1 ships alone.

---

## Dependencies

New optional extra `cocktail` in `pyproject.toml` (latest stable at time of writing; not imported unless `[cocktail] enabled`):

```toml
[project.optional-dependencies]
cocktail = [
  "speechbrain >= 1.0.3",     # ECAPA-TDNN speaker-embedding (d-vector) encoder
  "silero-vad >= 5.1.2",      # speaker-agnostic speech pre-gate, <1ms/chunk CPU
  "onnxruntime >= 1.22.0",    # CPU inference for the d-vector / P2 suppression models
]
```

Notes:
- **speechbrain** provides ECAPA-TDNN d-vectors (`embedder = "ecapa"`); **Resemblyzer** (GE2E, `embedder = "ge2e"`) is a lighter alternative selectable via config — the §10 prototype picks whichever clears LOFA-1 at the lowest install cost.
- **silero-vad** is the standard pip package for the cheap pre-gate.
- **onnxruntime** runs the encoder and (P2) the VoiceFilter-Lite-class checkpoint on CPU int8.
- No GPU, no cloud, no new always-on dependency: the extra is installed and imported only when the feature is enabled (`uv sync --extra cocktail`), exactly like the `emg` extra.

Verify each pinned lower bound against the current stable release at implementation time per the project's "latest-stable" rule.

---

## Testing approach

All units are pure transforms, fully mockable with `pytest` / `mocker` (no audio hardware, no model download in CI):

- **`TargetSpeakerGate.filter`** — inject a fake `SpeakerEmbedder` whose `embed` returns scripted vectors: assert target windows pass through unchanged and non-target windows are zeroed (P1) / attenuated by `suppress_db` (P2). Assert `keep_on_low_confidence` keeps near-threshold frames.
- **Quiet-onset protection** — feed low-energy target frames; assert recall stays high vs. an ungated baseline (LOFA-3 regression guard).
- **Pipeline composition** — unit-test that an all-interferer buffer, after `filter`, is classified silent by `is_silent_calibrated` (so the existing discard path fires) and that a clean target buffer is unchanged.
- **Enrollment** — mock `recorder_factory` (the wizard already supports this) and the embedder; assert a d-vector is computed from captured audio and written via the crypto cipher with `0600` perms, decryptable round-trip.
- **Config** — `CocktailConfig` defaults, `load_config` parsing of `[cocktail]`, and the `build_gate() is None` dormant path when `enabled = false` or no voiceprint exists.
- **Separability harness (offline, not CI)** — the §10 prototype script measuring cosine separation on real me/TV/interferer clips; reported in the vision card, not a CI gate.

Cosine-sim and masking math are deterministic and assertable without floating-point flakiness beyond `np.allclose`.

---

## Risks & consequences

- **d-vector quality from short enrollment is unproven for the user's specific mic/room** [paper:arXiv2204.03793, tier2, B] — the critical risk (LOFA-1). Mitigated by the offline separability harness with a pre-registered kill criterion (≥90% target recall at ≤10% interferer leakage) *before* daemon wiring.
- **Clipping the user's own quiet speech** (hypophonia) — gating risks dropping low-energy target frames, contradicting the `pre_speech_padding` accessibility design. Mitigated by `keep_on_low_confidence = true` and a recall regression test on enrolled-quiet clips.
- **Per-frame embedding latency** — adds CPU work between hold-release and transcript. Bounded by the 130K-param personal-VAD evidence [paper:arXiv1908.04284], but must be measured under YazSes's int8 budget; P1 runs as a single post-buffer pass (not streaming) to keep it simple.
- **P2 model availability/license** — no guarantee a permissive CPU-RT VoiceFilter-Lite checkpoint is pip-installable [paper:arXiv2009.04323]. Mitigated by gating P2 behind a 1-day spike; P1 ships independently.
- **Privacy surface** — a biometric voiceprint is sensitive. Mitigated by reusing the existing machine-bound AES-256-GCM `0600` store [observed:repo]; the d-vector never leaves the machine and is destroyed by the existing corpus-destroy path. Consequence: `corpus destroy` (or a new `voiceprint forget`) must also remove `voiceprint.dvec.enc`.
- **False rejects in genuinely solo-but-noisy rooms** (fans, music without speech) — Silero pre-gate + energy VAD already handle non-speech; the speaker gate only adds value against competing *speech*. When disabled, behaviour is identical to today.

---

## Scope boundary (explicit)

**In scope:** enroll-once d-vector → personal-VAD frame gate (P1) → optional VoiceFilter-Lite-style soft suppression (P2), all CPU/on-device/offline.

**Out of scope:** GPU-tier full source separation (recovering each speaker's clean stream, e.g. SepFormer-class models) [paper:arXiv2303.05023, tier2, A]. YazSes attenuates or drops the interferer to protect *the user's* transcription; it does not attempt to reconstruct the interfering speech. This boundary is deliberate and matches the dossier verdict: **ready-now for the gate, partial for suppression, never for full separation on CPU.**

---

## Open questions (deferred)

- Speaker-encoder choice (ECAPA-TDNN vs GE2E) — decided by the §10 prototype on separability-per-install-cost.
- Streaming per-frame gate vs single post-buffer pass — P1 ships the post-buffer pass; revisit streaming only if latency/barge-in demands it.
- Whether to fuse the Silero pre-gate and speaker gate or layer them — P1 layers; measure double-gating's effect on quiet onsets.
