---
title: Accessibility beyond the checkbox — what is actually worth building
description: Most accessibility work in dictation tools is commodity compliance. These are the capabilities that would materially change quality of life or throughput for people who cannot use a keyboard, why each is not already solved, and which one YazSes built first.
---

# Accessibility beyond the checkbox

Most of what ships as "accessibility" in a dictation product is compliance: a screen-reader
label, a contrast ratio, a keyboard path through a settings dialog. That work is necessary
and it is table stakes — every serious application does it, and doing it is not a reason for
anyone to choose one tool over another.

This page is about the other kind: capabilities that would **materially change what someone
can do in a day**, and that nobody ships.

!!! info "The exclusion is deliberate"

    Nothing here is a commodity accessibility feature. Screen-reader compatibility, focus
    order, contrast and font scaling belong in
    [the settings window](../settings-gui.md) and the
    [hands-free guide](../use-cases/accessibility-rsi-hands-free.md), not on this page.
    Listing them here would pad the list and hide the argument.

## The gap that makes this project unusual

The assistive-technology market prices hands-free computing at $10,000–20,000 and largely
skips Linux. That is the stated reason this research programme exists. But there is a
narrower gap, and it is the one that produces the list below:

> **A dictation tool is built for someone who can see the screen and reach the keyboard to
> fix things.** Every affordance assumes it — the transcript appears visually, corrections
> are made by hand, and the state of the system is shown in a tray icon.

Take that assumption away and most of the product goes with it. What follows is what is
left to build.

---

## 1. The state machine is invisible without eyes — **built**

**What breaks.** YazSes has eleven states, and every one of them is communicated visually:
a tray badge in five colours, an overlay, a settings window. A user who cannot see the
screen has no way to know whether the daemon is recording, whether it heard anything,
whether it is still transcribing, or whether it failed — and *hold-to-talk without state
feedback is a guess every single time*.

**Why it is not solved elsewhere.** Products that put dictation behind a visible UI treat
the UI as the feedback. There is nothing to fall back to when the UI is not perceivable.

**What YazSes did about it.** `earcon` — a non-speech tone grammar, rising two notes for
recording start, falling for stop, a bright chime for a completed command, a muted buzz for
low confidence or error. Turn it on with `yazses features enable earcon`.

It is deliberately **not speech**: a spoken "recording started" collides with the user's own
voice and with a screen reader that is already talking. A 200 ms motif does not.

**Why this one first.** It costs no new dependency, and it is the exact counterpart of the
[tray level ring](../tray-and-overlay.md#the-level-ring--is-the-mic-actually-hearing-me) —
the same information, delivered through the channel the user actually has.

## 2. Verifying a transcript you cannot read

**What breaks.** Correction assumes reading. `proofback` (interruptible proofreading) and
`echo` (replay your own recording of the last utterance) exist as designed modules with no
caller. Without them, a blind user's only verification is to paste elsewhere and have a
screen reader read it back — a workflow measured in tens of seconds per utterance.

**The insight worth keeping:** `echo` replays **your own audio**, not the transcript. If the
recogniser misheard, reading the transcript back tells you what it thinks you said; hearing
your own voice tells you what you actually said. Those are different diagnostics and the
second is the useful one.

**Status:** designed, unwired. `proofback/align.py` and `echo/span.py`.

## 3. Two things talking at once

**What breaks.** A screen reader is speaking. YazSes injects text. The screen reader
re-reads the changed region, mid-sentence, over itself. This is the most common complaint
about combining voice input with a screen reader, and it is a *scheduling* problem, not a
speech problem.

**Status:** designed, unwired — `srpace/schedule.py`. It is the least glamorous entry here
and possibly the highest daily value for the people affected.

## 4. Vocal strain — the injury that replaces the first one

**What breaks.** This is the one that surprises people. A substantial share of hands-free
users arrive because of RSI: they moved from keyboard to voice to protect their hands.
Speaking for six hours a day is its own repetitive strain, and vocal fatigue and dysphonia
are documented occupational risks for heavy voice users.

**A tool that made you dictate all day and never mentioned this would be complicit in the
next injury.** `voicehealth` (`voicehealth/strain.py`) monitors pitch and effort drift over
a session and suggests a break.

**Why nobody does it:** it means telling your user to stop using your product. Which is
exactly why it is worth doing, and why it is credible coming from a tool with nothing to
sell.

**Status:** designed, unwired. Needs the `prosody` extra (praat-parselmouth, ~11 MB).

## 5. Input for people who cannot reliably produce words

**What breaks.** Everything above assumes intelligible speech. For someone with dysarthria,
a tracheostomy, or a motor condition affecting articulation, the recogniser is the barrier —
but a *sound* is still available.

`mouthswitch` (mouth-sound switch access), `vocaljoystick` (continuous vowel → cursor
control) and `morsevox` (hum patterns as Morse) all treat the voice as a **signal**, not as
language. That is a genuinely different interaction model, and it is the one commercial
dictation cannot serve, because its entire value is transcription.

**Status:** all three designed, all three unwired. `contour/` (pitch gestures) too.

**The honest caveat:** these need evaluation *with* the people they are for, which is
[agenda question 6](agenda.md) and
[#255](https://github.com/MSKazemi/yazses/issues/255). Building them without that would be
guessing about people whose needs are not guessable.

---

## What this list says

Five capabilities, and **four are already designed, tested, and unreachable.** That is not
an accident of this page — it is the same finding as
[the 62 unwired capabilities](directions.md): in this project the missing piece is almost
never the algorithm.

It also explains why `earcon` was the one to build first. It needed no new dependency, no
new research, and no participant recruitment — and it closes the gap that makes every other
feature on this list unusable, because **a user who cannot tell whether the system is
listening cannot use any of the rest of it.**

## If you want to work on one

Every entry names its module. `srpace` and `echo` are the cheapest, and both would be a
first contribution someone could finish in a weekend —
[how to claim one](get-involved.md). For anything in §5, please
[open a research issue](https://github.com/MSKazemi/yazses/issues/new?template=research_idea.yml)
rather than a pull request first: the design question is bigger than the code.
