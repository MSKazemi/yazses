# Adjacent open-source projects, and what is worth taking from them

**Date:** 2026-08-15 · **Tier:** `design/` — public engineering research
**Companion:** [the problem space](2026-08-15-problem-space.md) ·
[where YazSes goes next](../../docs/research/directions.md)

Mining the neighbourhood for ideas, as input to the direction page. Every figure below was
read from the GitHub API on 2026-08-15, not from memory.

## The neighbourhood, measured

| Project | Stars | Last push | What it is |
|---|---:|---|---|
| [cjpais/Handy](https://github.com/cjpais/Handy) | **29,533** | 2026-08-14 | Offline speech-to-text desktop app, cross-platform, Whisper + Parakeet V3 |
| [Vaibhavs10/insanely-fast-whisper](https://github.com/Vaibhavs10/insanely-fast-whisper) | 13,043 | 2025-10-25 | Throughput-optimised Whisper CLI |
| [ideasman42/nerd-dictation](https://github.com/ideasman42/nerd-dictation) | 1,914 | 2025-10-10 | Minimal, hackable offline dictation on VOSK |
| [cursorless-dev/cursorless](https://github.com/cursorless-dev/cursorless) | 1,334 | 2026-08-08 | Structural code editing by voice |
| [dictation-toolbox/dragonfly](https://github.com/dictation-toolbox/dragonfly) | 416 | 2026-08-07 | Python scripting framework for speech grammars |
| [dictation-toolbox/Caster](https://github.com/dictation-toolbox/Caster) | 358 | 2026-05-16 | Voice programming toolkit on Dragonfly |
| **MSKazemi/yazses** | **10** | — | This project, created 2026-06-22 |

**The uncomfortable number is the first row.** Handy is 18 months old, does roughly what
YazSes's core does, and has ~3,000× the stars. Two honest readings, and both are true:
this space has real demand, and visibility here is not won by having more features.

## What each does that YazSes does not

### Handy — the packaging lesson

Handy is a *desktop application*. YazSes is a **daemon with a CLI**, which is a more
capable shape and a much higher barrier: a user who wants dictation must meet a service, a
config file and a terminal before they meet the product.

**Worth taking:** nothing architectural — the daemon is right, and it is what makes
`transcribe`, Meeting Mode and remote dictation possible at all. What is worth taking is
the *reading* of it: the settings window and the tray exist precisely to close this gap,
and they are the highest-leverage surfaces this project has. That is an argument for
finishing them well, not for becoming an app.

**Worth noting for [ADR-018](../adr/adr-018-feature-packs-and-the-plugin-question.md):**
Handy's README calls itself "extensible", and what that means there is *fork it and
contribute* — a community model, not a third-party plugin runtime. The most successful
project in this neighbourhood does not ship a plugin system either.

### Cursorless — the idea most worth stealing

Cursorless gives spoken names to *structural* targets — "take funk air", "chuck arg
bat" — so you edit the syntax tree rather than the character stream. It is the single
most interesting idea in this list, and it maps directly onto a problem already named:
**A2, that speaking is serial and correction is word-level when thought is not.**

**Gate check** (from [the direction triage](../../docs/research/directions.md)):
names a problem ✅ · runs on a laptop ✅ · measurable ✅ (task time on a scripted edit).
**It passes all three.** YazSes already has the unwired pieces — `hatselect` is exactly
this idea, and `jump` plus the Neovim LSP bridge are the substrate.

**The honest caveat:** Cursorless is an editor extension with the syntax tree in hand.
YazSes is outside the editor looking in, and only the Neovim bridge gives it structure
today. The transferable part is the *naming scheme*, not the implementation.

### nerd-dictation — the restraint lesson

1,914 stars for a single Python file over VOSK, with no daemon, no GUI and no features
beyond "speak, get text, run my script". It has more stars than every voice-programming
framework in this table.

**Worth taking:** the reminder that the 144-capability registry is not what attracts
people. nerd-dictation's proposition is *"you can read all of it in an afternoon"*, and
this project's equivalent asset — **one person can still understand the whole pipeline** —
is already claimed on the research page and should be defended rather than diluted.

### Dragonfly and Caster — the ecosystem that did not scale

Both are mature, both are Windows-centric, and both depend on a commercial recogniser
(Dragon) that is discontinued. They are the cautionary tale for
[ADR-018's plug-in decision](../adr/adr-018-feature-packs-and-the-plugin-question.md) from
the other direction: a rich third-party grammar ecosystem grew, and then the engine
underneath it went away and took the ecosystem with it. Offline and self-contained is not
only a privacy property; it is a survival property.

### insanely-fast-whisper — a benchmark, not a competitor

Throughput-optimised batch transcription on a GPU. Different problem (bulk, server) from a
different constraint (latency on a CPU). Listed because it is frequently cited as a
comparison and is not one — but it *is* a legitimate external baseline for
[gap 10](../../docs/research/framework-gaps.md) if the hardware caveat is stated.

## Candidate directions this produced

Feeding into the direction page:

| Idea | From | Gates | Verdict |
|---|---|---|---|
| **Structural targets by voice** — spoken names for syntax-tree nodes, not characters | Cursorless | 3/3 | **Buildable now**, on the Neovim bridge. `hatselect` is the unwired stub. |
| Editor-side extension so structure is always available | Cursorless | fails "runs on a laptop offline" only in scope, not in kind | Defer — a second product surface, not a feature |
| A single-file "just dictate" entry point | nerd-dictation | 3/3, but | **Already exists** as `yazses` + the daemon; the gap is onboarding, which the settings window addresses |
| GPU batch mode | insanely-fast-whisper | fails the laptop gate | Not pursued — use it as a *baseline* instead |

## What this exercise says about the project

Nothing in this list is an idea YazSes lacks. `hatselect`, `jump`, the LSP bridge and the
grammar layer are all present, designed and tested. **Cursorless's advantage is not the
idea; it is that theirs is wired to a syntax tree and reachable by a user.**

That is the same finding as [#164](https://github.com/MSKazemi/yazses/issues/164) and the
62 unwired capabilities, arrived at from outside instead of inside. Mining the
neighbourhood for ideas produced one idea worth having and a much stronger reason to
finish the ones already here.
