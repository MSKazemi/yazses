# ADR-021 — The one thing to invest in: carry the cost of an error through the pipeline

**Status:** Accepted (2026-08-15)
**Deciders:** Mohsen Seyedkazemi Ardebili
**Context links:** the problem space §A1, [where YazSes goes next](../../docs/research/directions.md),
[[adr-019-egress-inventory-and-escalation]], issue
[#164](https://github.com/MSKazemi/yazses/issues/164)

---

## Context

The question: of everything on the table, which single direction deserves sustained
investment? Four candidates survived the direction triage. This scores them and picks one.

## The scoring

Five criteria. **Evidence** and **already-started** carry the most weight, because this
project's failure mode is not a shortage of good ideas — it is 64 designed capabilities
nobody can reach.

| | Error cost | Hands-free mode | Composition | Structural targets |
|---|:---:|:---:|:---:|:---:|
| **User pain** — how bad when it goes wrong | **5** — unrecoverable | 5 — blocks the task entirely | 3 — annoying, not costly | 3 |
| **Novelty** — is anyone else doing it | **5** — cost-weighted error rate is unpublished | 2 — Talon does this | 3 | 2 — Cursorless does this |
| **Evidence** — do we know the problem is real | **5** — three shipped features are point fixes for it | 2 — no user has been observed | **5** — 62% re-dictation (TOCHI 2020) | 3 |
| **Cost** — inverse of effort | **4** — the pieces exist | 1 — integration + a study | 2 | 1 — needs an editor's syntax tree |
| **Demonstrable in 30 s** | **5** — "watch it refuse to type `rm -rf`" | 4 — needs a person | 2 | 4 |
| **Total** | **24** | 14 | 15 | 13 |

### Why error cost wins on more than arithmetic

**It is the only candidate the codebase has already voted for three times.** The command
safety gate, staged dictation and the no-text-target guard were each built separately, at
different times, for different symptoms — and all three are the same idea: *this token is
about to go somewhere the consequence of being wrong is high.* Naming the general case
turns three special cases into one mechanism.

**It produces something publishable.** Word error rate weights every word equally, and the
user never has. **Cost-weighted error rate** — errors scored by the consequence of where
the token lands rather than counted — is not a metric anyone publishes. That is a research
contribution and a product improvement from the same work, which is exactly what
[gap 3](../../docs/research/framework-gaps.md) says this project needs.

**It is the differentiator that survives contact with a better-funded competitor.** A
neighbouring project has 29,533 stars for doing the core well. Competing on recognition
quality is competing on someone else's budget. *Refusing to be confidently wrong in
expensive places* is a different axis, and it is one a privacy-first, local-first tool is
unusually well placed to occupy — it can see the destination, which a cloud API cannot.

### Why the others lose, briefly

- **Hands-free mode** scores highest on human stakes and lowest on evidence: nobody has
  been observed using it. That is not a reason to abandon it — it is a reason to run
  [agenda question 6](../../docs/research/agenda.md) first. Investment follows evidence.
- **Composition** has the best evidence of any candidate (62% of real corrections are
  re-dictations) and no cheap first move. It is the natural *second* investment.
- **Structural targets** is the best idea in the neighbourhood and needs a syntax tree
  YazSes does not own outside Neovim.

## Decision

**Invest in carrying error cost through the pipeline.** Concretely, in order:

1. **Extend the principle to destinations beyond the shell.** The safety gate knows shell
   patterns; the same reasoning applies wherever a mis-heard token is expensive and
   *checkable*. First: **numbers with check digits** — card numbers, IBANs, ISBNs, national
   IDs. `checkdigit/validate.py` already implements Luhn, ISBN-10/13 and Verhoeff plus
   single-edit fix suggestion, and has never had a caller. **This ADR ships that wiring.**
2. **Unify the three confirmation policies.** `cmdsafety`, `staged` and `target_guard` are
   three configs and three mechanisms for one decision. Merging them is a refactor with no
   user-visible change, so it comes *after* the user-visible wins, not before.
3. **Define and measure cost-weighted error rate.** Needs the run manifest and
   deterministic replay from gaps 1–2 to be worth reporting.

**What this is not.** It is not a promise to build all three. Step 1 ships with this ADR;
steps 2 and 3 are the direction, and each needs its own decision when reached.

## Consequences

**Good.** Every future "should we build this?" in this area has an answer: does it stop a
confident wrong token reaching an expensive destination? A `recommended`-tier capability
becomes reachable, and #164's count drops by one more.

**Accepted cost.** A guard that holds text is a guard that can hold text you wanted. The
mitigation is the one the command gate already uses: hold only on a *specific, checkable*
signal, never on a heuristic, and make the release one word.

**The risk worth naming.** The failure mode of this whole direction is becoming an app that
asks "are you sure?" too often, at which point users learn to confirm reflexively and the
guard is worse than nothing. Every step must therefore be judged on **how rarely it fires**,
not on how much it catches — a check-digit test fires only on digits that fail arithmetic,
which is why it is the right first step.
