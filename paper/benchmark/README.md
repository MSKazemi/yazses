# YazSes benchmark harness

Reproducible measurements behind the paper's Evaluation section. Every script reuses
the **shipping** YazSes code (not a bespoke reimplementation), writes JSON to
`../results/` with a provenance block, and prints a one-line summary.

## Install

```bash
uv sync --group benchmark      # jiwer, psutil, matplotlib, soundfile, whisper-normalizer
```

## Data (one-time)

WER and VAD use LibriSpeech `test-clean` (Panayotov et al., ICASSP 2015):

```bash
cd paper/data
curl -fsSL -O https://www.openslr.org/resources/12/test-clean.tar.gz
tar -xzf test-clean.tar.gz            # -> paper/data/LibriSpeech/test-clean/
```

## Run

```bash
# everything (WER on N utts, latency on N utts, VAD on N clips, commands, meta)
uv run python paper/benchmark/run_all.py --wer-n 200 --lat-n 30 --vad-n 200

# add full-suite coverage (slow: runs the whole pytest suite under coverage)
uv run python paper/benchmark/run_all.py --coverage --skip wer latency vad commands meta

# or a single experiment
uv run python paper/benchmark/bench_wer.py 200
uv run python paper/benchmark/bench_commands.py

# WER across every engine, not just the three Whisper checkpoints. `full` adds
# medium.en, large-v3, Parakeet TDT 0.6B and Moonshine tiny/base -- the models
# docs/models.md compares against each other on the vendors' word alone.
# Needs their extras installed; the bench REFUSES to run rather than let the
# factory fall back to faster-whisper and publish Whisper's numbers under
# another engine's name.
uv sync --extra parakeet --extra moonshine
uv run python paper/benchmark/bench_wer.py 200 full

# or an explicit selection, as `engine:model` pairs
uv run python paper/benchmark/bench_wer.py 200 parakeet:nemo-parakeet-tdt-0.6b-v2

# turn results/*.json into figures/*.pdf and LaTeX tables
uv run python paper/benchmark/make_figures.py
```

## What each script measures

| Script | Metric | Reuses |
|---|---|---|
| `bench_wer.py` | WER (%) + RTF across engines and checkpoints | `stt.factory.build_engine` (so faster-whisper, Parakeet and Moonshine all decode through the shipping path), whisper-normalizer, jiwer |
| `bench_latency.py` | decode P50/P95, cold-start, RSS, pure-stage timings, CPU core-seconds (and energy where readable) for load and decode separately | STT engine, `audio.vad_calibrated`, `postprocess.cleaner`, `stt.filters.disfluency`, `commands.grammar` |
| `bench_commands.py` | grammar action-accuracy, false-positive rate, per-call ms | `commands.grammar.classify` + existing fixtures |
| `bench_vad.py` | speech-detection / silence-rejection at the default threshold | `audio.vad_calibrated.is_silent_calibrated` |
| `bench_diarization.py` | diarization DER / miss / false-alarm / confusion + speaker-count error | `recimport.diarizer.SherpaDiarizer`, a corpus from `scripts/gen-meeting-corpus.py` |
| `bench_beam.py` | WER + RTF across `beam_size`, with per-utterance error counts | `stt.factory.build_engine`, `bench_wer._bootstrap_wer_ci`, jiwer |
| `bench_onset.py` | first-word accuracy against the silence lead-in, with per-utterance outcomes | `stt.factory.build_engine`, whisper-normalizer, jiwer |
| `bench_streaming.py` | partial-hypothesis latency and rewrite rate | `stt.streaming.StreamingEngine` |
| `bench_platform_resolution.py` | whether each extra can be installed at all, per platform, and why not | `uv pip compile`, PyPI file lists |
| `bench_plausibility.py` | how often the implausible-attribution warning fires, and on what | `recimport.diarizer`, `meeting` plausibility policy |
| `bench_throughput.py` | dictation words/minute against typing the same prompts | needs a human at the keyboard; no archived result |
| `analyze_beam.py` | paired bootstrap of the WER difference between two beam widths | reads `../results/beam-*.json` |
| `analyze_onset.py` | exact McNemar between two cells of the onset grid | reads `../results/onset.json` |
| `analyze_diarization.py` | exact sign test + paired bootstrap over the *recordings*, for two diarization runs of one corpus | reads two `../results/diarization-*.json` |
| `analyze_centroid.py` | pooled cosine separation between cluster-centroid pairs that share a true speaker and pairs that do not, with a bootstrap interval and a merge-threshold sweep | reads the shards written by `probes/centroid_merge.py` |
| `bench_meta.py` | dysfluency gate, model on-disk size, test/ADR/SLOC counts | `stt.filters.disfluency`, HF cache scan |
| `bench_persian.py` | Persian WER/CER raw **and** evaluation-normalized, exact-match rate, ZWNJ + Arabic-variant quality metrics, RTF/latency (FA-04, [#513](https://github.com/MSKazemi/yazses/issues/513)) | `stt.factory.build_engine` (manifest mode), `persian_metrics.py`, jiwer; `--smoke` needs no audio or model |
| `convert_hf_to_ct2.py` | converts a Hugging Face Whisper fine-tune checkpoint into a CT2 directory with an auditable `conversion.json` sidecar for non-CT2 candidates (FA-05, [#514](https://github.com/MSKazemi/yazses/issues/514)) | stdlib only at import; delegates conversion to an external interpreter with torch + transformers + ctranslate2 |
| `make_fa_manifest.py` | builds the `id/audio/reference` JSONL manifest `bench_persian.py --manifest` scores, from pinned FLEURS `fa_ir` / Common Voice `fa` releases — §8 seeded sampling, sidecar pins, no audio in git (FA-04 slice 2, [#513](https://github.com/MSKazemi/yazses/issues/513)) | stdlib only: `csv`/`tarfile`/`hashlib`; pins in `PINS`, audio stays local via `--audio-root` |
| `persian_metrics.py` | library: `fa-eval-v1` evaluation normalizer + §5 Persian text-quality metrics (imported by `bench_persian.py`, not run directly) | deliberately **not** `postprocess.persian_text` — §6 versions evaluation and production normalization separately |
| `persian_manifest.py` | library: the gate in front of `bench_persian.py --manifest` — every row needs a licence and a consent value (own or from the `.meta.json` sidecar), speaker/session may only be opaque pseudonyms, and audio may only be read from the manifest's directory or an explicit `--audio-root`; otherwise the run is refused before a model is built (FA-04, [#513](https://github.com/MSKazemi/yazses/issues/513)) | stdlib only; it checks that the claims are made, it cannot verify them |
| `persian_stats.py` | 95 % bootstrap confidence intervals over utterances, a *paired* bootstrap for two cells on the same rows, and the WER points attributable to a missing ZWNJ — reads the JSONL `bench_persian.py --hyps-out` writes (FA-05, [#514](https://github.com/MSKazemi/yazses/issues/514)) | an interval describes sampling noise on this corpus and machine only, not another host or decoder setting; pure Python, no benchmark deps |
| `codeswitch_metrics.py` | text-only fa-en code-switch scorer, protocol `fa-en-cs-v1`: MER (raw and `fa-eval-v1`), language-boundary error rate with precision/recall, English-token preservation (exact, case-folded, transliterated), Persian CER over the Persian-script tokens, token-language accuracy; the seeded held-out split; `--split heldout` prints the aggregate-only submission block, never text or ids (FA-09, [#518](https://github.com/MSKazemi/yazses/issues/518); protocol in `design/specs/persian-code-switch-evaluation.md`) | `persian_metrics.normalize_fa_eval_v1`; stdlib only, no audio or model |
| `cost_meter.py` | library: per-decode CPU core-seconds (`os.times()`, threads and exited children included), wall time and RTF, plus optional Linux RAPL / battery energy for a phase behind an `EnergyProbe` Protocol, a parser for a manually captured macOS `powermetrics` log, and the versioned record schema (`yazses.bench.cost/2`) with its validator; imported by `bench_latency.py` and `cost_smoke.py`, not run directly (PAPER2-ENERGY-001, [#506](https://github.com/MSKazemi/yazses/issues/506)) | stdlib only; see "CPU core-seconds and energy" below |
| `cost_smoke.py` | one-clip check of the cost instrument: model load + N decodes of the bundled `data/librispeech-sample/jfk.wav` (or a `--synthetic` clip), written to an explicit `--out` path, never to `../results/` (#506) | `cost_meter.py`, `stt.faster_whisper` from the local cache only (`HF_HUB_OFFLINE=1`); falls back to a labelled fake decoder when the model is not cached |
| `run_all.py` | orchestrates all of the above + provenance + optional coverage | — |
| `make_features_table.py` | capability-surface table + prose macros for the paper, from the live registry | `system.features` (the registry behind `yazses features`) |
| `make_results_index.py` | `../results/MANIFEST.md` — what every archived artifact is and which machine it came from | reads `../results/**/*.json` |
| `make_figures.py` | `results/*.json` -> `figures/{numbers,tab_main,tab_pipeline}.tex`, `wer.pdf`, `latency.pdf` | — |

## Other machines and other architectures

The `Benchmarks` workflow (`.github/workflows/benchmark.yml`) runs this harness on
Linux x86_64, Linux arm64, macOS arm64, macOS x86_64 and Windows, and uploads each
`results/*.json` as an artifact. It is `workflow_dispatch` only -- a full matrix run
takes hours -- and it never commits results back, so a published number can only
move when a person moves it.

```bash
gh workflow run benchmark.yml -f wer_n=100 -f lat_n=20
```

Read the artifacts with the provenance block, never without it. **Latency and RTF are
properties of the machine** and must be reported per host; merging latency from two
runners into one table is a defect, not a summary.

**WER is very nearly a property of the model, and the gap matters.** CTranslate2 owns
the int8 kernels and the order their partial sums are reduced in, and that order
depends on the ISA it dispatched to *and* on how many threads the GEMM was split
across. On one laptop, one byte-identical 200-utterance subset and one set of library
versions, `tiny.en` scored **4.78%** with the thread count left to CTranslate2,
**4.88%** at one thread and **4.95%** at four -- while `base.en` and `small.en` did not
move at all, which is exactly why this is easy to miss. The spread sits well inside
the bootstrap interval the bench already reports (tiny.en: 4.03-5.83), so it does not
threaten the *ranking* of models; it does mean a tenth of a point between two hosts is
not a finding. Pin the thread count on both before reading anything into a small gap:

```bash
uv run python paper/benchmark/bench_wer.py 200 default --threads 4
```

`--threads 0` (the default) is the shipping behaviour and therefore the right thing to
publish; the value is written into every result's `config.cpu_threads` so a reader can
tell "CTranslate2 chose" from "nobody recorded it".

**A broken engine does not take the others down with it.** `bench_wer` writes its JSON
after the last spec, so a matrix that had scored five checkpoints over ninety minutes
once produced *nothing* because the sixth engine raised on its first utterance. An engine
that fails to load, or dies part-way through the subset, is now recorded in
`results["failed"]` and the run continues. **Check that key before treating a table as
complete** — and note that a partly-decoded engine is deliberately given no WER at all,
because a score over the utterances it survived is a number for an engine that does not
work.

## CPU core-seconds and energy

`bench_latency.py` records, per model, a `load_cost` and a `decode_cost` block next to its
latency fields (method and arithmetic in `cost_meter.py`). Nothing runs unless the benchmark
is invoked; the daemon never imports it. This is the *instrument*: no result from it is
archived or quoted yet, and a number taken on one laptop is a measurement of that laptop.

To exercise it without LibriSpeech, `cost_smoke.py` loads one model from the local cache
and decodes one clip a few times:

```bash
uv run --group benchmark python paper/benchmark/cost_smoke.py --out /tmp/cost.json --repeats 5
uv run --group benchmark python paper/benchmark/cost_smoke.py --out /tmp/cost.json --fake-decoder --synthetic 3
```

It never downloads. When the model is not cached it substitutes a fake decoder (numpy work
proportional to the audio) and records `decoder.kind = "fake"` with the reason -- such a run
checks the meter, not a model.

### Record schema (`yazses.bench.cost/2`)

Every block carries `schema_version` and is checked by `cost_meter.validate_record` before
it is written (`check_record` raises), so a record that contradicts its own contract fails
at measurement time. Version 1 (unversioned) lacked the per-decode list, RTF, child-process
time and the `source` / `available` / `uncertainty` fields.

| Field | Meaning |
|---|---|
| `schema_version`, `method` | the schema, and how CPU time was read |
| `cpu_user_s`, `cpu_system_s`, `cpu_children_user_s`, `cpu_children_system_s` | the parts; `cpu_core_seconds` is their sum (validated) |
| `span_wall_s`, `bracket_wall_s` | wall time inside the decode spans, and over the whole begin-to-end bracket |
| `audio_s`, `n_spans` | audio decoded, number of decodes |
| `rtf`, `cpu_core_seconds_per_audio_s`, `mean_cores_busy` | span wall / audio, core-seconds / audio, core-seconds / span wall; `null` -- never `0` -- for a phase with no audio (model load) |
| `spans[]` | one entry per decode: `index`, `audio_s`, `wall_s`, `cpu_core_seconds`, `rtf`, `cpu_core_seconds_per_audio_s` |
| `span_summary` | `n`, `mean`, sample `stdev` (`null` below two decodes), `min`, `median`, `max` of per-decode core-seconds, wall and RTF -- the variation, not just the mean |
| `energy.<probe>` | one reading per source, below |

An energy reading always has `source` (what was read), `method`, `available`,
`energy_joules`, `reason`, `uncertainty` and the normalised `joules_per_audio_s` /
`joules_per_utterance`. The validator enforces the no-fabrication rule: an unavailable
reading must have `energy_joules` and both rates `null` and a non-empty `reason`; an
available one must have `energy_joules > 0` and `reason: null`. `uncertainty` is
`{quantisation_joules, notes[]}`: `quantisation_joules` is the counter's resolution (two
integer reads), a *lower* bound on the error, or `null` when not even that is known; the
notes name the terms that cannot be bounded from the reading (attribution, gauge step,
sampling).

### Core-seconds

`os.times()` user + system CPU time of the benchmark process, plus its `children_*`
fields, summed over the spans that wrap `engine.transcribe` (so reading the FLAC is not
billed to the decoder). Limits:

- Threads **are** included (CTranslate2 and ONNX Runtime pools live in this process); a
  test burns CPU in a worker thread and checks the span sees it.
- Child processes count only **once they have exited and been waited for**; a child still
  running at the end of a span is missed, and on Windows the `children_*` fields are always
  0. None of the benchmarked engines spawns one.
- Resolution is the OS clock tick (1/100 s on a typical Linux kernel), so per-decode
  core-seconds of a very short decode are quantised; use the phase totals for small clips.
- It is CPU *time*, not work: no normalisation for clock frequency, turbo or SMT, so
  core-seconds from two hosts cannot be compared without calibration.

### Energy

When a counter cannot be read, `energy_joules` is `null` and `reason` says why -- it is
never `0`, which would read as "free".

| Probe | Source | What it is | What it is not |
|---|---|---|---|
| `rapl` | Linux `/sys/class/powercap/intel-rapl:N/energy_uj` (package domains only; AMD parts expose the same names) | CPU package energy from a hardware counter; wraparound at `max_energy_range_uj` is corrected once; quantisation 2 uJ per package | Not wall power (no display, SSD, fans, PSU loss); not per-process, so it also counts everything else on the package -- measure an idle baseline; often readable by root only, in which case the record is `null` with a permission reason and the harness does not escalate. A run long enough to wrap twice cannot be detected (`counter_trace_delta` handles any number of wraps for a densely sampled trace) |
| `battery` | Linux `/sys/class/power_supply/*` with `type` Battery, excluding `scope` Device (a mouse or headset) | Whole-system discharge between two readings from `energy_now`, or `charge_now` x mean `voltage_now` for a charge-only gauge (flagged as an approximation), valid only while the status is `Discharging` at both ends | **Coarse**: the fuel gauge moves in steps much larger than one short decode, so short phases usually record `null` ("did not drop"); the sysfs unit is not the gauge's real step |
| `energy` (macOS) | `powermetrics`, manual | `unavailable` in the record: `powermetrics` needs root and the harness never escalates | See the manual path below |
| `energy` (Windows) | none | `unavailable` | No reader is implemented, because none could be tested here |

**macOS manual path.** In a second terminal, start
`sudo powermetrics --samplers cpu_power -i 100 -o pm.log` just before the phase and stop it
(Ctrl-C) just after, then integrate the log with
`cost_meter.powermetrics_energy(Path("pm.log").read_text(encoding="utf-8"))`. It sums
`CPU Power` (Apple silicon) or the Intel package-power line over each sample's elapsed time.
This is a model-estimated CPU power, not a counter and not wall power, the sample boundaries
do not line up with the phase, and the parser has been checked against **synthetic logs
only** -- no Mac was available to check a real one.

Energy probes cannot be paused, so they cover the whole bracket around the decode loop
(including FLAC reads), and `joules_per_audio_s` divides that bracket energy;
`bracket_wall_s` is recorded beside `span_wall_s` so the gap is visible. Single-host
numbers are not generalisable, and absolute energy must not be compared across machines.
Repeats (to report variation), the `tiny`/`base`/`small`/Parakeet/Moonshine comparison and
the batch-versus-streaming comparison from #506 are runs of this instrument, not part of it,
and have not been done.

## Notes

- Subset selection is deterministic: a speaker-stratified round-robin over the sorted
  utterance ids, so the same `N` always scores the same clips. Decoding is *nearly*
  deterministic -- see the thread-count note above; identical inputs and library
  versions can still differ in the last decimal when the thread count differs.
- Run nothing else CPU-heavy during a run: latency/RTF are wall-clock measurements.
- The numbers reported in the paper were taken on the machine named in each result
  file's `provenance` block; re-run on your own hardware to re-scope.


## Diarization (Meeting Mode)

`bench_diarization.py` is **not** in `run_all.py` and never will be: it needs a corpus
that is not in the repository, and a bench that silently skips is worse than one that
is absent. It scores any directory holding `<id>.wav`, `<id>.rttm` and a
`manifest.json` that declares where its reference came from — a corpus that does not
declare its own provenance is refused, because the strings it would otherwise inherit
describe some other corpus.

Three corpora, answering three different questions. **Their numbers are not
comparable with each other and must never be averaged.**

### 1. Synthetic — the regression fixture

```bash
export AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=westeurope
export AZURE_OPENAI_ENDPOINT=https://<name>.openai.azure.com/
export AZURE_OPENAI_KEY=... AZURE_OPENAI_DEPLOYMENT=gpt-4o
uv run python scripts/gen-meeting-corpus.py --out /tmp/meeting-corpus --meetings 8 --turns 20

uv sync --extra diarization
uv run yazses transcribe --download-models
uv run python paper/benchmark/bench_diarization.py /tmp/meeting-corpus out.json
```

The ground truth is exact rather than annotated — the mixer placed every turn — so the
primary figure is DER at **collar 0**; the NIST 250 ms collar is reported beside it
only so the number can be set next to published ones.

**Synthetic, so the DER is a floor, not a real-room figure.** Neural TTS voices are
cleaner and more separable than people in a room, so a real meeting scores worse. Its
value is as a regression fixture: it answers "did this change make separation worse",
never "this is the DER".

### 2. AMI — the target-domain number

Real four-person meetings in real rooms: what Meeting Mode is actually pointed at, and
therefore the only one of the three that can justify changing a shipped default.

```bash
mkdir -p /tmp/ami/wav /tmp/ami/rttm
for m in EN2002a ES2004a IS1009a TS3003a; do          # official test split
  curl -fsSL -o "/tmp/ami/wav/$m.wav" \
    "https://groups.inf.ed.ac.uk/ami/AMICorpusMirror/amicorpus/$m/audio/$m.Mix-Headset.wav"
  curl -fsSL -o "/tmp/ami/rttm/$m.rttm" \
    "https://raw.githubusercontent.com/pyannote/AMI-diarization-setup/main/only_words/rttms/test/$m.rttm"
done
uv run python paper/benchmark/make_corpus.py ami /tmp/ami/wav /tmp/ami/rttm /tmp/ami-corpus 90
uv run python paper/benchmark/bench_diarization.py /tmp/ami-corpus ami.json
```

The headset mix is cleaner than a single table microphone, so a far-field recording
scores worse than this.

### 3. VoxConverse — the generalisation check

Broadcast and YouTube audio: harder acoustically than a meeting and easier in turn
structure, so it checks that a change does not help one domain by hurting another.

```bash
mkdir -p /tmp/vox && cd /tmp/vox
curl -fsSL -O https://mm.kaist.ac.kr/datasets/voxconverse/data/voxconverse_dev_wav.zip
curl -fsSL -o vox.zip https://codeload.github.com/joonson/voxconverse/zip/refs/heads/master
unzip -q voxconverse_dev_wav.zip -d wav_root && unzip -q vox.zip -d repo_root
cd - && uv run python paper/benchmark/make_corpus.py voxconverse \
    /tmp/vox/wav_root /tmp/vox/repo_root/voxconverse-master/dev /tmp/vox-corpus 90
uv run python paper/benchmark/bench_diarization.py /tmp/vox-corpus vox.json
```

### Sweeping the clustering threshold

`--sweep` re-scores the corpus across `[recimport] cluster_threshold` values. On the
synthetic corpus the shipped `0.5` is dominated on every metric, with an interior
minimum near `0.8` — but a threshold tuned on TTS voices is precisely the parameter
those voices over-fit, which is why the real corpora exist.

```bash
uv run python paper/benchmark/bench_diarization.py /tmp/ami-corpus ami-sweep.json --sweep
uv run python paper/benchmark/bench_diarization.py /tmp/ami-corpus s.json --sweep \
  --thresholds 0.9,1.0,1.1,1.2,1.3,1.4,1.6
```

The default range now runs `0.4` to `1.4`. It used to stop at `0.9`, which is below
the real-audio optimum of `1.2`, so every AMI sweep ran to the edge of its range still
improving — and a sweep whose optimum lies outside its range does not report "range too
narrow", it reports a metric improving monotonically to the last column, which reads
exactly like "no threshold helps". Widen it again before concluding anything about a
corpus longer or noisier than AMI: the useful cut height grows with the recording.

### Telling it the speaker count

`--max-speakers N` sets `[recimport] max_speakers`, which on the shipped sherpa backend
is an **exact** cluster count rather than an upper bound, so `4` means four clusters
whatever the audio contains. It measures the mitigation available to a user who knows
how many people were in the room:

```bash
uv run python paper/benchmark/bench_diarization.py /tmp/ami-corpus n.json --max-speakers 4
```

### Subset selection

`make_corpus.py` takes an equal **number** of recordings from every bucket — speaker
count for VoxConverse, session for AMI — because `run()` averages DER across meetings
without weighting by duration, so a bucket's influence is its file count. Selection is
deterministic and never ordered by duration, and the chosen ids are written into the
manifest so a published number names the exact recordings behind it.
