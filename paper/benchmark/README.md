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
| `bench_latency.py` | decode P50/P95, cold-start, RSS, pure-stage timings | STT engine, `audio.vad_calibrated`, `postprocess.cleaner`, `stt.filters.disfluency`, `commands.grammar` |
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
