# Spec: Read-Back Loop — eyes-free dictation with offline TTS confirm/correct

| Field | Value |
|---|---|
| **ID** | spec-read-back-loop |
| **Status** | Proposed |
| **Date** | 2026-06-14 |
| **Modules** | `src/yazses/tts/` (new), `src/yazses/core/daemon.py`, `src/yazses/config.py`, `src/yazses/commands/grammar.py` |
| **Vision card** | the Read-Back Loop vision card (internal) |
| **Related** | ADR-011 (offline-default), ADR-v04-003 (optional-extra + Protocol-backend pattern), ADR-v04-001 (SLM intent routing) |

---

## Context

Every dictation tool — YazSes included — assumes a final **visual proofread**: you talk, then
you look at the screen to confirm what was typed. For the ~43 million blind and ~295 million
moderately-to-severely visually-impaired people worldwide [web:WHO-2023], and for any eyes-free
context (driving, walking, eyes fatigued, no monitor present), that assumption breaks the tool.

The enabling change is recent and decisive: **permissively-licensed neural TTS now runs faster
than real time on a laptop CPU.** Kokoro-82M is Apache-2.0 and benchmarks at **RTF ~0.47–0.51
on a 4-core CPU** [bench:heyneo]; MeloTTS (MIT) is documented CPU-real-time [web:bentoml]. Before
2024 the only offline CPU-real-time voices were robotic (eSpeak-NG), and the human-like voices
needed a GPU or a cloud call — and cloud is disqualified by ADR-011 (offline-default, no cloud
fallback). That column flipped from `✗` to `✓`, which is the "why now."

This spec adds a **Read-Back Loop**: after a dictation, YazSes speaks the transcript back through
offline TTS, and (P2) listens for a spoken `yes` / `no` / `redo` / `correct …` so the user can
verify and fix entirely by ear. The feature is born compliant with ADR-011 — TTS synthesis, ASR,
and intent classification all run on-device; nothing leaves the machine.

**Latency framing (load-bearing).** The metric that matters is **time-to-first-audio (TTFA),
not full RTF.** Streaming TTS reaches TTFA <50–200 ms, and human turn-taking tolerance is
~200–300 ms [paper:arXiv2508.04721]. Full-utterance synthesis latency scales with length, so the
transcript must be **sentence-chunked**: start speaking chunk 1 while chunk 2 synthesizes. The
design target is **median TTFA < 300 ms** on a 4-core CPU.

---

## Decision

### 1. New TTS abstraction — `src/yazses/tts/`

Mirror the `platform.base` Protocol pattern and the EMG optional-backend precedent (ADR-v04-003).

```
src/yazses/tts/
  base.py        # TtsBackend Protocol + SpeechChunk dataclass
  factory.py     # build_tts(config) -> TtsBackend | None  (None when dormant)
  kokoro.py      # KokoroTtsBackend  (Apache-2.0, default)
  melo.py        # MeloTtsBackend    (MIT, alternative)
  chunking.py    # sentence_chunks(text) -> Iterator[str]  (license-free, regex)
  null.py        # NullTtsBackend    (no-op, used when import/model unavailable)
```

`base.py` declares the Protocol — no third-party import, so it is always importable:

```python
class TtsBackend(Protocol):
    def synthesize(self, text: str) -> Iterator[bytes]:
        """Yield PCM/WAV audio chunks for *text*, sentence by sentence.

        Implementations MUST yield the first chunk as early as possible
        (sentence-chunked streaming) to minimize time-to-first-audio.
        """

    def speak(self, text: str) -> None:
        """Synthesize and play *text* through the default audio output,
        blocking until playback finishes (or until cancel() is called)."""

    def cancel(self) -> None:
        """Stop any in-progress playback immediately (barge-in)."""

    @property
    def name(self) -> str: ...
```

`factory.build_tts(cfg.tts)` returns `None` when `[tts] enabled = false` (the dormancy contract,
parallel to `learning.build_writer` and `build_cleaner`), and `NullTtsBackend` when enabled but
the engine import / model file is missing (so the daemon never crashes — it logs and degrades).
The Kokoro and MeloTTS backends run int8 inference via **ONNX Runtime** on CPU and use
`chunking.sentence_chunks()` to emit audio per sentence.

**License discipline (hard rule, enforced like ADR-011 §5 "open weights only").** Only
**Apache-2.0 / MIT** engines and weights ship as defaults:

- ✅ Kokoro-82M (Apache-2.0) — default [bench:heyneo]
- ✅ MeloTTS (MIT) — alternative [web:bentoml]
- ✅ KittenTTS (Apache-2.0) — low-resource fallback [repo:KittenML]
- ❌ **Piper post-Oct-2025** — original MIT repo archived; active dev is a **GPL-3.0** fork. Do
  NOT vendor or depend on the GPL fork [repo:piper1-gpl].
- ❌ **Coqui / XTTS** — restrictive weights license **and** not CPU-real-time [web:bentoml].

### 2. Eyes-free interaction mode + new daemon states

Add two `TrayState` values and a config-gated mode. The state machine extends the existing
`… → INJECTING → IDLE` path:

```
RECORDING → TRANSCRIBING → INJECTING → READBACK → [P2: AWAIT_CONFIRM] → IDLE
                                          │                  │
                                          │ read_back="off"  │ "yes"  → IDLE (kept)
                                          └──────────────────┤ "no"   → undo injection → IDLE
                                                             │ "redo" → re-record (RECORDING)
                                                             │ "correct …" → P2 span/SLM path
```

- **`READBACK`** — daemon is speaking the just-injected transcript via the TTS backend. The
  **recorder is interlocked OFF** for the whole of this state (critical: prevents the TTS audio
  from being re-captured and re-transcribed — the echo loop named as a critical gap in the
  vision card). `cancel()` (barge-in) is honoured if the user starts the hotkey.
- **`AWAIT_CONFIRM`** (P2) — after read-back, the recorder re-opens and the daemon listens for a
  single confirm/correct utterance, routed through the command grammar.

Wiring point: in `core/daemon.py::_on_hold_end`, after a successful **dictation** injection
(`is_dictation` branch, `injector.inject(text)`), if `cfg.tts.enabled and cfg.accessibility.read_back != "off"`,
enter `READBACK` and call `tts.speak(text)` on a background thread (never on the hotkey loop).
Commands (non-dictation intents) are **not** read back — only dictation is.

### 3. Voice confirm/correct grammar (P2)

Reuse the existing Tier 1 regex → Tier 2 SLM classifier (`commands/grammar.py`,
`commands/slm_router.py`). Add a new `IntentType.CONFIRM` and a small confirm grammar that is
**only active in `AWAIT_CONFIRM`** (so "no" mid-document doesn't trigger it during normal
dictation):

| Utterance (regex, Tier 1) | Action |
|---|---|
| `yes`, `yeah`, `correct`, `keep it`, `that's right` | accept — leave the injected text, → IDLE |
| `no`, `nope`, `delete`, `discard` | undo — backspace the injected text (`inject_backspaces`), → IDLE |
| `redo`, `again`, `re-record`, `say again` | discard + re-enter `RECORDING` for a fresh burst |
| `correct <X> to <Y>` / open-ended | route to Tier 2 SLM (`slm_router`); gated behind confidence + undo |

Open-ended `correct X to Y` shares the Punch-In / Mid-Thought-Undo risk (respeak corrects only
~35% [paper:Suhm2001-ToCHI]); **P1 ships only `yes/no/redo`** (whole-burst redo). Span-level
correction is gated to P2 behind the SLM confidence threshold with an undo fallback.

### 4. IPC integration

Add IPC methods so the CLI/tray can drive and observe read-back (parallel to
`enroll_start` / `streaming_enable`):

- `readback_speak {text}` — speak arbitrary text on demand (e.g. `yazses say "…"`), for testing
  and for an on-demand "say that back" command.
- `readback_enable` / `readback_disable` — toggle the loop at runtime without restart.
- `status` gains `read_back` (the active mode string) and `tts_backend` (the backend name or
  `null`), alongside the existing `state`.

### 5. Config schema

Two surfaces. A new `[tts]` section (engine + voice), and `read_back` under the existing
`[accessibility]` section (the accessibility-facing toggle, kept next to VAD/enrollment fields).

```toml
[tts]
enabled = false                 # master switch; false = fully dormant, no import, no download
engine = "kokoro"               # "kokoro" (Apache-2.0, default) | "melo" (MIT) | "kitten" (Apache-2.0)
voice = "default"               # engine-specific voice id
model_path = ""                 # explicit ONNX/weights path; empty = use bundled/cached default
sample_rate = 24000             # Kokoro native is 24 kHz
speed = 1.0                     # playback rate multiplier
max_readback_chars = 600        # don't read back very long bursts in full (truncate + "…")

[accessibility]
# ... existing fields: min_silence_ms, pre_speech_padding_ms, vad_source, vad_threshold ...
read_back = "off"               # "off" | "final" (P1: speak final transcript) | "confirm" (P2: full loop)
confirm_timeout_s = 6.0         # P2: how long to listen for yes/no/redo before auto-accepting
```

Config dataclasses (`config.py`), all with defaults so a config-less load stays valid (matching
every other section):

```python
@dataclass
class TtsConfig:
    enabled: bool = False
    engine: str = "kokoro"          # kokoro | melo | kitten
    voice: str = "default"
    model_path: str = ""
    sample_rate: int = 24000
    speed: float = 1.0
    max_readback_chars: int = 600

# AccessibilityConfig gains:
    read_back: str = "off"          # off | final | confirm
    confirm_timeout_s: float = 6.0
```

Add `tts: TtsConfig = field(default_factory=TtsConfig)` to `Config`, plus a `_load_tts(data)`
helper following the `_load_emg` pattern. `read_back` defaults to `"off"` so the feature is
dormant unless explicitly enabled (ADR-011: no behaviour change by default).

### 6. Dependencies — optional `tts` extra

Following the `emg` / `overlay` precedent (ADR-v04-003), TTS deps are an **optional extra**, not
imported unless `[tts] enabled = true`. Use latest stable, permissive-only:

```toml
[project.optional-dependencies]
tts = [
    "kokoro-onnx>=0.4",     # Apache-2.0 Kokoro-82M runtime
    "onnxruntime>=1.20",    # CPU int8 inference (MIT)
    "soundfile>=0.13",      # WAV I/O for chunk playback (BSD)
]
# 'all' extra extended to include the tts group.
```

(Exact lower bounds pinned to the current stable at implementation time; `melo`/`kitten` engines
add their own deps under the same extra. `sounddevice` is already a core dep for the recorder and
is reused for playback.)

**Licensing rationale (ship-blocking).** Per ADR-011 §5 ("open weights only by default"), every
shipped default model and runtime must be openly licensed. Kokoro/MeloTTS/KittenTTS weights are
Apache-2.0/MIT; ONNX Runtime is MIT. **Piper's GPL-3.0 fork and XTTS's restrictive weights are
explicitly excluded** — GPL-3.0 is incompatible with YazSes's permissive licensing posture, and
XTTS weights are non-redistributable and not CPU-real-time. This exclusion is a review gate.

---

## Phased plan

**P1 — read-back of the final transcript (the smallest real win).**
- `tts/` module: `TtsBackend` Protocol, `KokoroTtsBackend`, `chunking.sentence_chunks`, `NullTtsBackend`, `factory.build_tts`.
- `[tts]` config + `accessibility.read_back = "final"`.
- `READBACK` state; in `_on_hold_end`, after dictation injection, sentence-chunk + speak on a background thread with the recorder interlocked OFF.
- `readback_speak` IPC + `yazses say "<text>"` CLI for benchmarking.
- **Exit gate:** median TTFA < 300 ms on a 4-core CPU (the riskiest LOFA from the vision card). If unmet, ship as on-demand ("say that back") rather than automatic.

**P2 — voice confirm/correct loop.**
- `AWAIT_CONFIRM` state + `IntentType.CONFIRM` grammar (yes/no/redo), active only in that state.
- Undo path (`inject_backspaces` of the just-injected length) for "no"; re-record for "redo".
- Open-ended "correct X to Y" via Tier 2 SLM, gated behind confidence + undo.
- `accessibility.read_back = "confirm"`, `confirm_timeout_s`.

---

## Testing approach

- **Protocol contract tests** — a `FakeTtsBackend` records `synthesize`/`speak`/`cancel` calls;
  assert `_on_hold_end` enters `READBACK` and calls `speak(final_text)` for dictation only, never
  for command intents.
- **Echo-loop interlock test (critical)** — assert the recorder is *not started* while in
  `READBACK`, and no TTS audio is re-captured as a new burst. This guards the critical gap.
- **Dormancy test** — with `[tts] enabled = false`: `build_tts` returns `None`, no `kokoro-onnx`
  import fires, no model download occurs, state machine never enters `READBACK` (ADR-011 contract).
- **Chunking test** — `sentence_chunks("A. B! C?")` yields three chunks; first chunk is emitted
  before later ones synthesize (TTFA-not-RTF behaviour).
- **TTFA benchmark (non-CI / opt-in marker)** — measure median time-to-first-audio over varied
  transcript lengths on the target CPU; asserts the < 300 ms design target [paper:arXiv2508.04721].
- **Grammar tests (P2)** — `classify` in `AWAIT_CONFIRM` maps yes/no/redo correctly and does NOT
  fire those intents during normal dictation.
- **Privacy gate** — extend the existing `unshare --net` integration test to confirm the full
  read-back loop completes with all network adapters disabled.

---

## Consequences

**Positive**
- The first offline dictation tool that closes the verify loop **by ear** — a clear, underserved
  accessibility win, born ADR-011-compliant (fully local).
- The `tts/` abstraction is reusable: audible daemon status, command confirmation, future spoken
  UI — it compounds beyond this feature.
- Reuses existing substrate (command grammar, accessibility config, state machine) — low blast radius.

**Negative / trade-offs**
- **Model download size.** Kokoro adds a few-hundred-MB model + voices. Mitigated by the optional
  `tts` extra (dormant unless enabled) — most users never download it.
- **Latency budget is tight.** TTFA must stay < 300 ms on commodity CPU [paper:arXiv2508.04721];
  if a target machine can't hit it, P1 degrades to on-demand read-back rather than an automatic loop.
- **Echo-loop hazard.** TTS output must never be re-transcribed — handled by the `READBACK`
  recorder interlock, which is a ship-blocking test.
- **One more optional dep group** (`tts`: `kokoro-onnx`, `onnxruntime`, `soundfile`), Apache/MIT
  only, not imported unless enabled.
- **P1 confirm is coarse.** Whole-burst redo only; in-place span correction is deferred to P2 and
  gated, reflecting the ~35% respeak-correction ceiling [paper:Suhm2001-ToCHI].

---

### Evidence tags
`[bench:heyneo]` Kokoro-82M CPU RTF 0.469/0.509, 4-core EPYC, Apache-2.0 ·
`[web:bentoml]` MeloTTS MIT CPU-real-time; XTTS restrictive + not CPU-RT ·
`[repo:KittenML]` KittenTTS 25 MB int8 Apache-2.0 ·
`[repo:piper1-gpl]` Piper original MIT repo archived Oct 2025, active fork GPL-3.0 (excluded) ·
`[paper:arXiv2508.04721]` streaming-TTS TTFA <50–200 ms, turn-taking tolerance ~200–300 ms →
optimize TTFA not RTF ·
`[paper:Suhm2001-ToCHI]` respeak corrects only ~35% (span-correction risk) ·
`[web:WHO-2023]` ~43M blind / ~295M visually-impaired worldwide ·
`[doc:ADR-011]` zero telemetry, offline-default, open-weights-only.
