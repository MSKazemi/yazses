# Probe scripts — archived, not maintained

Short scripts written directly on the measurement hosts during the Azure window, each
answering one question. They are committed so that the artifacts in
[`../../results/probes/`](../../results/probes/README.md) trace back to code rather than
to a description of code.

**Read them; do not run them.** They hardcode absolute paths on hosts that no longer
exist, take no arguments, and several were edited between runs — the numbered variants
(`leadin_probe.py` / `leadin_probe2.py`, `determinism_probe.py` … `4.py`) are those
edits, kept separate rather than squashed, because which version produced which artifact
is exactly the thing a squashed history destroys.

Where a question proved worth asking again, the probe became a real harness script and
the artifact says so:

| Probe | Became |
|---|---|
| `beam_probe.py`, `beam_probe_other.py` | `../bench_beam.py` |
| `leadin_probe.py`, `leadin_probe2.py` | `../bench_onset.py` |
| `guard_probe.py`, `guard_corpus.py` | `../bench_plausibility.py` |
| `determinism_probe*.py` | folded into `../bench_wer.py` and the run-to-run note in `docs/benchmarks.md` |
| `embmodel_test*.py` | — one-off; the verdict is in `design/adr/adr-v2-133-diarization-clustering-default.md` |
