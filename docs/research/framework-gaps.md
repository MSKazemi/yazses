---
title: Ten capabilities that would make YazSes a research framework
description: An honest gap analysis for researchers. YazSes already has swappable seams for speech, VAD, diarization, embeddings, activation and gaze — these are the ten things it still lacks before someone could run, replicate and publish a study with it, each with the seam it touches and what it would cost to build.
---

# Ten capabilities that would make YazSes a research framework

[Work with YazSes](get-involved.md) describes what the project already offers a
researcher: a pluggable seam behind every scientifically interesting component,
everything offline, an encrypted on-device corpus that starts an ethics conversation in
the right place.

This page is the other half, and it is deliberately unflattering. **A platform you can
swap a model into is not yet a platform you can run a study on.** These are the ten
capabilities that stand between the two, ordered by how much each unblocks.

None of them is a research idea. They are the plumbing that turns an *artifact*
contribution into an *empirical* one — the distinction the
[research agenda](agenda.md) opens with.

!!! tip "If you want to build one"

    Each entry names the seam it touches and an honest size. Several are a weekend.
    Open a thread in
    [Research Corner](https://github.com/MSKazemi/yazses/discussions) and say which.

---

## 1. A run manifest — the exact conditions a result came from

**What you cannot do today.** Say what produced a number. Configuration is mutable TOML
that `yazses features enable` rewrites, the model can change between runs, and nothing
records which was in force. Two runs a week apart are not comparable and nothing says so.

**The capability.** One command that emits a manifest: YazSes version, config hash, model
and checkpoint, engine, VAD backend and threshold, platform, and the dependency lock hash.
Attach it to every result file.

**Seam:** `system/report.py` already assembles a redacted diagnostic bundle — this is
that, aimed at reproducibility rather than at debugging. **Size:** a weekend.
**Unblocks:** everything below. That is why it is first.

## 2. Deterministic replay — a study without a microphone

**What you cannot do today.** Re-run an experiment on the same audio. The live pipeline
needs a person and a room; `yazses transcribe` decodes a file but bypasses VAD, padding,
endpointing, the disfluency filter and injection — that is, most of what a study *of this
system* would be about.

**The capability.** A `--from-audio` source that drives the **full** pipeline from a WAV
file as though it were the microphone, honouring the silence gate and hold boundaries, so
every stage after capture is exercised identically on every run.

**Seam:** `audio/recorder.py`, behind the interface the daemon already consumes.
**Size:** a weekend. **Unblocks:** 3, 4 and 6 — none of which is trustworthy while the
input differs run to run.

## 3. The field's error metrics, not just WER

**What you cannot do today.** Report what text-entry research reports. `jiwer` gives word
error rate, which describes the *recogniser*. The literature's unit of analysis is the
**corrected and uncorrected error rate** and the **MSD error rate** of Soukoreff &
MacKenzie — metrics that count what the *user* had to do, including the corrections WER
never sees.

**The capability.** Given a presented phrase, a transcribed result and the correction
actions, compute the standard set. This is arithmetic on data the system already has.

**Seam:** `paper/benchmark/bench_wer.py` is the natural home. **Size:** days.
**Why it matters for publishing:** a paper reporting only WER will be asked for these in
review.

## 4. Per-utterance timing traces, exportable

**What you cannot do today.** Attribute latency. `decode_latency` reports percentiles over
a rolling window — the right thing for a user, useless for analysis, because you cannot
join a duration to the utterance that produced it or to the condition it ran under.

**The capability.** One record per utterance with monotonic stamps at every boundary —
hold start, speech end, decode start and end, post-process, inject — written as JSONL.

**Seam:** the event dict already threaded through `core/daemon.py::_on_hold_end`.
**Size:** days. **Note:** this is exactly the data that showed streaming makes
time-to-final-text *worse*; finding that should not have needed a bespoke harness.

## 5. An experiment harness — conditions, blocks, counterbalancing

**What you cannot do today.** Run a within-subjects design without writing the scaffolding
yourself. Presenting phrases, randomising condition order, blocking, and recording which
participant saw what is the same code in every lab, rewritten each time.

**The capability.** A minimal runner: a phrase set, conditions declared in a file,
Latin-square ordering, per-participant output.

**Seam:** new, but standalone — no daemon change. **Size:** a week.
**Honest caveat:** this is the entry most likely to be better served by an existing tool.
Check before building.

## 6. Ground-truth alignment and correction capture

**What you cannot do today.** Know what the participant *meant*. Metric 3 needs the
presented phrase aligned against the produced text, and needs corrections observed rather
than inferred. YazSes has both halves — `learning/edit_watch.py` reads back in-place
edits, `recimport/align.py` does word alignment — and they have never been pointed at each
other.

**Seam:** compose two existing modules. **Size:** days.

## 7. A no-consent mode that is genuinely no-consent

**What you cannot do today.** Reassure an ethics committee quickly. The learning corpus is
off by default and encrypted, which is a good answer — but "off by default" is a
configuration claim, and a reviewer wants a structural one.

**The capability.** A mode in which storage is *impossible* rather than *disabled*, plus a
machine-readable manifest of every path the process may write — so "where does the audio
go" is answered by a file rather than a paragraph.

**Seam:** `learning/store.py`, `system/report.py`. **Size:** days.
**Why it is worth it:** this is the difference between a two-week ethics review and a
two-month one, and it costs almost nothing.

## 8. Population-shift evaluation, built in

**What you cannot do today.** Report how a change affects *different speakers differently*.
Aggregate WER hides exactly the effect that matters for the accessibility and multilingual
claims this project makes — a change can improve the mean and worsen every dysfluent
speaker in the sample.

**The capability.** Metrics sliced by speaker group as a first-class output rather than a
post-hoc grouping: per-speaker WER with dispersion, and a worst-group figure beside the
mean.

**Seam:** `paper/benchmark/_common.py`. **Size:** days.
**Related:** agenda question 6 and [#255](https://github.com/MSKazemi/yazses/issues/255).

## 9. Result artifacts that survive the paper

**What you cannot do today.** Hand a reviewer something re-runnable. `docs/benchmarks.md`
publishes the numbers and — since the harness was published — the commands. What is still
missing is the *output* side: a versioned, citable bundle of raw per-utterance results.

**The capability.** A results directory with a fixed schema, the run manifest from 1, and a
Zenodo deposit per release. The DOI machinery already exists (`CITATION.cff`,
`10.5281/zenodo.21856271`); only the data is not deposited.

**Size:** days. **Unblocks:** other people replicating your numbers instead of believing
them.

## 10. A cited baseline you did not choose

**What you cannot do today.** Compare fairly. Every number this project publishes is YazSes
against YazSes. A framework people trust reports at least one *external* baseline on the
same data — a cloud API, a different local engine, or plain typing.

**The capability.** One baseline runner and a documented protocol for adding more, so a
comparison is a config entry rather than an argument.

**Seam:** `stt/base.py` — the engine interface already supports this; nothing has been run
through it as a baseline. **Size:** days per baseline.
**Constraint:** any cloud baseline must be opt-in, off by default, and must never touch a
participant's real audio without explicit consent.
[ADR-011](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-011.md) applies to
research use exactly as it applies to dictation.

---

## What this list is not

**It is not a roadmap.** Nothing here is scheduled, and several entries would be better
solved by adopting an existing tool than by building one — entry 5 especially. The list
exists so a researcher can see the gaps before investing a term in the project, and so the
gaps are *someone's* to close.

**It is not ordered by difficulty.** It is ordered by what it unblocks. Entries 1 and 2
are the foundation: without a run manifest and a deterministic input, every other number
on this page measures an unknown configuration on unrepeatable data.

**Three of the ten are already half-built.** Entries 4, 6 and 9 each compose modules that
exist and have never been joined. That is the same pattern as the
[62 designed-but-unwired capabilities](directions.md): in this project the missing piece is
usually the connection, not the component.
