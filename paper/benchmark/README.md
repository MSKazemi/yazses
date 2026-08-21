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

# turn results/*.json into figures/*.pdf and LaTeX tables
uv run python paper/benchmark/make_figures.py
```

## What each script measures

| Script | Metric | Reuses |
|---|---|---|
| `bench_wer.py` | WER (%) + RTF across `tiny/base/small.en` | `stt.faster_whisper.FasterWhisperEngine`, whisper-normalizer, jiwer |
| `bench_latency.py` | decode P50/P95, cold-start, RSS, pure-stage timings | STT engine, `audio.vad_calibrated`, `postprocess.cleaner`, `stt.filters.disfluency`, `commands.grammar` |
| `bench_commands.py` | grammar action-accuracy, false-positive rate, per-call ms | `commands.grammar.classify` + existing fixtures |
| `bench_vad.py` | speech-detection / silence-rejection at the default threshold | `audio.vad_calibrated.is_silent_calibrated` |
| `bench_meta.py` | dysfluency gate, model on-disk size, test/ADR/SLOC counts | `stt.filters.disfluency`, HF cache scan |
| `run_all.py` | orchestrates all of the above + provenance + optional coverage | — |
| `make_figures.py` | `results/*.json` -> `figures/{numbers,tab_main,tab_pipeline}.tex`, `wer.pdf`, `latency.pdf` | — |

## Notes

- Results are deterministic given the same models and data (LibriSpeech subset is
  chosen by sorting utterance ids and taking the first N).
- Run nothing else CPU-heavy during a run: latency/RTF are wall-clock measurements.
- The numbers reported in the paper were taken on the machine named in each result
  file's `provenance` block; re-run on your own hardware to re-scope.
