# Probes — the exploratory measurements

Every file here was produced during a two-day measurement window on rented Azure
compute (two 16-vCPU Xeon boxes in `westeurope`), answering one question at a time.
They are the working record behind the diarization, WER, beam-size, plausibility-guard
and silence-lead-in numbers published in [`docs/benchmarks.md`](../../../docs/benchmarks.md).

**These are probes, not the harness.** Where a question turned out to be worth asking
repeatedly, the probe was rewritten as a committed script in
[`../../benchmark/`](../../benchmark/README.md) and the artifact here carries a
`superseded_by` field naming it. Reproduce from the harness; read the probe for the
history, the intermediate ranges, and the runs that went nowhere.

Every file here also appears in [`../MANIFEST.md`](../MANIFEST.md), the generated
index over the whole archive, with the script that produced it and the machine it ran
on in a single table.

## The envelope

Each `*.json` is a wrapper, not the raw file:

```json
{
  "provenance": { "cpu_model": "...", "os": "...", "python": "...", "yazses": "..." },
  "probe": {
    "measured": "what question this answered",
    "produced_by": "probes/guard_corpus.py",
    "host": "Azure Standard_D16s_v6, westeurope",
    "run_finished_utc": "2026-08-23T21:31:25Z",
    "superseded_by": "paper/benchmark/bench_plausibility.py"
  },
  "result": { "...the file exactly as the probe wrote it..." }
}
```

Two things about `provenance` are deliberate and should be read before the numbers:

* Where the probe stamped its own block at run time, **that** block is what you see.
  Where it did not, the block was captured afterwards **on the same host**, which was
  not reconfigured in between, and it says so in a `captured` field. An after-the-fact
  provenance is weaker evidence than a contemporaneous one and is marked as such rather
  than quietly presented as equal.
* `run_finished_utc` is the modification time **on the measurement host**. Copying the
  files off the box would otherwise have restamped every one of them with the time of
  the copy — a plausible, uniform, and entirely false timestamp.

## The logs

[`logs/`](logs/) holds what each run printed, prefixed with the host it ran on. This is
where the per-recording and per-utterance lines live: the sweep that walked a range,
the meeting that took eleven minutes, the engine that crashed on utterance 3. Model and
corpus downloads and full `pytest` transcripts are excluded — large, and no measurement
in them: the largest single omission is a 1.3 MB `pytest` transcript from the
all-extras run, whose *result* (which tests ran, which passed) is recorded here and in
the plan rather than as ten thousand progress dots. `*-bootstrap.log` **is** kept
despite being an install log, because it is the record of what the two machines were
actually built from and every timing on this page is a property of that build.

**Two of these logs are an A/B proof that a dependency pin is load-bearing.**
`x86b-extras_bare_names.log` and `x86b-extras_via_extra.log` are the same two tests,
on the same box, twenty minutes apart. The first installed `resemblyzer` by bare name
and `test_real_resemblyzer_returns_a_unit_vector_at_both_lengths` died on
`ModuleNotFoundError: No module named 'pkg_resources'`; the second installed
`.[voiceprint-resemblyzer]`, whose `setuptools<81` pin exists for precisely that, and
both tests passed. The passing run still carries upstream's own warning verbatim --
"pin to Setuptools<81" -- which is where the pin came from. Both tests are gated on an
optional extra no CI job installs, so neither had ever executed anywhere before this
run; the pyannote one binds the adapter's call against the real
`Pipeline.from_pretrained` signature and is what would catch a repeat of the 3.x
`use_auth_token` → 4.x `token` rename.

**Two other logs are the only surviving record of a measurement.** The `test-other`
engine matrix was run twice on the same instance; the second run overwrote
`../wer-test-other.json`, and it disagreed with the first by 2.83 points on `large-v3`.
Run 1 therefore exists only as `logs/x86b-other_wer.log` and run 2, which is also the
committed JSON, as `logs/x86b-serial_chain.log`. `_common.write_result` now copies a
displaced result into `../history/` precisely so that this cannot happen again; the
mechanism postdates the loss, which is why the evidence for a published table is a
console log here rather than an artifact there.

Paths and login names are redacted (`$HOME`, `user`), because these files were written
on a machine where the home directory was in every path and git history does not
forget. `tests/test_benchmark_results_are_archived.py` fails the build if one gets
through, and it checks the logs, not only the JSON.

## The probe scripts

[`../../benchmark/probes/`](../../benchmark/probes/) holds the scripts themselves. They
are committed for the same reason the results are: a number whose code is gone is not
reproducible. Most are *not* maintained, take no arguments beyond what is hardcoded in
them, and expect corpora at absolute paths on a machine that no longer exists — read
those; do not run them. `largev3_repeat.py` is the exception and is meant to be run
(`python paper/benchmark/probes/largev3_repeat.py 4 test-other 200`): it needs only
LibriSpeech, which downloads itself.

`decode_determinism.py` is the other, and it is the follow-up: `largev3_repeat.py`
established that only the insertions move, and this tests *why* and *whether it can be
turned off*, by running the same 200 utterances through three decode settings -- what
ships, `temperature=0.0`, and `temperature=0.0` with `condition_on_previous_text=False`
-- five times each. It records a SHA-256 of each run's concatenated hypotheses, because
two runs that trade one insertion for another score the same WER and are not the same
text, and the ids of the utterances that differ, because a spread says the model is
noisy while a list of ids says where. Run it as
`python paper/benchmark/probes/decode_determinism.py 5 test-other 200 large-v3`.

Its first result is `largev3-instability-test-other.json`, and it is the one number on
this page worth re-deriving yourself, because it is a claim about *variance*. Across
five decodes of the same 200 utterances the substitutions (87), deletions (15) and hits
(3619) are bit-identical and only the insertions move (101 → 184), so every WER is
exactly `(102 + insertions) / 3721`. Four repeats are enough to refute a trend — the
first three fell monotonically and the fourth did not — and nowhere near enough to
put an interval on the spread. That is what a re-run adds.

Note the artifact's `summary` was recomputed after the run by the committed
`summarise()`, because the measurement host was carrying the version of the probe from
before deletion tracking was added; `runs` is untouched and the envelope's
`summary_rederived` field says so. `summarise` is pure over `runs`, so this changes
nothing that was measured.

[`../../benchmark/probes/drivers/`](../../benchmark/probes/drivers/README.md) holds the
shell that ran all of it — corpus fetch and preparation, machine provisioning, the
sweep queues, and `x86-validate_scorer.sh`, which is the only record that this repo's
DER agrees with NIST `md-eval-22.pl` and `pyannote.metrics` on the same hypothesis
RTTMs. Those scripts name the exact AMI split, channel and reference annotation used,
which is the single largest source of disagreement between published AMI numbers.

## What is not here

The corpora. AMI and VoxConverse carry licences that do not permit redistribution, and
the synthetic Azure-TTS meeting corpus is 1.4 GB of audio. The scripts that build them
name their sources; the DER and guard artifacts here name every recording by its corpus
id, so any figure can be traced to a specific piece of audio by anyone who has the
corpus.

**No audio and no transcript of the author's own speech appears anywhere in this
directory.** The learning corpus never left the laptop (ADR-011, ADR-019).
