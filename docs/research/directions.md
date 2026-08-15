---
title: Where YazSes goes next — futuristic ideas, sorted by what is actually buildable
description: The forward-looking research directions for offline voice input, each sorted into buildable on an ordinary laptop today, needs measurement first, or needs hardware and a lab. With the reasoning, the citations, and what would change each verdict.
---

# Where YazSes goes next

There is no shortage of things voice interfaces *could* become. There is a shortage of
honest sorting between the ones that would work on the laptop you already own and the
ones that need a lab, a data centre, or a research result nobody has yet.

This page is that sorting. Every entry names the problem it answers, says which of three
buckets it is in, and states what would move it.

!!! info "Companion pages"

    - [The problem space](https://github.com/MSKazemi/yazses/blob/main/design/research/2026-08-15-problem-space.md) — the problems these answer, stated without features
    - [Ten open questions](agenda.md) — the research agenda, stated as measurable claims
    - [The science of post-keyboard input](index.md) — what the measurements say today

## How an idea gets here

<figure class="yz-figbox">
--8<-- "assets/arch/direction-triage.svg"
<figcaption>Three gates in series. Most ideas fail the first one.</figcaption>
</figure>

The first gate does most of the work. YazSes ships **144 capabilities and 64 of them are
not reachable from any entry point** — the project's constraint has never been ideas, it
has been finishing them. So an idea that cannot name the problem it answers does not get
built, however good it sounds.

The second gate is [ADR-011](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-011.md):
it has to run offline, on a CPU, on a machine someone already owns. That is not modesty
about ambition — it is the one property that distinguishes this project from every
well-funded alternative, and a direction that needs a data centre would trade away the
only durable advantage.

---

## Buildable now — on an ordinary laptop

These need no new research and no new hardware. They are engineering.

### 1. Error cost, carried through the pipeline

**Problem: A1.** A `their/there` and an `rm -rf /home/work` are treated identically today
— both are simply typed. Word error rate, the metric the whole field optimises, weights
every word the same. The user never has.

**What it looks like.** The destination decides the confirmation. Dictating into a
terminal, a payment field or a git command is not the same act as dictating into a chat
box, and the pipeline already knows the difference: `inject/target.py` identifies the
focused element, and the command safety gate already holds a destructive command pending a
spoken *confirm*.

**Why it is the strongest candidate.** It generalises three features that were each built
as point fixes — the safety gate, staged dictation, and the no-text-target guard — into
one idea, and it produces a metric nobody publishes: **cost-weighted error rate**, errors
scored by consequence rather than counted. That is a research contribution and a product
improvement in the same change.

**What is already there.** `cmdsafety/classify.py`, `staged/buffer.py`, `inject/target.py`.
**What is missing.** A destination-risk model and one confirmation policy instead of three.

### 2. A hands-free mode that is actually a mode

**Problem: A3.** You can dictate a paragraph but you cannot open the file, fix the fourth
word, switch window or answer a dialog. Each of those exists as a designed, tested,
unwired module — `mousegrid`, `headpointer`, `pilot` (AT-SPI), `vocaljoystick`,
`mouthswitch`, `hatselect`.

**Why it is not done.** Every piece is individually unglamorous and only valuable in
combination, which is exactly the shape a feature-driven roadmap never delivers. The
measurement is also different: not word accuracy but **task completion** — can someone
finish a real workflow with no keyboard and no mouse, and how much slower is it.

**What would make it real.** Wire three of them together and run one person through a
scripted workflow. That is an afternoon of integration and an hour of observation, and it
would produce the first evidence anyone has about this project's accessibility claims.

### 3. Composition, not transcription

**Problem: A2.** In the largest published sample of real correction behaviour — 266
correction utterances — **62% were re-dictations rather than edits**, and what survives as
*commanding* is almost entirely one-or-two-word deletion
([Ghosh et al., 2020](#ref-ghosh)). People do not fix words; they restate thoughts. Yet
every correction affordance in every dictation product is word-level.

**What it looks like.** Treat the utterance, not the word, as the unit a user revises.
YazSes already has the pieces: `timeline/history.py` tracks whole-utterance injections,
and "scratch that" already works on the last burst.

**The honest caveat.** This is where the measured streaming result bites. Streaming
optimises time-to-first-word, and [the benchmark](../benchmarks.md) shows it makes
time-to-final-text **worse** on every model but `tiny.en`. Composition support has to be
judged on the second number.

---

## Needs measurement first — a study, not a feature

These are plausible, and building them before measuring would produce a feature nobody can
defend.

### 4. Code-switching as the real multilingual failure

**Problem: A4.** The assumption is that bilingual users struggle because of *accent*. The
competing hypothesis is that they struggle because of **code-switching** — a recogniser
locked to one language transcribes the other as noise, mid-sentence.

**Status: open question.** It is [research issue #258](https://github.com/MSKazemi/yazses/issues/258)
and `polyglot/lid.py` already implements the routing layer. What is missing is the WER
comparison on code-switched versus monolingual utterances from the same speakers. Building
the adapter first would be building on an assumption.

### 5. Uncertainty the user can see

**Problem: A1**, from the other side. If the recogniser knew it was unsure about a word,
showing that is cheaper than any correction mechanism. Whether it *helps* is unmeasured:
per-word confidence could reduce correction time, or it could add visual noise to every
sentence and slow reading down.

**Status:** agenda question 5. `confidence/` exists; the study does not.

---

## Needs hardware, a lab, or a result nobody has

Real, and not reachable from a laptop. Listed so they are not rediscovered as if new.

### 6. Silent speech

Sub-vocal input — sEMG at the jaw and throat, reading articulation without audible sound.
It is the genuinely transformative direction for both privacy and accessibility, and the
public numbers are not there: no one has published a false-activation rate over a real
working day, which is the number that decides whether it is usable at all
([our measurement call](https://github.com/MSKazemi/yazses/issues/106)).

**What YazSes has.** A working `EMGBackend` over the YESP serial protocol, and an
activation-source seam that already treats a squeeze as equivalent to a keypress. The
software is not the blocker; the evidence is.

### 7. Gaze that is precise enough to mean anything finer than a window

Webcam gaze is honest at 2–4°, which is centimetres on a screen — enough to know *which
window* you mean, never *which character*. YazSes ships that honest version
(`gaze/`, X11 only). Anything finer needs an eye tracker, not a webcam, and the deeper
blocker is not optics: **Wayland forbids one application from focusing another's window**,
so the capability is structurally unavailable on the display server most distributions now
default to.

### 8. Personal adaptation that provably helps

A per-user speech adapter is the most-requested idea in this space and the easiest to fake
— any fine-tune will look better on the data it was tuned on. The bar is a **held-out WER
win**, which requires held-out data, which requires a corpus, which the user has to consent
to build. The consent machinery exists (ADR-012, opt-in and encrypted). The evidence does
not.

---

## Deliberately not pursued

Recorded so the reasoning survives, rather than being relitigated.

| Direction | Why not |
|---|---|
| A conversational assistant | The README disclaims it, and no evidence suggests it is anyone's constraint. Voice input and a chat agent are different products. |
| Cloud escalation for hard audio | Would trade the only durable advantage (A5) for an accuracy delta nobody has measured. Designed and deferred in ADR-v2-126. |
| Third-party plug-ins | A plug-in sits on the dictation hot path with the microphone, the transcript and the injector. Declined in [ADR-018](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-018-feature-packs-and-the-plugin-question.md), with the isolation boundary that would reverse it. |
| Anything needing a GPU at runtime | The install already costs 414 MB; a CUDA runtime is 3 GB and would exclude the machines this is for. |

---

## Contributing a direction

The gates above are the whole review. An idea that names its problem, runs on a laptop and
can be measured is welcome regardless of how strange it sounds —
[open an issue](https://github.com/MSKazemi/yazses/issues/new/choose) or add to
[the research agenda](agenda.md). An idea that cannot do those three things is not
rejected, it is **filed as a question**, which is a different and often more useful thing.

## References

1. <a id="ref-ghosh"></a>Ghosh et al., *ACM Transactions on Computer-Human Interaction*
   **27:4** (2020). 266 real correction utterances: **62% re-dictation** (mean 6.01 ± 3.88
   words changed), ~29% command-based *deletion* (1.82 ± 1.74 words), ~7% replace, ~2%
   insert. Commanding survives almost entirely as one-or-two-word deletion.
2. <a id="ref-ruan"></a>Ruan, S., Wobbrock, J. O., Liou, K., Ng, A., Landay, J. A.
   "Comparing speech and keyboard text entry for short messages on two mobile devices."
   *Proc. ACM IMWUT* 1:4 (2016). — the 3× figure, measured on phones, not desktops.
3. See [the full reference corpus](hci-canon.md) for the 105 sources behind the research
   agenda, and [benchmarks](../benchmarks.md) for every performance number quoted here.

!!! note "No third-party PDFs are hosted here"

    Papers are cited and linked to the publisher, never redistributed — the repository
    blocks committed PDFs outright. What is published here is our summary and our own
    measurements.
