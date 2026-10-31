---
pretty_name: YazSes Benchmark Results
license: cc-by-4.0
language:
  - en
  - fa
task_categories:
  - automatic-speech-recognition
tags:
  - evaluation-results
  - benchmark
  - speech-recognition
  - word-error-rate
  - real-time-factor
  - latency
  - speaker-diarization
  - whisper
  - faster-whisper
  - persian
  - offline
  - on-device
size_categories:
  - n<1K
annotations_creators:
  - machine-generated
source_datasets:
  - openslr/librispeech_asr
  - google/fleurs
  - mozilla-foundation/common_voice_17_0
configs:
  - config_name: asr_librispeech_wer
    data_files: data/asr_librispeech_wer.csv
    default: true
  - config_name: beam_sweep
    data_files: data/beam_sweep.csv
  - config_name: command_grammar
    data_files: data/command_grammar.csv
  - config_name: diarization_corpus_summary
    data_files: data/diarization_corpus_summary.csv
  - config_name: diarization_recordings
    data_files: data/diarization_recordings.csv
  - config_name: latency_decode
    data_files: data/latency_decode.csv
  - config_name: latency_pipeline_stages
    data_files: data/latency_pipeline_stages.csv
  - config_name: onset_first_word
    data_files: data/onset_first_word.csv
  - config_name: persian_asr
    data_files: data/persian_asr.csv
  - config_name: significance_beam
    data_files: data/significance_beam.csv
  - config_name: significance_diarization
    data_files: data/significance_diarization.csv
  - config_name: significance_onset
    data_files: data/significance_onset.csv
  - config_name: streaming_latency
    data_files: data/streaming_latency.csv
  - config_name: vad_gate
    data_files: data/vad_gate.csv
---

# YazSes Benchmark Results

Measured speech-recognition **results** for [YazSes](https://github.com/MSKazemi/yazses), an
open-source, fully offline hold-to-talk voice-dictation daemon (faster-whisper on CPU, int8):
word error rate, real-time factor, decode latency, memory, speaker-diarization error and
command-grammar accuracy, each row carrying the machine, software versions and corpus it was
measured on. **This is a table of numbers. It contains no audio, no transcripts and no corpora.**

> **Comparability warning.** Latency, RTF, cold-start and memory figures are properties of the
> machine they were taken on. Compare them only between rows with the same `machine` value, and
> read `load_average_1m` first: a run taken on a busy host measures the host. WER moves by up to a
> third of a point between machines and, for small checkpoints, between thread counts, so a
> tenth of a point across two machines is not a finding. Rows from different tables are
> different experiments and must never be pooled into one ranking.

## 1. Contents

Fourteen tables, one per experiment family. Each is its own Hub config, so the dataset viewer
shows them separately; their columns differ because the experiments differ.

| Config (CSV in `data/`) | Rows | What one row is | Record kind |
|---|---|---|---|
| `asr_librispeech_wer` | 11 | one engine/checkpoint on a 200-utterance LibriSpeech subset: WER, MER, error counts, RTF | measurement |
| `beam_sweep` | 22 | one `[stt] beam_size` setting of one model on one split (default-model sweep and latency-governor sweep, told apart by `experiment`) | measurement |
| `onset_first_word` | 40 | first-word accuracy and WER for one silence lead-in / clipping cell of one run | measurement |
| `latency_decode` | 3 | decode P50/P95, cold start and memory of one model | measurement |
| `latency_pipeline_stages` | 5 | per-call cost of one non-decode pipeline stage | measurement |
| `streaming_latency` | 2 | LocalAgreement streaming versus batch timings for one model | measurement |
| `vad_gate` | 1 | speech detection / silence rejection at the default energy gate | measurement |
| `command_grammar` | 1 | command-phrase accuracy and false-positive rate | measurement |
| `persian_asr` | 11 | one Persian run (model x corpus): WER/CER raw and normalised, ZWNJ, RTF | measurement |
| `diarization_recordings` | 32 | DER of one meeting recording under one configuration | measurement |
| `diarization_corpus_summary` | 2 | corpus-level DER of one diarization configuration | measurement |
| `significance_beam` | 26 | one paired-bootstrap comparison of two beam settings | significance_analysis |
| `significance_onset` | 32 | one exact-McNemar comparison of two lead-in cells | significance_analysis |
| `significance_diarization` | 2 | paired comparison of two diarization runs, per scoring collar | significance_analysis |

Total: 190 rows from 34 archived result files. `data/export-metadata.json` lists every included
source with its SHA-256, every **excluded** file with the reason it was excluded (148 of the 159
excluded files are exploratory probes, dated history copies, CI-runner smoke runs and their logs), the
row counts and the fields deliberately not exported (per-utterance arrays).

**`record_kind`.** `measurement` rows are decodes (or scorings) of real audio. A
`significance_analysis` row is a statistical analysis of a measurement already in this dataset:
it decodes nothing, and counting it beside the grid it analyses counts the same utterances
twice. The two live in separate tables for that reason. For `significance_analysis` rows the
`machine_*` columns describe the host that ran the analysis script, not the host that decoded the
audio; `analysis_of` (or `analysis_a_file`/`analysis_b_file`) names the measurement. The
vocabulary also reserves `superseded` and `withdrawn`; no included file currently carries either.

## 2. Why the dataset is generated

The numbers were already public: every figure on the project's benchmarks page is backed by a
JSON file in the author's results archive, which is kept in a private research repository. Copying them by hand into a Hub dataset
would create a second copy that can drift from the first, or be edited without leaving a trace.
So the tables are produced by a script from an explicit allowlist of those files, with a
`--check` mode that fails when the committed tables no longer match the archive. Nothing is
recomputed and no normalisation is changed: values are copied from the source JSON as written
(`4.30` stays `4.30`), and a value the source does not record is left **empty**, never `0` and
never inferred.

## 3. Version and date

* Dataset version **2.0.0**, export `schema_version` **2** (in `export-metadata.json`).
  Schema 2 drops the git commit hashes that schema 1 carried (a per-row commit column, a
  per-source commit and a source revision): they depended on git history, not on the data.
  Every row and every measured value is otherwise unchanged.
* The results were measured between **2026-07-30** and **2026-10-06** (UTC; `timestamp_utc`).
* This card was written on 2026-10-27 and updated on 2026-10-30. No output file contains the
  time it was generated or a git commit, so re-running the exporter on the same archive
  reproduces them byte for byte, in any clone and after any merge.

## 4. Source repository and revision

* Source: the author's results archive, kept in a private research repository; the published record is this dataset. YazSes itself: <https://github.com/MSKazemi/yazses>.
* Each row names its source file (`source_file`) and that file's SHA-256 (`source_sha256`);
  `data/export-metadata.json` lists every exported source with the same hash. The
  hash identifies the source file exactly and, unlike a commit hash, survives a squash merge or rebase.

## 5. How it was exported

The export script is kept with the archive, in the private research repository.

* An explicit **allowlist** of archive files; the rest of the archive is never globbed in.
  Every other file is listed in `export-metadata.json` with a reason, so a new archive file
  cannot enter or disappear silently.
* Each file is validated: required provenance (timestamp, CPU model, logical CPUs, OS, YazSes
  version) and, where present, the corpus block. A malformed record aborts the export with the
  file and field named.
* A sensitivity scan rejects home-directory paths, e-mail addresses, access tokens and
  private-tree paths in any source string and in every output cell.
* Output: CSV, `\n` newlines, stable row order, numbers copied from the source text.
* The script writes only to `huggingface/benchmarks/data/` and refuses any other target; it
  never modifies the archive.
* `data/SHA256SUMS` covers the CSVs and the metadata file (`sha256sum -c SHA256SUMS`).

## 6. Methodology

How the measurements were taken is described on the project's benchmarks page
(`docs/benchmarks.md`); in brief:

* **Accuracy.** faster-whisper (CTranslate2), int8, CPU, no GPU. English WER is scored with the
  Whisper English text normaliser on a deterministic, speaker-stratified 200-utterance subset of
  LibriSpeech `test-clean` / `test-other`. The selection rule is in `corpus_description`.
* **Beam sweeps.** `beam-test` sweeps `[stt] beam_size` on the model a user dictates with;
  `beam-governor` scores the widths the latency governor actually selects, on the models it
  uses (`tiny.en` at several widths, `small.en` at width 2). They answer different questions
  and are not interchangeable: beam 1 on `base.en` says nothing about the governor's policy.
* **Persian.** Pinned Google FLEURS `fa_ir` test split (871 rows; a 50-row seed-42 sample for the
  `test50` runs) and the pinned Common Voice `fa` test split (10,559 rows), scored raw and after
  the versioned `fa-eval-v1` normaliser, on a 4-vCPU AMD EPYC host. `curation_note` marks the
  idle-host re-measure, the run-to-run repeat and the fine-tuned checkpoints.
* **Diarization.** Meeting Mode's sherpa-onnx pipeline on 16 AMI recordings (headset mix) scored
  frame-based with Hungarian one-to-one mapping (md-eval semantics). The `maxspk4` run pins the
  speaker count to four.
* **Latency / streaming / VAD / commands.** Timings of the shipped pipeline on the 2.12/2.30
  laptop runs; command-grammar accuracy on repository fixtures.
* **Significance.** Paired bootstrap over utterances (beam; 10,000 replicates, fixed seed),
  exact McNemar with Bonferroni correction (onset), paired sign test plus bootstrap over
  recordings (diarization).

Three machines appear (see `machine`): a 13th-gen Intel Core i7-1370P laptop (20 logical CPUs),
a 16-vCPU Intel Xeon Platinum 8573C virtual machine, and a 4-vCPU AMD EPYC virtual machine.

## 7. Metrics and units

Every metric below is a **different kind of measurement**; none is interchangeable with another.

| Column family | Meaning | Unit |
|---|---|---|
| `wer_*_pct`, `mer_pct` | word error rate / match error rate on normalised text; lower is better. `wer_ci95_*` is the 95% interval published with it | percent |
| `cer_*_pct` | Persian character error rate | percent |
| `exact_match_*_fraction` | share of utterances transcribed exactly | fraction, 0 to 1 (not percent) |
| `rtf`, `rtf_mean/median/p95` | real-time factor = decode time / audio duration (below 1 is faster than real time); distribution over utterances | ratio |
| `realtime_speedup_median` | median audio seconds decoded per wall second | factor |
| `decode_*_ms`, `latency_p50/p95_ms`, `cold_start_load_s`, `*_s` | wall-clock timings; machine-bound | milliseconds / seconds as named |
| `*_rss_*_mb`, `peak_rss_mb` | resident memory | megabytes |
| `strict_*` / `collar250ms_*` DER fields | diarization error rate with no forgiveness collar / a 250 ms collar; `missed`, `false_alarm`, `confusion` are its components | percent |
| `*_der_mean_pct` vs `*_der_time_weighted_pct` | unweighted mean over recordings vs total error time over total scored speech (the NIST md-eval convention, the one comparable with the literature) | percent |
| `first_word_ok`, `n_utterances` | utterances whose first word was recovered, out of `n` | count |
| `zwnj_*` | Persian zero-width non-joiner counts, precision, recall, F1. Precision/recall/F1 are set by convention (1.0 or 0.0) when a denominator is zero; use the counts | counts / fraction |
| `p_value`, `sign_test_p`, `alpha` | statistical-test outputs of the `significance_*` tables | probability |
| `*_a_minus_b_pct`, `*_b_minus_a_pct` | signed differences exactly as the analysis defines them (the column name gives the direction) | percentage points |
| `max_speakers` | speaker-count cap passed to diarization; `0` in the unpinned run | count |

## 8. Limitations

* **Small, specific samples.** 200 LibriSpeech utterances per split, 16 AMI recordings, one
  command fixture. LibriSpeech is read audiobook speech; dictation accuracy will be worse.
* **One machine per family, mostly one run.** Only the Persian `small` checkpoint has a repeat and
  an idle-host re-measure; most cells have no run-to-run variance. Timings from different
  machines are not comparable (see the warning above).
* **Load matters.** Several runs have a high `load_average_1m` (for example 15.97 on the
  `test-other` run); their RTF describes a contended host.
* **Mixed software versions.** Rows span YazSes 2.12.0.dev4 to 2.40.1; older files lack fields
  newer ones have (for example `engine`, confidence intervals), and those cells are empty.
* **Identify a model by `model_key`, not `model`.** `model_key` is the key the source file files
  the result under (for example `base.en`) and is filled in every row. `model` and `engine` are
  copied only from files that record them explicitly, so they are empty for the older
  `wer.json` rows; filtering on `model` alone would silently drop those rows,
  including the `base.en` `test-clean` result.
* **Corpus digests are not yet recorded.** The harness can stamp a digest of the selected
  utterance ids (`corpus_sha256_16`) and a `corpus_stratified` flag, but no archived file carries
  them yet, so those columns are empty in every row rather than inferred.
* **Significance tables carry the analysis host's machine** (Section 1), and several earlier
  beam conclusions did not survive the paired test; read the analysis before quoting a gap from
  the measurement it reads.
* **Per-utterance data is not exported** (per-utterance error arrays, first-word hit strings);
  the tables carry totals and intervals only.
* **Not exported at all:** probes, history copies, CI-runner smoke runs, platform-resolution,
  plausibility and centroid-merge studies, and the superseded roll-up `index.json`; reasons are in
  `export-metadata.json`.
* Results describe the measured configuration of one open-source tool. They are not a general
  ranking of speech-recognition models, and are not intended as training data.

## 9. Reproduction

Verify the files: `cd data && sha256sum -c SHA256SUMS`.

The archive these tables were generated from, and the script that generates them, are kept in the
author's private research repository, so the tables cannot be regenerated from a clone of the public
YazSes repository. The checksum above verifies the files as published; each row's `source_sha256`
identifies the archive file it was copied from. A re-measurement on your own hardware produces new
numbers, not these; the setup is described on the project's benchmarks page (`docs/benchmarks.md`).

The `argv` column holds the command that produced a row where the archive recorded one (home
directories appear as `$HOME`); older files predate the field and the column is empty.

## 10. Citation

If you use these results, please cite the YazSes paper (arXiv:2607.28878):

```bibtex
@article{seyedkazemi2026yazses,
  title   = {YazSes: An Offline, Privacy-First, Cross-Platform Hold-to-Talk Voice-Dictation System},
  author  = {Seyedkazemi Ardebili, Mohsen},
  journal = {arXiv preprint arXiv:2607.28878},
  year    = {2026},
  url     = {https://arxiv.org/abs/2607.28878}
}
```

The software has a Zenodo concept DOI, [10.5281/zenodo.21856271](https://doi.org/10.5281/zenodo.21856271).
Please also cite the corpora behind the rows you use, for example LibriSpeech (Panayotov et al.,
ICASSP 2015), Google FLEURS, Mozilla Common Voice and the AMI Meeting Corpus.

Author: Mohsen Seyedkazemi Ardebili, <https://mskazemi.com/yazses/>.

## 11. Provenance

Every row ends with the same provenance columns: `source_file`, `source_pointer` (where in the
source JSON the row came from), `source_sha256`, `timestamp_utc`,
`machine` (CPU model / logical CPUs / RAM / OS joined) plus its parts, `yazses_version`,
`faster_whisper_version`, `ctranslate2_version`, `compute_type`, `device`, `omp_num_threads`,
`load_average_1m`, `corpus_name`, `corpus_split`, `corpus_n`, `corpus_sha256_16`,
`corpus_stratified`, `corpus_version`, `corpus_description`, `argv` and `curation_note`
(a note added by the exporter's allowlist, not copied from the source). Each is copied from the
source file's own provenance block or config; the exporter fills nothing in by inference. The
kernel, Python and NumPy versions in the source provenance are not exported.

## 12. License and redistribution

The tables are released under **CC BY 4.0** (`license: cc-by-4.0`).

* The dataset contains only numbers derived by running software, plus identifiers (model names,
  AMI meeting ids, split names, file names). It reproduces no audio, no transcript text and no
  corpus content.
* The corpora behind the measurements are LibriSpeech (CC BY 4.0, OpenSLR 12), Google FLEURS
  (CC BY 4.0), Common Voice `fa` (CC0 1.0) and the AMI Meeting Corpus (CC BY). None is
  share-alike or non-commercial, so an attribution licence on the derived tables is compatible
  with every corpus measured. Attribution is the common condition, and CC BY keeps it visible.
* The repository's code, including the exporter, is Apache-2.0; that licence is written for
  software, not data, which is why the tables are licensed separately.
* Results about third-party models are facts about those models as measured here; no model
  weights are redistributed. The fine-tuned Persian checkpoint measured in two rows is
  Apache-2.0 (`steja/whisper-small-persian`).

## 13. What this dataset does not contain

It contains **no audio** and **no user voice recordings** of any kind: no microphone captures, no
dictation history, no voiceprints, no learning-corpus material and no research-participant data.
It contains no transcripts or reference texts. Rows are aggregate metrics over public benchmark
corpora that are not redistributed here. YazSes itself runs offline and sends nothing off the
machine; this dataset is a separate, voluntarily published set of benchmark numbers.
