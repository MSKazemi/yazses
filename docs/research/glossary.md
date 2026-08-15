---
title: Glossary — the terms the YazSes research pages use
description: Plain definitions for the speech, HCI and evaluation terms used across the YazSes research notebook — WER and why it is not enough, VAD, endpointing, diarization, code-switching, d-vectors, GBNF, and the metrics text-entry research actually reports.
---

# Glossary

The research pages use terms from three fields that do not usually meet — speech
recognition, human-computer interaction, and text-entry evaluation. This is the shortest
useful definition of each, in the sense this project uses it.

Where a term has a **stronger claim than it appears to**, that is said. Several of the
disagreements on these pages are really disagreements about a definition.

## Recognition

**ASR** — Automatic Speech Recognition. Audio in, text out. Everything else on this page
is about what happens either side of that.

**WER — word error rate.** Substitutions + insertions + deletions, divided by the number
of reference words. The field's default metric, and **the source of a specific blind
spot**: it weights every word equally. A wrong `their` and a wrong `rm -rf` count the
same, which is why the [problem space](https://github.com/MSKazemi/yazses/blob/main/design/research/2026-08-15-problem-space.md)
treats cost-weighted error as a separate, unmeasured thing.

**Beam search / greedy decoding** — whether the decoder keeps several candidate
transcriptions alive or commits to the best next token. Beams cost time and buy accuracy;
on a CPU that trade is the whole latency story.

**Hallucination** — a recogniser emitting fluent text for audio that contained no speech.
Whisper is known for it on silence, which is why the silence gate exists *before* the
decoder rather than after it.

**Initial prompt** — text handed to the decoder as context so it biases toward your
vocabulary. YazSes uses it for the personal dictionary and for the app name itself.

**Hotword / contextual biasing** — the same goal at decode time rather than as a prompt.
Stronger, and engine-specific; the reason `hotwords` is still unwired.

## Capture

**VAD — voice activity detection.** Deciding which audio contains speech. YazSes's default
is an energy gate: `mean(|samples|)` against a threshold. Cheap, and the thing most often
misconfigured — below your voice and everything is discarded, above the room and nothing is.

**Endpointing** — deciding *when you stopped speaking*. Distinct from VAD, which decides
whether a moment is speech. Endpointing is what makes release feel instant or laggy.
(Confusingly, YazSes's `EndpointConfig` is about this, not about network endpoints.)

**Pre-speech padding** — a ring buffer of audio kept from *before* the key was pressed,
prepended to the recording. Without it the first phoneme is clipped, because humans start
speaking fractionally before they finish pressing.

**Barge-in** — speaking while the system is talking back, and having it stop.

## Speaker

**Diarization** — "who spoke when". Segmenting audio by speaker without necessarily
knowing who they are.

**Speaker embedding / d-vector** — a fixed-length vector representing a voice, so two
utterances can be compared for sameness. **Biometric**: this is why ADR-019 forbids
exporting them under any consent regime.

**ECAPA-TDNN** — the embedding model YazSes uses by default. Accurate on utterances of a
second or more, and **unreliable below about half a second**, which is exactly why the
Cocktail Filter false-rejects the user's own voice and stays off.

**Enrolment** — recording a known speaker once so later audio can be matched to them.
Opt-in and consent-gated here, never automatic.

## Language

**Code-switching** — changing language *within* an utterance, not between sessions. The
[open question](https://github.com/MSKazemi/yazses/issues/258) is whether this, rather
than accent, is the dominant failure for bilingual users.

**LID — language identification.** Deciding which language is being spoken. Per-utterance
LID is standard; per-*span* LID is what code-switching needs and what makes it hard.

**ITN — inverse text normalisation.** Turning spoken forms into written ones: "twenty
twenty six" → "2026", "john dot doe at gmail" → an address.

## Commands and structure

**Grammar (Tier 1)** — the regex classifier that decides whether an utterance is dictation
or a command. **Anchored at both ends** in this codebase, because ordinary words like
"undo" and "cancel" are also commands, and a loose match swallows real speech.

**GBNF** — the grammar format llama.cpp uses to force a model's output into a schema.
How a local model can be made to emit valid tool calls rather than plausible-looking ones.

**MCP — Model Context Protocol.** The standard interface between an agent and the tools it
can call. [ADR-020](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-020-agent-protocols.md)
covers which direction of it YazSes should support and why.

**AT-SPI** — the Linux accessibility bus. How an application can be asked what has focus
and whether it accepts text. The basis of the no-text-target guard, and unavailable on
Wayland without it, which is why several capabilities are X11-only.

## Evaluation

**Corrected / uncorrected error rate** — errors the user fixed versus errors that survived
into the final text. Reporting only the second flatters a system that made the user work
hard; reporting only the first hides what shipped. Text-entry research reports both.

**MSD error rate** — minimum string distance between what was presented and what was
produced, normalised. With the two above, the standard set from Soukoreff & MacKenzie.

**WPM — words per minute**, conventionally with a "word" defined as five characters so
that languages and scripts compare. The 153-vs-52 figure on these pages uses this.

**Held-out** — evaluated on data the model was not tuned on. The bar any personal-adaptation
claim has to clear, and the reason that work stays unbuilt rather than merely unfinished.

**Preregistration** — writing down the hypothesis and analysis *before* collecting data, so
a result cannot be reverse-engineered from what the data happened to show.

## This project's own vocabulary

**Wired / unwired** — whether a capability in the registry is reachable from a real entry
point. An unwired capability may be fully implemented and tested; it simply has no door.
Roughly 62 of 144 are unwired, and the count is
[enforced by a test](https://github.com/MSKazemi/yazses/blob/main/tests/test_feature_wiring_honesty.py)
so the catalogue cannot overstate itself.

**Hold-to-talk** — recording only while a key is physically held. The alternative, a toggle,
is what produces the "was it listening?" class of problem this project's design avoids.

**Egress path** — any code that can open an outbound connection, classified *fetch* (data
comes in) or *send* (user content goes out). There are two of the second kind, and
[ADR-019](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-019-egress-inventory-and-escalation.md)
keeps it that way with a test.
