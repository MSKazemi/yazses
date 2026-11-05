# ADR-034 — Whether to recommend Parakeet where it loads (default-engine decision, proposed)

**Status:** Proposed (2026-11-04; figures and file references re-checked against `main` on 2026-11-05) · no runtime, config, default, CLI or test change; awaiting the maintainer's decision  
**Decision owner:** YazSes maintainer (pending). Changing `[stt] engine`'s default is L3 work (AGENTS.md, "Public interfaces").  
**Tracking:** [#645](https://github.com/MSKazemi/yazses/issues/645) (TRUTH-ENGINE-002)  
**Context:** [ADR-030](adr-030-agent-era-direction.md) §2 Pillar 1.3, [ADR-033](adr-033-reproducible-asr-evaluation-gate.md) (Proposed), [ADR-011](adr-011.md), [ADR-019](adr-019-egress-inventory-and-escalation.md), [ADR-021](adr-021-invest-in-error-cost.md), [ADR-028](adr-028-feature-addon-packs.md)

Evidence labels: **[R]** a file in this repository says so (path and conditions quoted) ·
**[F]** an upstream model card says so, as cited in `src/yazses/language/capability.py` ·
**[O]** engineering judgement · **[U]** unmeasured. Nothing in this ADR was benchmarked
for it; every figure is quoted from an existing file, and where a comparison the decision
needs was never made on comparable conditions, it says *unmeasured* and does not estimate.

## Context

ADR-030 Pillar 1.3 says the engine question is answered by measurement, that a change of
default engine is an L3 config change needing its own ADR, and that a Parakeet that fails
to load must say so loudly. The loudness half is done ([#644](https://github.com/MSKazemi/yazses/issues/644),
CHANGELOG 2.45.0: `yazses status` names the decoding engine and prints a `FALLBACK:` line).
This ADR is the other half: should YazSes *recommend* Parakeet, and how?

### What is measured

All of the following is from [`docs/benchmarks.md`](../../docs/benchmarks.md), section
"Every engine, measured against every other" [R]: 200 LibriSpeech `test-clean` utterances
(speaker-stratified, 40 speakers), Whisper `EnglishTextNormalizer`, one 16-vCPU Intel Xeon
Platinum 8573C VM, Ubuntu 24.04, CTranslate2 4.8.1, int8 on CPU, every engine built
through `stt.factory.build_engine`.

| Engine / model | WER | 95 % CI | Sub / Del / Ins | RTF (lower = faster) |
|---|---|---|---|---|
| `parakeet-tdt-0.6b-v2` | 2.06 % | 1.54–2.68 | 73 / 12 / 11 | 0.050 |
| `small.en` | 2.66 % | 2.05–3.28 | 100 / 16 / 8 | 0.092 |
| `large-v3` | 3.23 % | 1.95–5.00 | 62 / 8 / 89 | 0.451 |
| `base.en` (shipped default) | 4.01 % | 3.21–4.87 | 141 / 16 / 30 | 0.042 |

Same page, section "How much worse: the same models on `test-other`" [R] (200 utterances,
33 speakers, same machine and method): Parakeet 2.88 % (1.4x its clean figure), `small.en`
5.59 %, `base.en` 9.46 %. Same page, "The same number, measured twice": Parakeet and `base.en`
were bit-identical across repeated runs on both splits [R].

Readings the page itself supports, and two it does not:

- Against the shipped default on this corpus and machine, Parakeet's point estimate is about half
  `base.en`'s WER on clean audio and under a third on `test-other` (2.88 % vs 9.46 %). The two
  clean-split marginal intervals (1.54–2.68 vs 3.21–4.87) do not overlap, but that is not a paired
  test; no paired, speaker-clustered test was run [U]. The page itself warns that Parakeet vs
  `large-v3` overlaps and is "not something 200 utterances establish".
- The `large-v3` row is one of several runs on this machine (`test-clean`: 3.23 %, 3.41 %,
  3.98 %; on `test-other` the page says it "cannot be ranked at all"). The Parakeet, `base.en` and
  `small.en` rows were identical in every run [R]. Quoting `large-v3` at 3.23 % is therefore
  the favourable end of its range, which is also the figure `yazses features` and ADR-030 use.
- Parakeet is **not faster than the default**: RTF 0.050 vs 0.042 on the same box, i.e. about
  19.8x vs 24.1x real time (same table). "About twice `small.en`'s speed" (0.092/0.050) is true
  but is not the comparison a default change makes.
- Everything is read audiobook speech [R]. The page says its own numbers are "a comparison
  between models, not a promise about your desk". Spontaneous dictation, accented speech and a
  real microphone are [U] for Parakeet.

### What is not measured [U]

- Parakeet on a consumer laptop CPU: the only Parakeet row is the Xeon VM above. The laptop
  tables in `docs/benchmarks.md` and `docs/models.md` (i7-1370P; Ryzen 5 PRO 4650U) contain no
  Parakeet row.
- Release-to-final latency, cold model-load time and resident/peak memory for Parakeet. The
  upstream card for v2 states only "at least 2GB RAM for model to load" [F]. The latency
  figures elsewhere in `docs/benchmarks.md` and `docs/models.md` are single-run historical
  numbers that the pages themselves say were never reconciled with the Xeon matrix; do not
  mix the two sets in one comparison.
  `docs/benchmarks.md` "Memory" and `docs/models.md` list `tiny.en`, `base.en`, `small.en`
  only (base.en: 202 MB after load, 342-344 MB peak, Ryzen 5 PRO 4650U, 2026-10-21).
- Behaviour on silence and trailing room tone. `src/yazses/stt/parakeet.py` states Parakeet
  "does not hallucinate text on silence"; the measurement behind it is 11 inserted words vs
  `large-v3`'s 89 on 200 utterances **of speech**. That is an insertion count on speech, not a
  silence test.
- Whether losing `initial_prompt` priming costs a user with a personal vocabulary more than the
  engine gains; and how well `[stt] vocab_correction` substitutes. Neither was compared.
- Parakeet TDT v3 (25 European languages [F], `language/capability.py`): no YazSes measurement
  of any kind.
- macOS and Windows dictation are still labelled preview (ADR-030 Pillar 1.1); Parakeet there
  is a fortiori unverified.
- How often Parakeet fails to load across real installs. Not measurable by design: there is no
  telemetry (AGENTS.md rule 1, ADR-011). Only opt-in reports can inform it.

### Facts about the engine that any recommendation must carry

| Fact | Source |
|---|---|
| English-only for the default checkpoint `nemo-parakeet-tdt-0.6b-v2` ("designed for high-quality English transcription") | `src/yazses/language/capability.py` [F] |
| A `[stt] language` the resolved engine cannot do is *refused* (`LanguageUnsupportedError`), not fallen back from | `src/yazses/stt/factory.py` (#515) [R] |
| `initial_prompt` is accepted and ignored; `task="translate"` is unsupported; `transcribe_words` returns no word timings, so prosody and confidence decorations are skipped | `src/yazses/stt/parakeet.py` [R] |
| The personal dictionary reaches Parakeet only through `[stt] vocab_correction`, which is `False` by default | `src/yazses/config.py` line 120; `docs/models.md` [R] |
| Model download about 600 MB on first use (`stt-parakeet` ~604 MB, 1 package) vs base.en 148 MB, so about 456 MB more | `docs/install-cost.md`; `docs/models.md` [R] |
| The dependency `onnx-asr` is an optional extra (`stt-parakeet`), imported lazily; the Linux snap does not bundle it; the Windows installer bundles the library but not the model | `src/yazses/system/features.py`; `docs/install-linux.md`; `docs/install-cost.md` [R] |
| The feature is tier OPTIONAL, so the first-run seeded config (`system/firstrun.py::ensure_recommended_config`) does not enable it; no setup flow offers an engine choice today | `src/yazses/system/features.py`, `firstrun.py` [R] |
| A failed load degrades to faster-whisper `base.en`, with a `FALLBACK:` line in `yazses status` and a doctor `WARN` for a missing dependency. Doctor reads the environment (`find_spec`), so it cannot see an installed package whose model fails to load | `stt/factory.py`; `system/doctor.py::_configured_engine_check`; `docs/architecture.md` [R] |

### Why "where it loads" is not a formality

Parakeet has failed silently in practice, for reasons that were not the user's: CHANGELOG
2.37.2 records that `uv tool upgrade` deleted an enabled Parakeet's `onnx-asr` and dictation
fell back to a smaller Whisper model "with nothing surfaced anywhere" (fixed; the 2.44.0
entry "an update could still delete an enabled feature's libraries" closes the remainder).
That 2.37.2 entry and `docs/architecture.md` both say the configured-but-absent case was found on a
real machine: `engine = "parakeet"` with `onnx_asr` missing, decoding on `base.en`. A separate
CHANGELOG entry ("Cache-first model loading left offline mode switched on, so Parakeet could
never download") records that `features enable stt-parakeet` appeared to succeed while dictation
stayed on faster-whisper. All three are fixed and now visible; they show that "configured" and
"running" have differed for real users, which is why a load probe is part of Option B. How many
installs are affected today is [U].

## Decision options

The maintainer is asked to choose one. None is implemented by this ADR.

### Option A — Keep faster-whisper `base.en` as the default and make no new recommendation

Parakeet stays as today: documented in `docs/models.md` ("best English accuracy per unit of
CPU"), listed in `yazses features`, enabled by the user with `yazses features enable stt-parakeet`.

- Privacy / rule 1: unchanged; the only network use remains the user-initiated model download.
- Rule 3: unchanged; extra stays optional and lazy.
- Rule 2: nothing new, so nothing to default off.
- Cost: users who would benefit never learn of it unless they read the models page. The
  `yazses features` text for `stt-parakeet` already states 2.06 % against `large-v3`'s 3.23 %,
  English-only and the ~600 MB download (`src/yazses/system/features.py`), but it does not
  compare Parakeet with the shipped default (`base.en`, 4.01 %), which is the comparison a user
  deciding whether to switch needs. So discoverability is partial rather than absent.

### Option B — Recommend Parakeet only where it loads and passes a probe; never switch automatically

A recommendation, surfaced as advice, never a config write. It would be shown only when **all**
hold:

1. `[stt] language` is supported by the Parakeet checkpoint per `language/capability.py`
   (initially `en` with v2 only; v3 languages only after they are measured);
2. `onnx_asr` is importable;
3. the checkpoint is already cached, so the advice and the probe cause no download. The existing
   `stt.download.is_cached` is built for Whisper repo names; whether it detects the onnx-asr
   cache layout is not verified here and would have to be established first;
4. a smoke load and one decode of a bundled or synthetic clip succeeds with
   `describe_active_engine(...)["engine"] == "parakeet"` and no `fallback_from`. Loading a
   ~600 MB model costs seconds and memory, so this would be an explicit user command, not a
   background check. [O]

Surfaces, in increasing order of reach; the maintainer may take any prefix:

- **B1: `features` advice.** Already largely present. The change would be wording only: state
  the measured conditions (Xeon VM, clean read speech) and the English-only, no-priming and
  download costs beside the WER, so the claim is not read as a laptop dictation promise.
- **B2: a `yazses doctor` / `yazses status` hint** when conditions 1-3 hold and the engine is
  still faster-whisper: one line, naming the enable command. New wording, no behaviour change.
- **B3: an offer in a setup or first-run flow.** There is no engine-choice step today. This
  adds one, so it is the largest scope, and ADR-030's freeze permits only work within the four
  pillars (Pillar 1.3 arguably covers it).

Consequences:

- Rule 1: no new egress. The ~600 MB download already exists behind `features enable` and is
  already classified; B must not trigger it, which condition 3 enforces.
- Rule 2: advice only, so an existing install is unchanged until the user acts.
- Rule 3: no change to dependencies.
- The probe (condition 4) is new code and needs tests with a fake `onnx_asr`; the
  pure/injected-backend split of AGENTS.md rule 5 applies.
- Residual risk: a user acts on a recommendation grounded in read-speech WER and gets worse
  results on their own vocabulary (no priming). Mitigated by stating the cost in the advice;
  not eliminated, because the size of that effect is [U].

### Option C — Make Parakeet the default where it is installed

e.g. an `engine = "auto"` or a changed default that selects Parakeet when `onnx_asr` is present
and the language is `en`.

- Rule 2: this is the opposite of "an existing install is unchanged until the user opts in".
  Any existing install that has the package (the feature enabled for any reason, or a Windows
  installer, which bundles the library) would change engine on upgrade.
- Rule 1 / ADR-019: on an install that has the package but not the checkpoint, the first load
  would start a ~600 MB download the user did not request. That would need an explicit
  escalation entry or a rule that it never downloads implicitly; the second makes "default where
  installed" mean "where installed *and cached*", which is Option B's condition set.
- `initial_prompt` priming and `vocab` would silently stop applying for those users; the existing
  vocabulary feature is documented as priming the decoder (`docs/settings-gui.md`).
- Word timings and translate would disappear for them (see facts table).
- Evidence needed for C is the entire list below, not part of it. It is the only option that
  changes what existing users get without their action.
- A silent-fallback incident under C changes from "user chose Parakeet and lost it" to "user
  never chose Parakeet and was moved off it", a worse honesty position even with #644's status line.

### Option D — Make Parakeet the default for every fresh install

Listed for completeness; **not proposed**. It makes a ~600 MB download part of first run
(against rule 3's "a fresh install with no extras must import and run"), is English-only against
a project whose language plan includes Persian and Mandarin work (Persian is not in the v3 list
either, `language/capability.py`), and is unsupported by the evidence above on every
[U] item.

## What evidence would settle it

Per ADR-033 (Proposed), a *new* default-engine comparative conclusion needs its protocol v1:
pinned model/runtime identity, the *resolved* engine asserted (the benchmark must not score a
silent Whisper fallback as Parakeet), per-sample failures kept in the denominator, speaker-
clustered paired uncertainty, warmed decode separated from cold load and release-to-final. If
ADR-033 is not accepted, the same requirements stand as the bar this ADR sets for itself.

| Needed for | Measurement | Today |
|---|---|---|
| B1, B2 | None beyond quoting the existing Xeon rows with their conditions and the English-only caveat | Available [R] |
| B2, B3 | Parakeet vs `base.en` on a consumer laptop CPU: WER, release-to-final p50/p95, cold load, peak RSS | [U] |
| B3, C | Paired speaker-clustered WER difference, Parakeet vs `base.en`, on test-clean and test-other | [U] (marginal intervals only) |
| B3, C | Spontaneous / real-microphone speech (the protocol names Common Voice Spontaneous Speech as a candidate) | [U] |
| B3, C | Silence and no-speech stress: words inserted per second of non-speech | [U] |
| C | Personal-vocabulary accuracy: Whisper with `initial_prompt` vs Parakeet with `vocab_correction`, same word list | [U] |
| C | Probe pass rate across real installs on Linux, macOS, Windows, snap, `.exe` | [U], opt-in reports only |
| any multilingual claim | Parakeet v3 per-language results | [U] |

## Assessment

**My reading of the evidence, with confidence stated.**

- *High confidence:* the evidence does not support C or D. C changes what existing users get
  without opt-in (rule 2), and most rows C needs are unmeasured.
- *Moderate confidence:* the evidence supports B1 and B2 for English-configured users whose
  Parakeet already loads. Basis: a 2x lower point-estimate WER on clean read speech and under 1/3
  on `test-other` than the shipped default on one machine, bit-reproducible, with the costs
  (English only, no priming, 456 MB more download, decode no faster than `base.en`) stated in the
  advice. Why only moderate: one machine, read speech only, no paired test, and the user-visible
  effect on personal vocabulary and latency is unmeasured.
- *Low confidence, and I do not recommend it on current evidence:* B3, because it puts the
  advice in front of people who have not looked for it, before laptop latency and vocabulary cost
  are known.
- A is defensible if the maintainer judges that advice beyond what `yazses features` already says
  is not worth the surface. The evidence neither requires nor forbids it.

## Decision needed from the maintainer

1. Choose **A**, **B** (and how far: B1 only, B1+B2, or B1+B2+B3) or **C/D**. This ADR recommends
   nothing beyond B1+B2 on current evidence.
2. If B: is the probe (condition 4) an explicit command, a `doctor` flag, or dropped in favour of
   the cheaper conditions 1-3?
3. Is ADR-033's protocol the required bar before B3 or C, or is a smaller matched run enough?
4. Which CPU classes count for the laptop run (the table above leaves this open)?
5. If any option is accepted: is it an ADR-030 Pillar 1.3 act, or does it need an amendment under
   the breadth freeze?

## Non-goals

No default, config key, code path, CLI flag, test or dependency changes. No new benchmark was
run. No claim about Parakeet on hardware, languages or speech styles listed [U]. Nothing here is
accepted until the maintainer changes the status line.
