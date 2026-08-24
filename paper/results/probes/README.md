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
turned off*, by running the same 200 utterances through four decode settings -- a 2x2
over (temperature fallback, conditioning on previous text) -- five times each. It
records a SHA-256 of each run's concatenated hypotheses, because two runs that trade
one insertion for another score the same WER and are not the same text, and the ids of
the utterances that differ, because a spread says the model is noisy while a list of
ids says where. Run it as
`python paper/benchmark/probes/decode_determinism.py 5 test-other 200 large-v3`, or
name a subset of arms as a fifth argument.

`decode-determinism-large-v3-test-other.json` is the result, and it identifies the
mechanism rather than merely measuring it. Five decodes per arm, 200 stratified
`test-other` utterances, `large-v3` int8 on CPU:

| arm | decode kwargs | WER | distinct outputs | insertions |
|---|---|---|---|---|
| `baseline` | faster-whisper defaults | 4.84-6.21 (mean 5.52) | **5 of 5** | 78-129 |
| `greedy` | `temperature=0.0` | 15.26 | 1 | 466 |
| `greedy_no_context` | `temperature=0.0`, `condition_on_previous_text=False` | 3.82 | 1 | 40 |
| `no_context` | `condition_on_previous_text=False` | 3.82 | 1 | 40 |

Substitutions (87) and deletions (15) are identical in **every run of every arm**. No
decode setting changed a single one. Whatever these arms do, they do it entirely by
adding text that was never spoken -- which is the failure mode that matters for a
dictation daemon, because a dropped word is visible on screen and a fluent inserted
clause is not.

The two fixed arms differ in exactly one keyword, and that isolates the cause.
`greedy` -- sampling off, conditioning left on -- emits **466** insertions against
`greedy_no_context`'s **40**. So conditioning on the previously emitted text is what
drives the model into runaway repetition, and the temperature fallback is the rescue
that exists for it: the baseline's 78-129 insertions are that rescue working, on a
problem the other setting creates. It works by *sampling*, which is why it produces a
different sentence every time and why the baseline is the only arm that is not
reproducible. This matches the documented behaviour of the parameter upstream, where
disabling conditioning is described as making the model less prone to a failure loop.

The instability is also narrower than a corpus spread suggests: across five baseline
decodes only **two** utterances ever differed (`1998-15444-0002`, `4294-14317-0002`),
and those two move corpus WER by 1.37 points. A user meets this as a rare burst that
comes out differently each time, not as uniform noise.

Turning conditioning off is *also* slightly cheaper -- 705 s per decode against the
baseline's 829 s -- while the **median** RTF is indistinguishable across all three arms
(0.566-0.595). The saving is entirely the fallback re-decodes it avoids, concentrated
in the few utterances that trigger them, so a median hides it and a total shows it.

Two limits are load-bearing before any of this becomes a default. This ran with
`numpy 2.5.2`, where `largev3-instability-test-other.json` ran with `2.4.6`, so the two
artifacts' absolute WERs are **not** comparable -- the arms here are comparable with
each other, which is the question asked. And 3.82 % is a 200-utterance stratified
subset, not full `test-other`, so it should not be read against published full-set
figures. What the four arms support is a statement about *this corpus on this host*.

The fourth arm, `no_context` -- conditioning off, fallback **left on** -- was added
after these three ran, because they do not contain the setting YazSes would actually
ship: `greedy_no_context` moves both knobs at once and so cannot say whether the
safety net still earns anything once the cause is gone. It is filed separately as
`decode-determinism-large-v3-test-other-no_context.json`, and it answers cleanly:
**bit-identical five times out of five**, `3.82 %`, hash `b7d0705601ff3190` -- the same
bytes as `greedy_no_context`. Once the cause is removed the safety net never fires, so
the setting a large-model user would ship is both the most accurate arm measured and a
fully reproducible one.

### The win does not survive its own error bar

A corpus WER is a weighted mean, and a mean over 200 utterances is moved a long way by
one clip that emitted four hundred words of repetition. `decode_arms_per_utterance.py`
scores every arm **per utterance** against a paired baseline (the median of five
baseline decodes), and asks whether the difference is broad or carried by a few clips.
It is carried by a few clips.

| arm vs baseline | corpus WER | delta | 95 % CI | better / worse / unchanged | sign test p |
|---|---|---|---|---|---|
| `greedy` | 15.27 | +10.40 | [0.00, +25.41] | 0 / 3 / 197 | 0.25 |
| `no_context` | 3.82 | **-1.05** | **[-2.59, +0.16]** | **4 / 8 / 188** | **0.39** |

The interval crosses zero, *more* utterances got worse (8) than better (4), and
**95.7 % of the total gain comes from three utterances** -- 38.3 % from
`5484-24317-0004` alone. `greedy`'s ten-point loss is likewise three clips out of 200.

So "3.82 % against 5.52 %, a 1.7 point win" is true arithmetic and a false claim about
what a user gets, and it is what this directory would have published had the arms not
been re-scored per utterance. **The honest argument is about the tail, not the mean.**
Conditioning drives a runaway repetition on roughly 1.5 % of utterances; when it fires
the user gets hundreds of words of garbage typed into their editor, which is not a
one-point WER event to them. Removing it deletes those and costs a small, unresolvable
amount on ordinary speech. That is a reason to change a setting. A WER win is not.

### It reverses on the model the default install actually runs

Everything above is `large-v3`. `[stt] model` ships as **`base.en`**, so none of it
described a default install until the same 2x2 was run on that checkpoint -- five
decodes per arm, 200 stratified utterances, both splits
(`decode-determinism-base.en-test-{clean,other}.json`).

| arm | test-clean WER | test-other WER | distinct outputs |
|---|---|---|---|
| **`baseline` (ships)** | **4.01** | **9.46** | 1 / 1 |
| `greedy` | 10.33 | 9.46 | 1 / 1 |
| `greedy_no_context` | 5.93 | 9.81 | 1 / 1 |
| `no_context` | 4.24-4.28 | 9.81 | **5** / 1 |

Three things, all pointing the same way. The **shipped default is the best arm on both
splits** -- on test-clean `greedy` costs 6.3 points (325 insertions against 30). The
**sign of the conditioning effect reverses with model size**: turning it off wins 1.05
points on `large-v3` and *loses* 0.23-0.35 here. And `no_context` -- bit-identical five
times on `large-v3` -- is the one arm that is **not** reproducible on
`base.en`/test-clean, five decodes and five different hashes. Neither the direction of
the effect nor the reproducibility is a property of the setting alone.

On test-other `baseline` and `greedy` are the *same bytes*, as are `greedy_no_context`
and `no_context`, so the 2x2 collapses to the conditioning factor. On test-clean it does
not collapse at all. One split would have supported either story.

### Conditioning is not confined to long files

`condition_on_previous_text` is read in exactly two places in faster-whisper 1.2.1, both
*after* a window is decoded and both only setting `prompt_reset_since` for the next one.
That makes it provably inert on a single-pass decode -- which invites the inference that
a hold-to-talk burst, seconds against a 30 s window, can never be affected, so all of
this is a `yazses transcribe` and Meeting Mode concern.

`decode_mechanism.py` refutes that. `seek` advances to the model's **last emitted
timestamp**, not by a whole window, so a model that closes its final segment early
leaves the rest for another pass:

| | conditioned | `condition_on_previous_text=False` |
|---|---|---|
| test-clean, 40 clips, longest 27.2 s | 32x1 pass, 8x2 | 32x1, 7x2, 1x3 |
| test-other, 200 clips, longest 20.3 s | 184x1, 16x2 | 184x1, 16x2 |
| whose *later* pass was handed previous text | **8** and **16** | **0** and **0** |

8-20 % of ordinary short utterances take a second pass, and with conditioning on that
pass is prompted with the first pass's text. The flag acts on dictation-length audio.
(The pass counts themselves can move -- one clip went 2 -> 3 -- because dropping the
prompt changes what the model emits and so where `seek` lands. That is a consequence of
the flag, not a confound: the prompt evidence is counted per pass.)

### Where the benefit changes sign

`base.en` and `large-v3` are the two ends of a ladder with nothing measured between
them, which is a thin basis for a config key's guidance. Two arms, five decodes each,
same 200 `test-other` utterances (`7a567011f21916c1`):

| model | conditioning on | conditioning off | effect | distinct outputs |
|---|---|---|---|---|
| `base.en` | **9.46 %** | 9.81 % | helps by 0.35 | 1 / 1 |
| `small.en` | **5.59 %** | 5.70 % | helps by 0.11 | 1 / 1 |
| `medium.en` | 5.51 % | 5.51 % | **one hash across all ten decodes** | 1 |
| `large-v3` | 4.84-6.21 % | **3.82 %** | hurts by ~1.05 | 5 / 1 |

Monotone, and zero is reached exactly at `medium.en` -- both arms return
`58f46b414140b432`, so the flag did not change a single token in 200 utterances.
`test-clean` agrees at lower amplitude: `base.en` 4.01 against 4.24-4.28 %, `small.en`
2.66 against 2.72 %.

The pass counts explain the shape but not the whole of it. The share of utterances
taking a second decode pass -- the only ones a prompt can reach at all -- falls with the
checkpoint: **8 % on `base.en` (16/200), 1.5 % on `small.en` (3/200), 0.5 % on
`medium.en` (1/200)**. If that were the whole story `medium.en` would show a small
effect, not none. Its one multi-pass utterance **was** handed previous text, with
`later_pass_prompted_utterances: 1`, and the output is identical anyway. So two things
shrink together: how often the prompt is delivered, and how much the model is moved when
it is. Only at `large-v3` does the second one turn around.

The fallback counts fall too, which is why these arms are reproducible at all:
`base.en` rejects 2 decode attempts over the 200, `small.en` and `medium.en` reject
**none**. A model that never reaches the sampled step is bit-reproducible whatever the
temperature ladder is configured to do -- and that is a measured statement here, not the
inference the next section describes retiring.

Two cross-checks arrived free. `small.en` 5.59 % and `medium.en` 5.51 % reproduce
`../wer-test-other.json` **exactly**, from a different probe on a different day. And
`small.en` `test-clean` 2.66 % reproduces the Xeon figure `docs/benchmarks.md` already
prints against the reference laptop's 2.59 % -- the per-ISA int8 kernel difference that
page documents, which I was one paragraph from filing as a new disagreement.

### An inference that the same probe retired

`base.en` produces the same hash across five `baseline` and five `greedy` decodes.
`greedy` differs only in disabling the temperature fallback, so that reads as proof the
fallback never fires there -- and it was about to be written up that way. Counting
faster-whisper's own rejection log instead shows it fires 2-6 times.

**Equal outputs are not evidence that a sampled step did not run.** When every rung of
the temperature ladder is rejected, the ladder ends by taking the best average-logprob
result it saw, which can be the temperature-0 decode it started from -- an escalation
that leaves the output exactly where it began. The count is now measured rather than
inferred, and split by temperature, because only the first rung (0.0) is greedy and
every rung above it samples.

That split also killed a second hypothesis. Running the mechanism probe twice, unchanged,
counted 6 rejected attempts and then 4, which looked like proof that something *below*
the decoder was varying -- CTranslate2's multi-threaded reduction order being the obvious
candidate, since int8 accumulation makes thread completion order visible in the low bits.
`thread_determinism.py` tested it at the seam a user can set, `[stt] cpu_threads`.

It does not survive. Across three sessions -- 4+4, 4+4 and 6+6 repeats of 40 `test-clean`
utterances on `base.en`, 28 decodes in all -- **every hypothesis is bit-identical**
(`49350ac9803792a9`, WER 2.75 %) and the rejection count still moves:

| session | artifact | `cpu_threads=0` | `cpu_threads=1` |
|---|---|---|---|
| 1 | `../history/probes-thread-determinism-base.en-test-clean-2026-08-24T15-57-24Z.json` | 4, 5, 6, 5 | 4, 4, **7**, 4 |
| 2 | `../history/probes-thread-determinism-base.en-test-clean-2026-08-24T17-26-09Z.json` | 4, 4, 4, 4 | 4, **6**, 4, **7** |
| 3 | `thread-determinism-base.en-test-clean.json` | 4, 4, **8**, 4, **7**, 4 | 4, 4, 4, 4, 4, 4 |

The run logs are `logs/x86-thread1.log`, `logs/x86-thread2.log` and `logs/x86-thread3.log`.

The count varies with a single thread in two of the three sessions, so thread reduction
order cannot be what drives it. The temperature split says what does. Sessions 2 and 3
carry it -- 20 runs, both arms -- and in **every one of them** the greedy rung at 0.0 is
rejected exactly **3** times. Only the sampled rungs above it move: 1-5 in session 3's
`cpu_threads=0` arm, and 1-4 in session 2's `cpu_threads=1` arm, which is the arm that
was supposed to be free of the effect. An utterance rejected greedily is re-decoded with
sampling, so how far up the ladder it climbs before something passes is free to differ
between runs while the text it finally returns does not. Pinning threads costs
2.05-2.19x wall-clock and buys nothing.

The three sessions share one output name, and each survives only because `write_result`
was made non-destructive: overwriting a result moves the old one into
[`../history/`](../history/) under its own timestamp. Sessions 1 and 2 were about to be
written up from their run logs, on the assumption they had been overwritten in place --
the artifacts were there. Session 1 predates the temperature split and reports totals only.

`largev3-instability-test-other.json` is the earlier four-repeat run that established
the variance. Across it the substitutions (87), deletions (15) and hits (3619) are
bit-identical and only the insertions move (101 -> 184), so every WER is exactly
`(102 + insertions) / 3721`. Four repeats are enough to refute a trend -- the first
three fell monotonically and the fourth did not -- and nowhere near enough to put an
interval on the spread.

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
