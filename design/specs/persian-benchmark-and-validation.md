# Persian Benchmark and Validation Specification

**Status:** Proposed  
**Purpose:** define reproducible evidence for Persian model selection and release qualification.

---

## 1. Questions the benchmark must answer

1. Which local model gives the best Persian accuracy/latency trade-off in YazSes?
2. How much do results vary across speakers and corpora?
3. Does Persian normalization improve text consistency without hiding ASR errors?
4. Does text survive injection on Linux, macOS, and Windows?
5. How well does the current `fa-en` Polyglot path handle code-switching?
6. Can another contributor reproduce the result?

## 2. Evaluation corpora

Use at least two independent public sources.

### Corpus A — Mozilla Common Voice Persian

Purpose:

- broader speaker variability;
- community-recorded speech;
- accent/microphone diversity.

Use a fixed released dataset version and fixed split. Store dataset version and sample IDs/manifests, not audio blobs, where licensing allows.

### Corpus B — Google FLEURS `fa_ir`

Purpose:

- stable multilingual comparison;
- consistent evaluation structure;
- independent source from Common Voice.

Pin dataset revision/version.

### Optional Corpus C — project field set

A small opt-in set may cover dictation-specific vocabulary, but:

- no private recording is committed without explicit consent and suitable license;
- contributors may submit metrics/results without submitting their audio;
- field data must never replace public-corpus results.

## 3. Model matrix

Minimum:

- Whisper base (multilingual);
- Whisper small;
- Whisper medium;
- Whisper large-v3;
- Whisper large-v3-turbo if supported reproducibly by the pinned runtime.

Optional Persian-specific checkpoints may be evaluated only if all are documented:

- license;
- source repository/model card;
- training-data description;
- conversion procedure to supported runtime;
- hash/revision;
- inference settings.

Do not evaluate `.en` models as Persian candidates except for a negative guard test proving they are rejected/diagnosed.

## 4. Runtime matrix

Primary project policy is CPU-first.

Record:

- CPU model;
- architecture;
- RAM;
- OS and version;
- YazSes commit;
- Python version;
- faster-whisper version;
- CTranslate2 version;
- compute type;
- thread count;
- beam size;
- condition_on_previous_text;
- language;
- task;
- model revision/hash where available.

GPU may be reported separately but must not replace CPU evidence for the default recommendation.

## 5. Metrics

### Recognition

- WER;
- CER;
- utterance-level exact match;
- number-token accuracy;
- named-entity/proper-noun subset where annotated.

### Persian text quality

- Arabic Yeh/Kaf variant count;
- ZWNJ precision/recall on references containing U+200C;
- mixed-script preservation;
- punctuation difference rate.

Report both:

1. **raw** metrics on model output;
2. **evaluation-normalized** metrics.

Never report only normalized WER because normalization can hide errors.

### Code-switch

For `fa-en`:

- mixed error rate (MER);
- language-boundary error rate;
- English-token preservation;
- Persian-token CER;
- span-language classification accuracy where observable.

The exact definitions, categories, consent template and held-out split are frozen in
[persian-code-switch-evaluation.md](persian-code-switch-evaluation.md) (`fa-en-cs-v1`).

### Performance

- real-time factor;
- p50/p95 utterance latency;
- model load time;
- peak RSS if available;
- disk size/cache size.

## 6. Evaluation normalizer

The metric normalizer is separate from the production Persian normalizer.

Version it explicitly, for example:

```json
{
  "evaluation_normalizer": "fa-eval-v1"
}
```

Safe evaluation normalization may include:

- Unicode NFC;
- canonical Persian Yeh/Kaf mapping;
- standardized whitespace.

Any digit or punctuation normalization must be separately reported because it can materially alter WER/CER.

Historical result files must retain the normalizer version used at generation time.

Tokenisation (stamped into each result as `metrics.tokenisation`): WER tokens are the
whitespace-separated words of the normalized text, so a ZWNJ-joined compound is one token;
CER is over Unicode code points, spaces and ZWNJ included; both are case-sensitive. In
`fa-eval-v1` the ZWNJ is kept, Persian/Arabic-Indic/Latin digits are not folded into one
another, and Arabic presentation forms, tashkeel, tatweel and bidi marks are not stripped;
the rule-by-rule rationale is in `benchmark/persian_metrics.py`. Changing any of these
is a new normalizer version, never an edit to `fa-eval-v1`. Evaluation normalization is for
metrics only and is never applied to text a user receives.

### 6.1 Manifest contract

Each manifest row has `id`, `audio`, `reference`, and optionally `speaker` and `session`
(opaque pseudonyms, `[A-Za-z0-9_-]{1,64}`). A `license` and a `consent` value are required
for every row, from the row or from the `<manifest>.meta.json` sidecar. The harness refuses
to run when either is missing or a placeholder, and when an audio path resolves outside the
manifest directory or the explicit `--audio-root`. It checks that the claims are made; it
cannot verify them. Subset selection (`--limit`, `--seed`) is recorded in the sidecar and
copied into the result's `selection` block.

## 7. Result schema

Each result JSON should include:

```json
{
  "schema_version": 1,
  "yazses_commit": "...",
  "timestamp_utc": "...",
  "corpus": {
    "name": "common-voice",
    "language": "fa",
    "version": "...",
    "split": "test",
    "samples": 0
  },
  "model": {
    "engine": "faster-whisper",
    "name": "small",
    "revision": "...",
    "compute_type": "int8"
  },
  "decoder": {
    "language": "fa",
    "beam_size": 5,
    "condition_on_previous_text": false
  },
  "machine": {
    "os": "...",
    "cpu": "...",
    "ram_gb": 0
  },
  "metrics": {
    "wer_raw": 0.0,
    "cer_raw": 0.0,
    "wer_normalized": 0.0,
    "cer_normalized": 0.0,
    "rtf": 0.0,
    "latency_p50_ms": 0.0,
    "latency_p95_ms": 0.0
  }
}
```

Validate the schema in CI.

## 8. Sampling policy

For development smoke tests, use a small deterministic subset.

For model-selection results:

- evaluate the full official test split when practical;
- otherwise define a deterministic sample selection rule before seeing model outputs;
- publish sample count and selection seed/hash;
- do not cherry-pick utterances after inspecting errors.

## 9. Model recommendation rule

The repository should not use a single accuracy number as the decision.

A candidate preset must satisfy:

- materially better Persian error rate than the smaller baseline, or comparable accuracy with materially lower latency;
- acceptable CPU RTF for hold-to-talk use;
- no unstable/run-to-run decoding behavior that undermines reproducibility;
- memory compatible with the documented target class of machines;
- supported license/runtime.

Publish the full table. The preset is the project default recommendation, not a claim that it is best on every machine.

## 10. Cross-platform injection validation

Use a deterministic target harness that captures received Unicode text.

The harness is `scripts/injectmatrix/` (#517): a Tk receiver that records arriving code points,
a driver that types each fixture through `yazses inject`, a comparator that reports the first
divergence, and a result format that names OS, session, backend and versions. The procedure and
the results table are in `docs/contribute/persian-injection-matrix.md`.

Matrix:

| OS | Backend | Persian | Mixed fa/en | ZWNJ | URL/path | Multiline |
|---|---|---|---|---|---|---|
| Linux X11 | xdotool/unicode/clipboard as applicable | required | required | required | required | required |
| Linux Wayland | ydotool/wtype/clipboard as applicable | required | required | required | required | required |
| macOS | native/clipboard | required | required | required | required | required |
| Windows | native/clipboard | required | required | required | required | required |

Pass condition: exact code-point equality for tested strings, plus human visual verification of bidi layout.

## 11. Human validation

At preview stage, recruit at least three native Persian speakers.

Collect:

- OS;
- CPU/device class;
- microphone;
- model/config;
- 10-20 minutes of normal use;
- qualitative error categories;
- perceived latency;
- mixed Persian-English behavior;
- injection/display defects.

Do not require users to submit recordings or private dictated text. A tester can report counts/categories without sharing content.

## 12. Accessibility validation

Persian support must be tested with the same accessibility expectations as English where relevant:

- keyboard-only configuration;
- screen-reader labels in Settings;
- transcript copyability;
- no visual-only error state;
- correct focus behavior;
- high-DPI text rendering;
- no loss of Persian text when using clipboard fallback.

## 13. Regression policy

Every Persian change must run:

- Persian unit/contract tests;
- existing English contract tests;
- command-safety tests;
- multilingual model/language compatibility tests.

A Persian normalization improvement that changes English output is a regression unless separately designed and reviewed.

## 14. Release evidence package

A Persian preview release should link to:

- benchmark protocol revision;
- result JSON files;
- summarized comparison table;
- injection matrix;
- known limitations;
- native-review status;
- open Persian issues.

The release note should say exactly what was measured and avoid broader claims such as "full Persian support" unless P3 gates are met.

## 15. Suggested CI split

Keep CI affordable:

- every PR: unit, property, contract, schema validation;
- benchmark-code PR: 10-50 sample smoke run;
- scheduled/manual benchmark: full corpus matrix;
- release candidate: full selected Persian benchmark + injection/human checklist.

Large model downloads and full-corpus evaluations should not run on every ordinary PR.
