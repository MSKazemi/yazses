---
description: "How the YazSes Mobile Working Group builds the Android app together — a six to twelve month effort designed to be built by contributors who have never met."
---

# The YazSes Mobile Working Group — how we build this together

**Status:** open for contributors · **Last updated:** 2026-08-07
**Read first:** [`index.md`](index.md) (why + milestones), [`architecture.md`](architecture.md),
the root [`CONTRIBUTING.md`](https://github.com/MSKazemi/yazses/blob/main/.github/CONTRIBUTING.md)

The Android app is a 6–12 month effort that the maintainer cannot build alone while also
running the desktop line. So it is designed to be built by a group of people who have never
met, in evenings, on different phones. Everything below exists to make that work.

---

## 1. The deal

**What you get.** A well-specified module to own, an unambiguous definition of done, a
reviewer who responds within a few days, credit in `CONTRIBUTORS.md` and the release notes,
and — for module stewards — a real say in the architecture of your area.

**What we ask.** Claim before you build, keep PRs small, write the tests, say when you get
stuck or lose interest (that is *fine*, and saying so frees the issue for someone else).

**What we will not do.** Sit on your PR. Rewrite your work without telling you. Merge
something that quietly weakens the privacy posture — including our own.

## 2. What makes this contributable

Four properties, all of them deliberate design choices, not accidents:

1. **The definition of "correct" is a JSON file, not a person.** Shared logic is verified by
   `contract/vectors/*.json` (ADR-MOB-008). "Port the disfluency filter" means "make these
   60 cases pass". You do not need to read Python, guess at intent, or wait for a reviewer
   to tell you whether an edge case was meant to work that way.
2. **You do not need a device — or a microphone — for most of the work.** `:core:*` modules
   are pure-Kotlin JVM modules (ADR-MOB-002 §3): `./gradlew :core:postprocess:test` needs no
   emulator, no model, no phone. Audio fixtures live in `contract/audio/` for the parts that
   do need sound.
3. **Modules are independent by construction.** The module map in
   [`architecture.md`](architecture.md#3-module-map) has one-way dependencies
   and interface boundaries, so ten people can work at once without stepping on each other.
4. **The architecture is already decided and written down.** Ten ADRs mean you are not
   asked to invent policy in a PR review. If you think a decision is wrong, argue with the
   ADR — that is what it is for.

## 3. Roles

| Role | What it means | How you get it |
|---|---|---|
| **Contributor** | you took an issue, you shipped it | claim an issue |
| **Module steward** | you own a module's design within its ADRs: you review PRs to it, keep its docs true, and your call decides its internal design | ship two non-trivial PRs to that module and ask |
| **Device tester** | you run pre-release builds on hardware nobody else has and file device reports | say which phone you have on [the epic](https://github.com/MSKazemi/yazses/issues/81) |
| **Maintainer** | Mohsen — contract ownership, ADRs, release, signing keys, final call | — |

Stewardship is real delegation, bounded by the ADRs: a steward decides *how* `:feature:ime`
renders its key bar; a steward does not decide to add an `AccessibilityService` (that is
ADR-MOB-003, and changing it takes a new ADR).

Stewardship lapses quietly after ~3 months of silence — no drama, no hard feelings, and the
door stays open. Announcing a break is the polite version and is always welcome.

## 4. Claiming work

1. Find an issue with the `android` label. Sub-issues of [the epic (#81)](https://github.com/MSKazemi/yazses/issues/81) list their milestone,
   their prerequisites, and their acceptance criteria.
2. **Comment to claim it.** You get it unless someone already has it.
3. If you go quiet for two weeks with no PR, we will ask; after three, the issue is
   released. Nobody is annoyed — "I ran out of time" is a completely normal comment.
4. **Do not open a large unclaimed PR.** A 3,000-line surprise implementation of a module
   someone else is working on is the fastest way to waste both of your evenings.
5. Prefer to pair or scope first? Say so on the issue. A 20-minute scoping exchange
   routinely saves a weekend.

## 5. The contribution ladder

Start anywhere; these are ordered by how much context they need, not by how valuable they
are.

| Rung | Example task | Needs |
|---|---|---|
| 0 | Review an ADR and disagree with it in writing | opinions |
| 1 | Write the ugly edge cases for one contract vector unit | Python, an hour |
| 2 | Port one pure function to Kotlin until its vectors go green | Kotlin, JUnit |
| 3 | Build a Compose screen (model chooser, diagnostics, onboarding) | Compose |
| 4 | Own an Android service module (`:feature:ime`, `:feature:recognition`) | Android internals |
| 5 | JNI + CMake for a native engine, or the F-Droid build recipe | NDK, patience |
| 6 | Design something new → write the ADR → build it | all of the above |

Non-code contributions that are genuinely wanted: device reports, onboarding copy that
survives contact with a suspicious user, screenshots, translations, accessibility testing
with TalkBack and with a switch device, and testing on old/cheap phones — the devices the
maintainer does not own are exactly where this will break.

## 6. The review bar

A PR is merged when:

- [ ] the contract vectors for anything it touches are green;
- [ ] new logic has tests, and they run on the JVM if the code is in `:core:*`;
- [ ] no new manifest permission, no new network dependency, no analytics — or, if there
      genuinely must be, the ADR-MOB-007 permission table is updated in the same PR and the
      change is argued for;
- [ ] no `android.*` import crept into a `:core:*` module;
- [ ] new features are **off by default** (project-wide rule, mobile included);
- [ ] user-visible strings are honest — no capability announced before it works;
- [ ] the PR body says *why*, not just *what*.

We would rather merge a small imperfect PR and polish it afterwards than leave you waiting.
That is the same promise the root CONTRIBUTING makes, and it holds here.

## 7. Working in the open

- **Design questions** → [the epic (#81)](https://github.com/MSKazemi/yazses/issues/81), or a Discussion. Anything that changes an ADR
  needs an ADR PR (copy the house style of the existing `adr-mob-*` files: Context,
  Decision, Consequences, Rejected — and "Rejected" is not optional; it is where most of
  the value is).
- **Implementation questions** → the sub-issue you claimed.
- **"Is this a bug or is my phone weird?"** → an issue with a device report.
- No private roadmap, no side channel where the real decisions happen. If a decision gets
  made in a DM, it gets written back to the issue.

## 8. Using an AI assistant

Fine and expected — the same rules as the rest of the project apply, plus one that matters
more on mobile: **an LLM will confidently produce Android code that violates ADR-MOB-007**
(adding Firebase, adding `INTERNET` to the app module, adding an `AccessibilityService`
because that is what most tutorials do) and will invent framework behaviour that changed
three API levels ago. Read every line, run the gates locally, and point your assistant at
`AGENTS.md` plus the mobile ADRs before it starts. Say in the PR body if a change was
largely AI-generated; it changes how carefully we review, never whether we accept it.

## 9. Recognition

Every merged PR gets its author into `CONTRIBUTORS.md` (all-contributors, non-code
contributions included) and named in the release notes. Module stewards are listed in
`android/README.md`. This is a portfolio-grade project to have your name on: an offline,
privacy-first speech stack that people actually use.

## 10. Where the first ten issues are

[The epic, #81](https://github.com/MSKazemi/yazses/issues/81), carries the full work breakdown and is the current state of play.
The M0 tasks (#82, #83) are Python-only and can start today; the Gradle skeleton (#84)
unblocks all of M1. Not sure where to start? [#98](https://github.com/MSKazemi/yazses/issues/98)
asks you to read the ADRs and tell us what is wrong with them — no code, no device.
