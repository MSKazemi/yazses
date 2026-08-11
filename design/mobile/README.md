# Mobile programme — internal pointer

**The mobile design lives in the public tree, not here.**

Canonical location: `docs/mobile/` (published on the docs site), with the ten binding ADRs
in `docs/mobile/adr/adr-mob-001..010`.

## Why this series is public when `design/` is not

The three-tier rule keeps internal rationale out of `docs/`. The mobile programme is the
deliberate exception, for one reason: **the Android app is being built by contributors, and
an architecture they cannot read is an architecture they cannot implement.** The ADRs' whole
job here is to stop a volunteer from re-litigating a decision in a PR review — which only
works if the volunteer can read them.

Nothing in the mobile series is commercially or personally sensitive; it is architecture for
an Apache-2.0 app. The desktop `adr-*` / `adr-v2-*` series stays internal as before.

## Where things are

| Content | Path |
|---|---|
| Programme overview, milestones M0–M4 | `docs/mobile/index.md` |
| ADRs MOB-001..010 | `docs/mobile/adr/` |
| Android architecture (module map, pipeline, testing) | `docs/mobile/architecture.md` |
| The cross-platform contract spec | `docs/mobile/contract.md` |
| Desktop → Android portability matrix | `docs/mobile/portability.md` |
| Mobile Working Group contribution model | `docs/mobile/contributing.md` |
| Contributor landing page in the code tree | `android/README.md` |

Keep genuinely internal mobile notes (cost estimates, store-account details, signing-key
handling procedures, unreleased positioning) in this directory instead of in `docs/`.
