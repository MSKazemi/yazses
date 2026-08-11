# Spec: Punch-In — re-speak-to-correct span splicing

| Field | Value |
|---|---|
| **ID** | spec-punch-in |
| **Status** | Proposed |
| **Date** | 2026-06-14 |
| **Module** | `src/yazses/postprocess/punch_in.py` (new) |
| **Vision card** | the Punch-In vision card (internal) |
| **Maturity** | Experimental (ship respeak → 2–3 aligned candidates → confirm; never auto-splice) |

---

## Context

YazSes transcribes a hold-to-talk burst and injects plain text. When Whisper mis-hears a word ("their" for "there", "bool in" for "Boolean"), the user's only recourse today is to leave voice: reach for arrow keys, select the wrong span, delete, retype — the single most flow-breaking moment in voice dictation. The motivating dream (vision card §1) is *punch-in correction*: re-speak just the corrected phrase, and the system locates the wrong span and splices the fix in place, like dropping in on one bar in a DAW.

**The central constraint of this spec is an empirical ceiling, not a compute limit.** Pure respeak correction — re-speak the phrase, silently overwrite — succeeds only **~35%** of the time and *degrades on repeated respeak*, because the recognizer makes the *same* error again on the re-articulation [paper:Suhm2001-ToCHI, tier2, A]. Respeak "often does not lead to correct recognition"; **multimodal correction (respeak + a pick/keyboard step) is ~2× faster** [paper:Lewis-HFES, tier2, B+]. The decades-shipped, mature pattern is Dragon's **"Correct \<word\>" → alternatives list → confirm** [web:WillowVoice, tier5, C]. No 2025–26 offline product ships in-voice span correction.

By contrast, the *mechanics* are solved and cheap. Edit-distance token alignment locates and splices ASR-error spans at **−8–14% WER, 6–9× faster** than autoregressive correction (FastCorrect) [paper:arXiv2105.03842, tier3, A], and phonetically-oriented alignment matches a respoken span to its target across surface-form differences — the homophone case [paper:arXiv1904.11024, tier3, B+]. All required inputs already exist in one process: the recently injected text and cursor offsets (`inject/streaming.py`), the audio buffer (`audio/recorder.py`), and word timestamps (`stt/faster_whisper.py`, one flag away) [observed:codebase].

**Design consequence (carried forward honestly):** because pure respeak is wrong ~⅔ of the time on the hard cases and worsens on the user's instinctive retry, this feature must **never auto-splice**. It must present **2–3 aligned candidates and require a one-step confirm**, and it must **fall back to keyboard/clipboard correction when alignment confidence is low** — the multimodal, Dragon-proven shape. The solved splice engine is the easy half; the human-factors ceiling is what the *interaction* is designed around.

---

## Decision

Add a **correction mode** to the daemon and a new postprocess module `src/yazses/postprocess/punch_in.py`.

1. The user enters correction mode explicitly — a distinctive command-grammar trigger (e.g. "correct that" / "fix that") **or** a dedicated hotkey/EMG label — then re-speaks the corrected phrase as a normal hold-to-talk burst.
2. `punch_in.locate()` aligns the respoken phrase against the **recent correction buffer** (last *N* words of injected text, with char offsets) using **edit-distance + phonetic alignment**, producing a located target span and an alignment confidence score.
3. `punch_in.candidates()` produces **2–3 candidate replacement strings** (the respoken transcription, neighbouring Whisper hypotheses, and phonetic/near-miss variants), optionally **reranked by a small GGUF LM** when one is configured.
4. The daemon **presents the candidates and the located span for confirmation** (numbered pick — voice "one/two/three" or a hotkey cycle). It does **not** silently overwrite.
5. On confirm, the splice reuses `inject/streaming.py` cursor tracking (shift+Left ×N over the span, then inject the replacement), or **clipboard-paste replacement** as the portable fallback.
6. **When alignment confidence is below threshold** (mislocated span, ambiguous match, out-of-window), the daemon **does not guess** — it surfaces the located region for manual keyboard/clipboard correction. This is the explicit Dragon escape hatch.

The whole feature is **opt-in and off by default** (`[punch_in] enabled = false`), honouring the same conservatism as streaming and prosody.

### Pipeline placement

```
Correction mode entered (trigger phrase OR hotkey/EMG label)
  → next hold-to-talk burst → audio → vad → faster-whisper      (respoken phrase)
  → clean_text                                                   (postprocess/cleaner.py)
  → punch_in.locate(respoken, buffer)        → TargetSpan + confidence   ← NEW
  → punch_in.candidates(respoken, span, reranker) → [Candidate, ...]     ← NEW
  → IF confidence ≥ threshold: present candidates → confirm → splice (inject/streaming.py)
  → ELSE: surface span for keyboard/clipboard fallback
  → exit correction mode
```

Punch-In runs **only in correction mode**, **only on the batch transcribe path** (the respoken burst), and **only on dictation** (a command intent inside correction mode is ignored / exits the mode). The normal dictation path is untouched when correction mode is not active.

### Recent correction buffer

The daemon maintains a bounded **correction buffer**: the last `window_words` words of injected DICTATE text, each with its character offset relative to the current cursor (sourced from `inject/streaming.py`'s `chars_injected` tracking and the per-burst text). This is the search space for `locate()`. Bursts older than the buffer window, or text the user has since edited by other means, are out of scope and route to fallback.

### Module interface

```python
# src/yazses/postprocess/punch_in.py
from dataclasses import dataclass, field

@dataclass(frozen=True)
class TargetSpan:
    start_char: int            # offset into the correction buffer (chars back from cursor)
    end_char: int
    old_text: str              # the located wrong span, e.g. "the're"
    confidence: float          # 0..1 alignment confidence; gates auto-presentation vs fallback

@dataclass(frozen=True)
class Candidate:
    text: str                  # replacement string, e.g. "there"
    score: float               # combined alignment + (optional) LM rerank score
    source: str                # "respoken" | "hypothesis" | "phonetic" | "lm_rerank"

@dataclass(frozen=True)
class PunchInResult:
    span: TargetSpan | None    # None ⇒ no usable target found ⇒ keyboard fallback
    candidates: list[Candidate] = field(default_factory=list)   # 0..3, best first
    fallback: bool = False     # True ⇒ confidence below threshold, surface for manual fix

def locate(respoken: str, buffer: str, *, cfg: "PunchInConfig",
           word_offsets: list[tuple[str, int]]) -> TargetSpan | None: ...

def candidates(respoken: str, span: TargetSpan, *, cfg: "PunchInConfig",
               hypotheses: list[str] | None = None,
               reranker: object | None = None) -> list[Candidate]: ...

def punch_in(respoken: str, buffer: str, *, cfg: "PunchInConfig",
             word_offsets: list[tuple[str, int]],
             hypotheses: list[str] | None = None,
             reranker: object | None = None) -> PunchInResult: ...
```

`locate()` is pure and CPU-cheap: a `rapidfuzz` alignment of `respoken` against sliding windows of `buffer`, scored by a blend of surface edit-distance and a phonetic-key distance (Double Metaphone / G2P keys), returning the best window as a `TargetSpan` with its blended confidence. `candidates()` assembles up to 3 replacement strings and, if a GGUF reranker is wired, reorders them by LM likelihood in the span's surrounding context. `punch_in()` is the orchestrating entry the daemon calls; it returns `fallback=True` (and a best-effort `span` for highlighting) whenever confidence is below `confidence_threshold`.

---

## Configuration

New `[punch_in]` section in `config.py` (`PunchInConfig` dataclass), all fields defaulted, off by default:

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | `bool` | `false` | Master switch. `false` ⇒ correction mode is never offered; feature fully dormant. |
| `trigger_phrases` | `list[str]` | `["correct that", "fix that"]` | Distinctive full-utterance phrases that enter correction mode. Empty ⇒ hotkey/EMG only. |
| `trigger_hotkey` | `str` | `""` | Optional dedicated key / EMG `COMMAND:<label>` that enters correction mode without a voice trigger. Empty ⇒ disabled. |
| `window_words` | `int` | `40` | Size of the recent correction buffer (words back from cursor) searched by `locate()`. Bounds alignment cost and candidate space. |
| `confidence_threshold` | `float` | `0.6` | Below this blended alignment confidence, route to keyboard/clipboard fallback instead of presenting candidates. |
| `max_candidates` | `int` | `3` | Number of replacement candidates presented (clamped to 1–3). |
| `phonetic_weight` | `float` | `0.5` | Blend of phonetic-key vs surface edit-distance in alignment (0 = surface only, 1 = phonetic only). |
| `splice_backend` | `str` | `"auto"` | `"streaming"` (shift+Left replace via `inject/streaming.py`), `"clipboard"` (paste replacement), or `"auto"` (probe app, prefer clipboard where shift+Left is unsafe). |
| `confirm` | `str` | `"voice"` | `"voice"` (say "one/two/three"), `"hotkey"` (cycle + accept), or `"auto_top1"` (accept top candidate **only** when its score exceeds `auto_top1_threshold` — still a presentation, never silent). |
| `auto_top1_threshold` | `float` | `0.9` | Used only when `confirm = "auto_top1"`; below it, fall back to an explicit pick. |
| `lm_rerank_model` | `str \| None` | `None` | Path to a small GGUF LM for candidate reranking. `None` ⇒ rerank disabled, candidates ordered by alignment score alone. |

Defaults are deliberately conservative: `enabled = false`, `confidence_threshold = 0.6` (route ambiguous matches to keyboard, per the ~35%/mislocation risk), and `confirm = "voice"` (never silent). `auto_top1` exists for power users but is still a presented, dismissible suggestion — there is **no** path that overwrites without the user seeing the candidate.

Example:

```toml
[punch_in]
enabled = true
trigger_phrases = ["correct that", "fix that"]
window_words = 40
confidence_threshold = 0.6
max_candidates = 3
splice_backend = "auto"
confirm = "voice"
lm_rerank_model = "/home/me/.local/share/yazses/models/qwen2.5-0.5b-q4.gguf"
```

---

## Integration

- **`core/daemon.py`** — add a `CORRECTING` sub-state (entered from `IDLE` via trigger phrase or `trigger_hotkey`, exited after a confirm/cancel or timeout). In `_on_hold_end`, when in `CORRECTING`, route the cleaned respoken text to `punch_in.punch_in()` instead of the normal `grammar.classify()` → inject path. Present candidates over the existing IPC/notification surface; apply the splice via the chosen backend; then return to `IDLE`. The normal dictation path is unchanged when not correcting.
- **`commands/grammar.py`** — add the trigger phrases as a new `IntentType` (e.g. `CORRECT`, action `enter_correction_mode`) so the existing Tier 1 classifier recognises them without an SLM round-trip. Inside correction mode, candidate picks ("one/two/three") are parsed by the daemon, not the global grammar, to avoid collisions with NAVIGATE/EDIT.
- **`inject/streaming.py`** — reuse `StreamingInjector` for the in-place splice: position at the span end, `inject_key_sequence(["shift+Left"] * len(old_text))`, then `inject(replacement)`. Gate behind the same app-compatibility caveat documented for streaming (`StreamingConfig` note: shift+Left is unsafe where it isn't "extend selection") — `splice_backend = "auto"` prefers clipboard-paste in those apps.
- **`stt/faster_whisper.py`** — enable `word_timestamps=True` on the respoken-burst transcribe so `locate()` has word offsets; optionally request alternative hypotheses (n-best) to seed `candidates()`. This is additive and only on the correction path.
- **`commands/slm_router.py`** — the optional GGUF reranker reuses the same llama-cpp loading path as the SLM router; `lm_rerank_model` may point at the same weights.
- **`config.py`** — add `PunchInConfig`; wire into the top-level config loader with full defaults (loading without the section stays valid).

---

## Dependencies

Latest stable at time of writing; new optional dep group `punch_in` in `pyproject.toml`:

```toml
[project.optional-dependencies]
punch_in = [
  "rapidfuzz >= 3.9",      # C++-backed Levenshtein / partial alignment for locate()
  "metaphone >= 0.6",      # Double Metaphone phonetic keys for homophone-robust alignment
]
```

- **`rapidfuzz`** — fast, MIT-licensed Levenshtein + partial-ratio alignment; replaces the need for FastCorrect-style training (the alignment primitive is what we need, not a learned corrector) [paper:arXiv2105.03842].
- **`metaphone`** (or an equivalent G2P/CMU-dict phonetic key) — supplies the phonetic distance that makes respoken-span matching robust across homophones [paper:arXiv1904.11024].
- **faster-whisper** — already a core dep; reused for the respoken transcribe (word timestamps + optional n-best). No new STT dependency.
- **llama-cpp-python** — already used by the SLM router; reused only when `lm_rerank_model` is set. No new dep.

Not imported unless `[punch_in] enabled = true`. Install with `uv sync --extra punch_in`.

---

## Phased plan

**Phase 0 — kill-test harness (no daemon wiring).** Implement `locate()` + `candidates()` and a CLI/test harness that takes (transcript, respoken phrase) and prints the located span + 2–3 candidates with scores. Run the §10 LOFA experiment: 40 real dictation errors, respeak once each, measure **top-3 hit rate** and **span-localisation precision**. Pre-registered gate: proceed only if the correct fix is in the top-3 for **≥ 70%** of errors and span mislocation is **≤ 15%** [paper:Suhm2001-ToCHI risk]. If it fails, re-scope to a pure "Correct \<word\>"→list UX (Dragon) and stop.

**Phase 1 — present-and-confirm, clipboard splice.** Wire the `CORRECTING` sub-state, trigger phrases, candidate presentation, and voice confirm. Splice via **clipboard-paste replacement only** (most portable). No shift+Left yet. Validate end-to-end in one editor.

**Phase 2 — cursor-tracking splice + app probe.** Add the `inject/streaming.py` shift+Left splice path and `splice_backend = "auto"` app probing. Run the app-compatibility LOFA across 5 target apps; default to clipboard where shift+Left corrupts text.

**Phase 3 — GGUF rerank + hotkey/EMG trigger.** Wire optional `lm_rerank_model` candidate reranking via the SLM-router llama-cpp path, and the dedicated `trigger_hotkey` / EMG label entry. Add `auto_top1` confirm for high-confidence cases.

Each phase is shippable behind `enabled = false`; nothing reaches users until its LOFA passes.

---

## Testing approach

- **`locate()` unit tests** — homophone cases ("their"/"there", "to"/"two"/"too"), near-misses ("bool in"/"Boolean"), repeated-word spans (correct localisation, not the first match), out-of-window phrases (returns `None` ⇒ fallback). Assert confidence ordering.
- **`candidates()` unit tests** — top-k ordering with and without the LM reranker (reranker mocked); `max_candidates` clamping; phonetic_weight extremes (0 and 1).
- **Confidence-gate tests** — below `confidence_threshold` ⇒ `fallback=True` and no candidates auto-presented; assert the daemon takes the keyboard-fallback branch.
- **Splice tests** — `StreamingInjector` shift+Left-replace produces the right final string for a span (injector mocked, assert key sequence + replacement); clipboard backend path; `auto` backend selection.
- **Daemon state tests** — enter/exit `CORRECTING` via phrase and hotkey; correction mode never fires on ordinary dictation (false-enter rate); a command intent inside correction mode exits cleanly.
- **Regression guard** — with `enabled = false`, the normal dictation path is byte-for-byte unchanged (no correction-mode code on the hot path).
- **Evidence-anchored acceptance** — the Phase 0 harness *is* a test: top-3 hit rate and mislocation rate are asserted against the pre-registered thresholds and tracked over time, so the ~35% respeak ceiling is measured, not assumed.

---

## Risks and mitigations

| Risk | Evidence | Mitigation |
|---|---|---|
| **Pure respeak corrects only ~35% and re-fails on retry** — the recognizer repeats the error | [paper:Suhm2001-ToCHI, tier2, A] | **Never auto-splice.** Present 2–3 candidates (respoken + n-best + phonetic variants, optional LM rerank) and require a one-step confirm — the multimodal route that ~doubles success [paper:Lewis-HFES]. The user picks from candidates that include hypotheses the recognizer *did* consider, breaking the same-error retry loop. |
| **Confidently-wrong alignment** — respoken phrase matches the wrong span (short/repeated phrases) | [paper:arXiv2105.03842; arXiv1904.11024] | `confidence_threshold` gate (default 0.6) routes low-confidence matches to keyboard/clipboard fallback; located span is shown before any replacement; phonetic+surface blend reduces homophone mislocation. |
| **In-place splice corrupts text** where shift+Left isn't "extend selection" | [observed:codebase, StreamingConfig note] | `splice_backend = "auto"` probes the app and prefers clipboard-paste replacement; shift+Left gated behind an app allowlist (Phase 2 LOFA). |
| **Correction mode misfires** on ordinary dictation | [observed:codebase, grammar.py] | Distinctive full-utterance trigger phrases + optional dedicated hotkey/EMG label; picks parsed only inside the mode; pre-registered false-enter kill criterion (> 1% ⇒ require hotkey). |
| **User prefers the keyboard anyway** — the in-voice path doesn't actually win | [paper:Suhm2001-ToCHI] | The fallback *is* the keyboard, so the feature never traps the user; the §10 self-trial LOFA (> 60% keyboard reach ⇒ re-scope) decides whether to keep the voice path. |
| **Latency** — alignment + n-best + LM rerank adds delay to the respoken burst | [card:Qwen2.5-0.5B sub-1B GGUF, tier4, C] | `rapidfuzz` alignment is sub-ms over a 40-word window; n-best is cheap; LM rerank optional and sub-200 ms for ≤3 short candidates; measure p95 and keep rerank off by default. |

---

## Consequences

- **No auto-splice — ever.** Every correction passes through a presented candidate the user confirms or dismisses. This is a deliberate constraint set by the strongest evidence in the file [paper:Suhm2001-ToCHI], not a UX preference, and it is the difference between this spec and the (un-shipped, un-evidenced) auto-splice dream.
- **Keyboard/clipboard is a first-class path, not a failure.** Low-confidence alignment routes to manual correction by design — the Dragon escape hatch. The feature degrades gracefully to "show me where the error is" rather than guessing.
- **Reuses existing infra.** Cursor tracking (`inject/streaming.py`), word timestamps (`stt/faster_whisper.py`), command grammar (`commands/grammar.py`), and the llama-cpp reranker (`commands/slm_router.py`) are reused; the net-new surface is one postprocess module, one config section, and a daemon sub-state.
- **Two optional deps** (`rapidfuzz`, `metaphone`) under the `punch_in` extra; not imported unless enabled.
- **Off by default.** Loading config without `[punch_in]` stays valid; the normal dictation hot path is unchanged when correction mode is inactive.
- **Shared signals with the learning loop.** The correction events (located span, chosen candidate, fallbacks) are a clean ground-truth signal for ADR-012's corpus and overlap with Mid-Thought Undo's reformulation signal — a future consolidation, flagged not built here.
- **Honest scope.** This ships the *partial* verdict from the dossier: in-voice correction that works because it designs around the respeak ceiling, not in spite of it. The auto-splice version is explicitly out of scope and recorded as a no-go with its reason [the Punch-In vision card (internal) §10].

---
### Evidence tags
`[paper:Suhm2001-ToCHI, tier2, A]` · `[paper:Lewis-HFES, tier2, B+]` · `[paper:arXiv2105.03842, tier3, A]` (FastCorrect) · `[paper:arXiv1904.11024, tier3, B+]` (phonetic alignment) · `[web:WillowVoice, tier5, C]` (Dragon pattern) · `[card:Qwen2.5-0.5B, tier4, C]` · `[observed:codebase]`. Full dossier: the 2026-06-14 ten-feature SoA dossier (internal) §3.
