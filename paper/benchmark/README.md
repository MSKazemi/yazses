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
| `bench_meta.py` | dysfluency gate, model on-disk size, test/ADR/SLOC counts | `stt.filters.disfluency`, HF cache scan |
| `run_all.py` | orchestrates all of the above + provenance + optional coverage | — |
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

Read the artifacts with the provenance block, never without it: **word error rate is
a property of the model** and is comparable across hosts, while **latency and RTF are
properties of the machine** and must be reported per host. Merging latency from two
runners into one table is a defect, not a summary.

## Notes

- Results are deterministic given the same models and data (LibriSpeech subset is
  chosen by sorting utterance ids and taking the first N).
- Run nothing else CPU-heavy during a run: latency/RTF are wall-clock measurements.
- The numbers reported in the paper were taken on the machine named in each result
  file's `provenance` block; re-run on your own hardware to re-scope.


## Diarization (Meeting Mode)

`bench_diarization.py` is **not** in `run_all.py` and never will be: it needs a
corpus that is not in the repository, and a bench that silently skips is worse than
one that is absent. Build the corpus first, then score against it:

```bash
export AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=westeurope
export AZURE_OPENAI_ENDPOINT=https://<name>.openai.azure.com/
export AZURE_OPENAI_KEY=... AZURE_OPENAI_DEPLOYMENT=gpt-4o
uv run python scripts/gen-meeting-corpus.py --out /tmp/meeting-corpus --meetings 8 --turns 20

uv sync --extra diarization
uv run yazses transcribe --download-models
uv run python paper/benchmark/bench_diarization.py /tmp/meeting-corpus out.json
```

The ground truth is exact rather than annotated — the mixer placed every turn — so
the primary figure is DER at **collar 0**; the NIST 250 ms collar is reported beside
it only so the number can be set next to published ones.

**The corpus is synthetic and the DER is therefore a floor, not a real-room figure.**
Neural TTS voices are cleaner and more separable than people in a room, so a real
meeting will score worse. Its value is as a regression fixture: it answers "did this
change make separation worse", never "this is the DER". Do not quote it as the
latter, and do not merge it with a figure measured on AMI or VoxConverse.
