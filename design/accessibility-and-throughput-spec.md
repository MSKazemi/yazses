---
title: Accessibility and throughput — what to build, and what has to be measured first
status: draft
date: 2026-08-16
---

# Accessibility and throughput

The brief was: *"features for disabled people, but I don't want to add normal features …
really useful or innovative … improve the life quality … or improve the communication in
view of quality or performance or speed"*.

That contains two goals with different evidence bases, and mixing them is how a roadmap
fills with plausible-sounding work:

- **(a) Quality of life** — someone who cannot use a keyboard comfortably gets a working
  day, not a demo.
- **(b) Throughput** — anyone gets more finished text per minute than by typing.

## The finding that comes first

**There is no throughput baseline, so no throughput claim can be honest today.**

`paper/benchmark/` holds six harnesses that reuse shipping code and write JSON with a
provenance block: `bench_wer.py`, `bench_latency.py`, `bench_vad.py`, `bench_streaming.py`,
`bench_commands.py`, `bench_meta.py`. **None measures words per minute, correction cost, or
time-to-finished-text.**

The project already says so, in its own words, and those sentences should be quoted rather
than replaced:

> "YazSes has **not run a controlled throughput study against typing**; that experiment is
> an open research question, deliberately listed as unanswered rather than guessed at."
> — `docs/comparison.md`

> no claim on throughput "or correction cost; that comparison requires a user study, which
> we have not run" — `paper/main.tex`

The method is already settled — MacKenzie & Soukoreff's protocol, Soukoreff & MacKenzie's
unified error metric, Vertanen & Kristensson's phrase set, preregistered
(`docs/research/agenda.md`). The binding constraint is **participants**, not design. Even
n=8 within-subjects would be the first such number published for this class of tool.

So the first deliverable here is a **measurement, not a feature**, and every spec below
states the number it must move rather than a promised percentage.

### Spec 0 — `bench_throughput.py`

**Target:** a reproducible figure for *finished text per minute* by dictation, and the same
for typing, on identical prompts, on one stated machine.

- Reuses the shipping pipeline like every other harness; writes JSON to `paper/results/`
  with the same provenance block.
- Measures **time to finished text**, not time to first transcript. That distinction is
  the point: a fast recogniser producing text that needs three corrections is slower than
  a slow one that does not. The project's own streaming benchmark already demonstrates the
  principle in the other direction — streaming costs 32 % on `tiny.en` and 56 % on
  `base.en`, and on `base.en` **0 %** of utterances had visible text at release.
- Records corrections separately — re-dictations, "scratch that", manual edits — so
  correction cost becomes a measured quantity here rather than a cited one.
- Prompts must include what actually breaks: numbers, proper nouns, code, and a bilingual
  passage.

**Done when:** a number exists with a stated method, machine and prompt set, and can be
re-run.

## (a) Quality of life — two candidates that are not checkbox features

Rejection test: **could a competitor ship this by adding a menu item?** If yes it is a
checkbox feature and does not belong. That removes most of what this space calls
accessibility.

### Spec 1 — A hands-free mode that is actually a mode

**Problem** (problem-space A3): hands-free is treated as a checkbox rather than a working
mode. Tools assume a keyboard for everything that is not text — confirming, correcting,
navigating, dismissing — so someone who cannot use one is abandoned at the first dialog.

**Not a checkbox** because it is not a feature, it is a completeness property: audit every
state where the daemon waits for the user, and provide a spoken route out of each. The
command-safety gate already does this correctly — a destructive command waits for a spoken
**confirm** — and the check-digit guard deliberately reuses the same release word, so one
phrase is learned rather than one per guard. That pattern is the model; nothing else
follows it.

**The number it must move:** count of daemon-initiated states with no voice-only exit.
Target zero. **Countable today, no harness needed** — which is why this goes first.

### Spec 2 — Error cost, not error count

**Problem** (A1): the recogniser is confident and wrong, and the cost of being wrong varies
by orders of magnitude. Everything in this space counts errors equally.

**Not a checkbox** because it needs what only this pipeline knows: whether the target is
editable, whether the utterance parsed as a command, per-word confidence, whether a number
passes its own check digit. Two features already act on consequence rather than frequency
(`cmdsafety`, `checkdigit`). Generalising that into a cost model is a research contribution
and a product feature at once, which is rare.

**The number it must move:** cost-weighted error rate on the Spec 0 harness — errors
weighted by repair cost — with unweighted WER not regressing from the measured baseline
(`base.en` 4.07 % on LibriSpeech test-clean).

**Honest risk:** a guard that fires too often gets dismissed, and a dismissed guard costs
attention and catches nothing. The existing two are judged on how *rarely* they fire; a
generalised version inherits that bar and is harder to hold to it.

### A citation this depends on, which must be resolved first

ADR-021 rests on **"62 % of real correction utterances are re-dictations rather than
edits"** (Ghosh et al., ACM TOCHI 27:4, 2020, n=266), and scores it 5/5 on evidence. The
citation has **no title, no DOI, no URL**, and appears in neither `design/research/hci-corpus.bib`
nor `paper/refs.bib` — so it fails the project's own rule that "before any of these numbers
enters the manuscript or a public page, the specific entry must be read at source".

Better-sourced neighbours exist and should carry the argument until it is resolved: pure
respeak corrects only ~35 % of errors and degrades on retry (Suhm 2001, ToCHI), and
multimodal correction is ~2× faster (Lewis, HFES).

**Action:** resolve to a DOI and read at source, or restate the argument on Suhm. Do not
put the 62 % figure on a public page in the meantime.

## (b) Throughput — one candidate

### Spec 3 — Composition, not transcription

**Problem** (A2): speaking is serial and thinking is not. Tools transcribe in arrival order,
so revising means going back with a keyboard — which is where the throughput advantage is
lost, and where a hands-free user is stranded entirely.

**Not a checkbox** because the capability exists in pieces that are not connected as a
whole — `revise`, `timeline`, `outline`, `reflow`, `condense`. The bet is that
*composition* is a different product from *transcription*, and the throughput number moves
only when revision stops requiring hands.

**The number it must move:** time-to-finished-text on prompts requiring revision, against
typing. This decides whether the premise is true at all, and needs Spec 0.

## Deliberately not here

- **Anything a menu item delivers.** Font size, high-contrast themes, shortcuts — real
  accessibility work, already solved better by the desktop.
- **Eye tracking as a pointing device.** Webcam gaze is 2–4° in the literature (WebGazer
  4.17°, L2CS-Net 3.92°); the shipped Glance-Type is honest about being window-granular.
- **Silent speech.** ~68 % WER open-vocabulary (Gaddy & Klein 2020). Genuinely exciting,
  not buildable on a laptop.
- **Any "faster than typing" claim** until Spec 0 exists.

## Order

1. **Spec 0** — the harness. Nothing else can be honestly claimed without it, and it is the
   smallest of the four.
2. **Spec 1** — countable today, needs no harness, and its user cannot work around its
   absence.
3. **Spec 2** — mechanism can be built alongside; validation needs Spec 0. Resolve the
   Ghosh citation first.
4. **Spec 3** — needs Spec 0 to know whether it is true.
