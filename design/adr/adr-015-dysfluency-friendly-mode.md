# ADR-015 — Dysfluency-Friendly Mode (collapse pass + accessibility preset)

**Status:** Accepted (2026-06-19)
**Context links:** [[adr-011]] (zero telemetry / offline), [[adr-012-self-improvement-loop]] (the corpus that could later evaluate this), [[adr-013-llm-cleanup]] (guarded text-transform philosophy)

## Context

YazSes names **accessibility-OS** as one of its four product axes, but offered no
specific accommodation for atypical speech. A vision-lab review (2026-06-19) developed
**Dysfluency-Friendly Mode** into a Vision Card
(internal) that scored **GO (22/25,
regret 4/5, reputation/learning 5/5)** — the top "ship-now" pick.

Its load-bearing evidence — Lea/Wu et al., *"Enabling People Who Stutter to Better Use
Speech Recognition,"* CHI 2023 (`doi:10.1145/3544548.3581224`) — found that most of the
ASR gain for people who stutter comes from **endpointing + posthoc text refinement**
(removing repetitions), taking a consumer system from WER 25.4% → 9.9% and cutting
truncation 79.1%, **without** acoustic retraining. The population is large (~1% stutter;
most Parkinson's patients develop dysarthria) and already uses ASR despite it failing
them (32.2% daily in the same survey).

YazSes already owns a guarded 3-pass disfluency filter (`stt/filters/disfluency.py`)
with an `_is_protected` guard for proper nouns / code / URLs. The one genuine build gap
the card identified (its two `critical` gaps) was: a **sub-word repetition + prolongation
collapse pass** the existing whole-word 2-gram dedup misses, and an **evaluation** that
proves it does not damage clean text (we have no local affected-user audio).

## Decision

Add an **opt-in collapse pass** (Rule B.5) to the disfluency filter, plus a one-switch
accessibility preset, all **off by default** so the default pipeline is byte-identical.

1. **Collapse pass** (`stt/filters/disfluency.py`), inserted after 2-gram dedup and
   before self-correction rollback, every operation skipping `_is_protected` tokens:
   - `_collapse_prolongations(text, min_run)` — a same-letter run of length ≥ `min_run`
     (default 3) collapses to one letter (`sooo`→`so`); English double letters (run 2)
     stay safe.
   - `_collapse_repetitions(text, max_fragment_len)` — three **conservative** forms:
     (a) hyphenated false starts with ≥2 identical leading fragments that prefix the
     final word (`b-b-because`→`because`); (b) ≥2 identical short (≤ `max_fragment_len`,
     default 2) space-separated fragments followed by a longer word they prefix
     (`b b because`→`because`); (c) unigram runs of length ≥3 (`the the the`→`the`).
   - Driven by four `DisfluencyConfig` flags (`collapse_repetitions`,
     `collapse_prolongations`, `prolongation_min_run`, `repetition_max_fragment_len`),
     all default off.

2. **Master preset** — `AccessibilityConfig.dysfluency_friendly` (default off). When set,
   `config._apply_presets` enables both collapse flags and widens
   `pre_speech_padding_ms` to ≥ 400 ms (delayed voice onset is common in dysarthria).

3. **Pre-registered evaluation gate** (`tests/test_dysfluency_eval.py` over
   `tests/fixtures/disfluency/dysfluency_eval.json`) encodes the card's LOFA-1 kill
   criteria as an automated regression test: **false-collapse < 2% on clean control AND
   recall ≥ 60% on labelled dysfluency spans.** Measured at ship: **0% false-collapse,
   92.9% recall.**

4. **`yazses doctor`** reports the mode's status when enabled.

## Scope decision — endpointing is out (and why)

The CHI-2023 result also credits **forgiving endpointing**. This **does not transfer to
YazSes's core path**: YazSes is **hold-to-talk** — the user holds the key through a block
or pause and releases when truly done, so utterance end is a key release, not an
auto-endpointer decision. (`AccessibilityConfig.min_silence_ms` is, in fact, currently
stored but **not consumed** by the daemon.) Truncation-by-endpointer would only matter on
the off-by-default streaming / Ghost-Ahead speculative-finalize path. So the preset's only
endpointing-adjacent action is widening onset padding; it makes **no** claim to fix
endpointer truncation. The endpointing question is parked (see the card / plan Open
Questions), not silently dropped.

## Alternatives rejected

- **Acoustic model fine-tuning / LoRA for atypical speech.** The bigger lever for severe
  dysarthria, but needs training data + adapters and is the **v2.0 roadmap item**, not
  this. This pass stacks *under* any future adaptation. Out of scope by design.
- **Aggressive collapse (collapse any repeat / any double letter).** Rejected — it fails
  the < 2% clean-control bar (would eat `re-read`, `co-op`, `very very`, `committee`).
  Conservatism (≥2 leading fragments, ≥3 unigram run, ≥3 letter run, `_is_protected`) is
  deliberate; the eval gate enforces it.
- **On-by-default.** Rejected — honours the "default pipeline unchanged" rule and ADR-011.

## Consequences

- A person who stutters / has dysarthria flips `[accessibility] dysfluency_friendly =
  true` and gets clean text today — offline, on CPU, no model, no new dependency.
- Two documented conservative misses (`b-because` single fragment; `I I` protected by
  capitalisation) — accepted trade-offs; loosening them would breach the clean-control
  bar.
- Prolongation collapse-to-1 can mis-handle rare ≥3 double-letter words (`welllll`→`wel`);
  bounded by the clean-control gate, revisit only if it shows real damage.
- The eval fixture is a reusable harness; if UA-Speech/TORGO/SEP-28k become available it
  can be strengthened. All in-house WER claims stay `[unverified]` until measured on real
  affected-user audio (real-user validation is the card's remaining value LOFA).
