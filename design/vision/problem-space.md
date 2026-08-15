---
title: The problem space — what a future YazSes would be for
status: draft
date: 2026-08-15
---

# The problem space

> **Problems first, then scenarios, then features.** This document deliberately names
> no features. It exists because the project's standing diagnosis is that YazSes has
> more capability than evidence — 144 registry entries, 65 of them unreachable — and
> the cure for that is not more ideas. It is knowing which problem each idea answers.
>
> **Tier:** `design/` — public engineering and science. Every claim below is either
> evidenced from this repository, cited, or explicitly marked as a hypothesis.

## The test each entry has to pass

A problem earns a place here only if all four hold:

1. **Someone loses something today.** Time, accuracy, privacy, access, or the ability
   to do the task at all. Named concretely, not as "friction".
2. **It is not already solved acceptably.** By YazSes, by the OS, or by a competitor.
3. **Voice is a plausible part of the answer** — not merely a way to reach it.
4. **We could tell whether we fixed it.** There is a measurement, even an expensive one.

Ideas that fail (4) are not thereby bad; they are research questions, and they belong
in [the HCI research agenda](../research/2026-08-11-hci-research-agenda.md).

---

## A. Problems for humans

### A1. The recogniser is confident and wrong, and you find out downstream

**Who loses what.** Everyone, constantly. Transcription errors are not uniformly
costly: `their/there` in a chat message is noise, in a legal filing it is a defect, and
`rm -rf /home/work` in a terminal is unrecoverable. YazSes currently treats all three
identically — it types them.

**Evidence in this repo.** The command safety gate exists because a dictated `rm -rf`
executes. Staged dictation (#294) exists because "scratch that" is too late once the
token is in a terminal. Both are point fixes for one shape of problem: **the cost of an
error is not carried anywhere in the pipeline.**

**Why it is unsolved.** Every dictation product optimises word error rate, which
weights all words equally. The user does not.

**How we would know.** Cost-weighted error rate: errors scored by the consequence of
the token's destination, not by count. Nobody publishes this; the metric would be a
contribution on its own.

### A2. Speaking is a serial channel and thinking is not

**Who loses what.** Anyone composing rather than transcribing. Dictation is excellent
at getting known words out and poor at the actual work of writing — reordering,
qualifying, discarding a sentence half-said. The result is that people dictate a draft
and then rewrite it by hand, which erases the throughput advantage that motivated
dictating.

**Evidence.** The measured finding that streaming is *slower* end-to-end on every model
but `tiny.en` is a symptom: the pipeline optimises time-to-first-word when the binding
cost is time-to-final-text. And in the largest published sample of real
correction behaviour — 266 correction utterances, ACM TOCHI 27:4 (2020) — **62% were
re-dictations rather than edits**: people are not fixing words, they are restating
thoughts. (Read for issue #99, which is about command mode and does not itself report
this.)

**Why it is unsolved.** Products treat speech as a keyboard substitute. The keyboard is
not the thing being replaced; the composing loop is.

**How we would know.** Net WPM after correction, on *composed* prose rather than
transcribed passages — the study already specified as direction 1 of the research agenda.

### A3. Hands-free is treated as an accessibility checkbox, not a working mode

**Who loses what.** People with RSI, tremor, motor impairment, or a temporary injury —
and, differently, anyone whose hands are occupied. The commodity answer is "we support
dictation", which addresses text entry and nothing else: you can dictate a paragraph but
not open the file you want to dictate into, not correct the fourth word, not switch
window, not answer a dialog.

**Evidence.** The unwired capability list is disproportionately this: `mousegrid`,
`headpointer`, `pilot` (AT-SPI), `mouthswitch`, `vocaljoystick`, `hatselect`. The pieces
were designed and never joined into a mode someone could actually live in.

**Why it is unsolved.** Each piece is individually unglamorous and only valuable in
combination — exactly the shape that does not get built by feature-driven roadmaps.

**How we would know.** Task completion, not word accuracy: can a participant complete a
realistic workflow — open a file, edit a specific line, respond to a prompt, save — with
no keyboard or mouse, and how long does it take relative to using them.

### A4. Dictation is monolingual in a bilingual mouth

**Who loses what.** Anyone whose working vocabulary spans two languages, which in
technical work is most of the world. The failure is not accent — it is **code-switching**
mid-sentence, where a recogniser locked to one language transcribes the other as noise.

**Evidence.** `polyglot/lid.py` exists, `[stt] language` was silently ignored by every
decode path until recently, and the open research question (#258) asks precisely whether
code-switching rather than accent is the dominant failure for bilingual users. That
question is open — this entry is a **hypothesis**, not a finding.

**How we would know.** WER on code-switched utterances versus monolingual ones from the
same speakers.

### A5. Your voice is biometric, and everything else in this space treats it as telemetry

**Who loses what.** Anyone dictating something confidential — the lawyer, clinician,
journalist and researcher the docs already name. Cloud dictation makes the recording
someone else's asset; consumer devices make it training data.

**Evidence.** This is the one problem YazSes already answers well (ADR-011), and the
answer is the project's principal differentiator. It appears here because **future work
must not erode it**, and because the erosion would be gradual and reasonable-sounding at
each step — a cloud escalation "just for hard audio", a plug-in seam "just for
extensibility". ADR-018 already declined one of those.

**How we would know.** It is a property, not a metric: no outbound connection the user
did not ask for, verifiable by the user with `--network none`.

---

## B. Problems for agents and infrastructure

This section is more speculative than A, and is marked as such. It is included because
the note that prompted this document asked specifically about agents, and because the
honest answer to "does YazSes have a role there" is *narrower than it first appears*.

### B1. An agent can read a screen but cannot ask a human a question cheaply

**The problem.** Autonomous agents stall on decisions only a human can make —
authorisation, ambiguity, taste. The interrupt is expensive: it requires the human to
context-switch to a screen, read, and type. A voice channel is the cheapest interrupt a
working human can service, because it does not require their eyes or hands.

**Why YazSes is plausibly the right shape.** It already owns the microphone, runs
locally, and has an IPC surface. It is the component that could turn "agent needs a
decision" into a spoken question and a spoken answer, without either party touching a
browser.

**What makes it hard, honestly.** Interrupting a human is a *permission* problem, not a
transport problem. An agent that can speak to you at will is an agent that can interrupt
you at will. The design question is the interrupt budget, not the plumbing — and
ADR-018's reasoning about what may sit on the hot path applies with equal force.

**Status: hypothesis.** No evidence any user wants this. It is listed to be tested, not
built.

### B2. Speech is the only input modality with no machine-readable contract

**The problem.** A keystroke has an unambiguous meaning. A click has coordinates. An
utterance has an interpretation, and every product invents its own — so nothing built on
dictation composes with anything else. There is no equivalent of "this application
accepts text input" for "this application accepts *spoken intent*".

**Why it matters for infrastructure.** The absence is why voice features are
re-implemented per application instead of being an OS-level service, and why the
accessibility stack (AT-SPI, UIA) exposes structure that voice tools mostly ignore.

**What YazSes has that is relevant.** `commands/grammar.py`'s intent classification, the
contract vectors in `tests/test_contract_vectors.py`, and an AT-SPI bridge already used
for the no-text-target guard. The raw materials for a contract exist; nothing has been proposed
as one.

**Status: research direction**, and the most likely of section B to produce something
publishable rather than shippable.

### B3. Meeting capture is a data-governance problem wearing a transcription costume

**The problem.** Recording a meeting is trivially easy and almost always improperly
governed: who consented, where the audio lives, how long, who may re-identify a speaker.
Every cloud notetaker answers these by taking custody. Organisations that cannot allow
that simply go without.

**Why YazSes is positioned.** Meeting Mode already runs on-device, and the voiceprint
work already forced explicit-consent design (ADR-011/012 — never auto-enrol).

**How we would know.** Not a user study: an actual governance review. Whether a real
institution's ethics or data-protection process would approve it is a binary, checkable
answer — and the research-interview use-case page already claims this audience.

---

## C. What is deliberately not here

- **"Make dictation more accurate."** Not a problem statement; it is the whole field.
  Broken down, the useful parts are A1 and A4.
- **A conversational assistant.** The README explicitly disclaims it, and nothing in the
  evidence suggests it is the constraint on anyone's work.
- **Mobile.** Real, already scoped in the Android epic, and a different problem space.
- **Anything requiring a data centre.** Not by squeamishness: it would contradict A5,
  which is the project's only durable advantage.

## What this document is for

The next three items in this work — the direction page, the ten framework capabilities,
and the choice of what to invest in — must each point at an entry here. **An idea that
cannot name its problem does not get built**, and that rule is the entire reason this
file exists before them.
