# Benchmark results

The artifacts behind every number on [`docs/benchmarks.md`](../../docs/benchmarks.md)
and in the paper's Evaluation section. One JSON per experiment, written by the
harness in [`../benchmark/`](../benchmark/README.md).

These are committed on purpose. The page's central claim is that its numbers can be
reproduced, and half of that promise is the harness while the other half is the run it
produced: the machine it was taken on, the library versions, the load average, and
every per-row figure that did not fit on the page. While this directory was gitignored
that half existed on one laptop and nowhere else — not reproducible, not citable, and
impossible to compare a later run against.

**Start with [`MANIFEST.md`](MANIFEST.md)** — one row per archived artifact, naming
what it measures, the machine it was taken on and when. It is generated from the
files themselves (`uv run python paper/benchmark/make_results_index.py`), so it
cannot fall behind them without failing `tests/test_results_manifest_is_current.py`.
Two numbers on this page are comparable only if their `Machine` column matches.

## Reading one

Every file carries a `provenance` block and **must** — `write_result` stamps one when
the caller does not, and `tests/test_benchmark_results_are_archived.py` fails the build
on a file without it.

```json
"provenance": {
  "timestamp": "2026-07-30T21:17:57Z",
  "cpu_model": "13th Gen Intel(R) Core(TM) i7-1370P",
  "logical_cpus": 20, "ram_gb": 33.3,
  "os": "Ubuntu 24.04.4 LTS", "kernel": "7.0.0-28-generic",
  "python": "3.12.3", "faster_whisper": "1.2.1", "yazses": "2.12.0.dev4",
  "ctranslate2": "...", "omp_num_threads": "unset", "load_average_1m": 0.4
}
```

Three rules for using these files, each learned the expensive way:

* **Latency and RTF are properties of the machine.** Merging timings from two hosts
  into one table is a defect, not a summary. Read the `cpu_model` and the
  `load_average_1m` before comparing anything timed — a run of this matrix was once
  invalidated by contention the operator created on the same box.
* **WER is very nearly a property of the model, and *nearly* is the interesting part.**
  CTranslate2's int8 reduction order depends on the ISA and the thread count, so
  `tiny.en` moved 4.78 → 4.95 % across thread counts on one laptop while `base.en` and
  `small.en` did not move at all. A tenth of a point between two hosts is not a finding.
* **Check `failed` before treating a matrix as complete.** An engine that dies part-way
  is recorded there and given no score, because a WER over the utterances it survived
  is a number for an engine that does not work.

## What is here

| File | Experiment | Script |
|---|---|---|
| `wer*.json` | WER + RTF per engine and checkpoint — `wer.json` is `test-clean`, `wer-test-other.json` the hard split | `bench_wer.py` |
| `beam-*.json` | `[stt] beam_size` sweep, clean and hard splits | `bench_beam.py` |
| `onset.json` | the silence lead-in, onset intact and onset clipped | `bench_onset.py` |
| `latency.json` | decode P50/P95, cold start, RSS, per-stage timings | `bench_latency.py` |
| `streaming.json` | LocalAgreement streaming vs batch | `bench_streaming.py` |
| `vad.json` | speech-detection / silence-rejection at the default gate | `bench_vad.py` |
| `commands.json` | command-grammar accuracy and false-positive rate | `bench_commands.py` |
| `plausibility-*.json` | how often the attribution warning fires, and is right | `bench_plausibility.py` |
| `diarization-*-der.json` | speaker-diarization DER per recording and over the corpus, at the profile's shipped `cluster_threshold` | `bench_diarization.py` |
| `meta.json` | dysfluency gate, model footprint, engineering scale | `bench_meta.py` |
| `index.json` | the provenance + summary of one `run_all.py` sweep | `run_all.py` |
| `platform-resolution.json` | which extras resolve on which OS/arch, and what blocks the rest | `bench_platform_resolution.py` |

### Two DERs, and why both are reported

`diarization-*-der.json` carries `der_strict` (the unweighted mean across recordings)
and `der_strict_time_weighted` (total error time over total scored speech time). The
mean is the headline because it answers "how well does Meeting Mode do on a meeting",
and a forty-minute meeting should not drown out three short ones. The time-weighted
figure is what NIST `md-eval` computes and what every published AMI and DIHARD table
quotes, so **it is the one to compare against the literature** — reading the mean as
though it were a corpus DER compares two different quantities. On the AMI test split
they are 26.71 % and 27.37 %; on a corpus whose recordings differ in length by 3x they
do not have to agree, and neither is a correction of the other.

Both are derivable from the `meetings` rows, which carry `scored_seconds` — md-eval's
denominator — so the second figure could be added to an artifact measured before the
function existed. Where that happened the file says so in `derived_after_the_run`, and
the measured rows are untouched.

## Measurements and analyses are different files

A file whose name ends `-significance` is an **analysis**: it reads a measurement
already in this directory and reports what survives a statistical test. It carries
`comparisons`, never `rows`, and it produces no new numbers of its own.

| File | Reads | Reports | Script |
|---|---|---|---|
| `onset-significance.json` | `onset.json` | exact McNemar per lead-in cell, Bonferroni-corrected across conditions | `analyze_onset.py` |
| `beam-*-significance.json` | `beam-*.json` | each beam vs beam 1, paired | `analyze_beam.py` |
| `beam-*-significance-vs-beam2.json` | `beam-*.json` | each beam vs beam **2**, the operating point | `analyze_beam.py --baseline=2` |

Keeping them apart matters more than it looks. Both halves match `beam-*.json`, so a
glob written for the measurement swallows the analysis and fails on a missing `rows`
key — which is how this was found. `tests/test_benchmarks_match_results.py` now asserts
an analysis carries `comparisons` and no `rows`, so the two can never be confused
silently again.

Read an analysis **before** quoting a difference from the measurement it reads. Two of
the four conclusions the beam table originally carried did not survive the paired test,
and every lead-in comparison on the onset page fell to the multiplicity correction.

Two scripts have no result here, and that is recorded rather than left as an absence:
`bench_diarization.py` scores corpora that may not be committed (licence, size), and
`bench_throughput.py` needs a human at the keyboard. The reasons live in
`tests/test_benchmark_results_are_archived.py::NO_ARCHIVED_RESULT`, where a stale one
fails the build.

## The probes, and the two-day Azure window

[`probes/`](probes/README.md) holds the exploratory measurements — the ones made on
rented compute while a question was still being framed, before it was worth a harness
script. Sweeps that found their optimum outside their own range, the embedding-model
comparison, the first DER on real human speech, and every run log those produced. Each
carries the machine it ran on and, where a committed script has since replaced it, the
name of that script.

They are archived rather than summarised because a published figure with no artifact is
a claim, and because the intermediate runs are the part a later reader cannot
reconstruct: the ranges that were wrong, and how the wrong one was found.

## Regenerating

```bash
uv sync --group benchmark
uv run python paper/benchmark/run_all.py --wer-n 200 --lat-n 30 --vad-n 200
uv run python paper/benchmark/bench_beam.py 200 test-clean
uv run python paper/benchmark/bench_onset.py 200 2
```

`.github/workflows/benchmark.yml` runs the harness across Linux x86_64/arm64, macOS
arm64/x86_64 and Windows and uploads each result as an artifact. It never commits back:
a published number only moves when a person moves it.

## Privacy

These files are published. They contain no audio, no transcripts, no hostname and no
login name; the provenance block is deliberately machine-descriptive. The guard test
fails the build if a home directory or a user name appears in one, because git history
does not forget.
