# Governance

How decisions get made in YazSes, who makes them, and how you get a say. This is
deliberately lightweight — the project is small and the goal is that a contributor
never has to guess who can say yes.

---

## Roles

| Role | What it means | How you get it |
|---|---|---|
| **Contributor** | You opened an issue or a PR. That is the whole bar. | Do it |
| **Module steward** | You own a module's *internal* design: you review its PRs, and your call decides how it works inside the boundaries its ADRs set. | Ship two non-trivial PRs to that module, then ask on the issue or the relevant epic |
| **Maintainer** | Architecture, ADRs, releases, signing keys, the final call when consensus does not appear. | Currently one person; see *Growing the maintainer group* |

Stewards are recorded in [`.github/CODEOWNERS`](.github/CODEOWNERS), which also makes
GitHub request their review automatically. Adding yourself there is part of the PR
that makes you a steward.

Stewardship **lapses quietly** after roughly three months of silence. No drama, no
hard feelings, and the door stays open — announcing a break is the polite version
and is always welcome.

**Current maintainer:** [@MSKazemi](https://github.com/MSKazemi)
(Mohsen Seyedkazemi Ardebili).

## How decisions get made

Most changes need no ceremony: open a PR, a steward or the maintainer reviews it,
it merges. The ladder only exists for the things that are expensive to undo.

| Kind of change | Process |
|---|---|
| Bug fix, test, doc, refactor inside a module | PR → review → merge |
| New feature | Discuss in [Ideas](https://github.com/MSKazemi/yazses/discussions/categories/ideas) first if it is user-visible, then PR. **Ships off by default.** |
| Change to a module's internal design | The steward decides, within the module's ADRs |
| Change that crosses modules, changes a public interface, or changes shared behaviour | **An ADR PR**, then implementation |
| Change to an *accepted* ADR | A **new ADR that supersedes it**. Accepted ADRs are not edited to say something different from what was decided |
| Anything touching privacy posture, permissions, or network access | ADR + maintainer approval, always. See below |

An ADR follows the house style: **Context, Decision, Consequences, Rejected**. The
*Rejected* section is not optional — it is where most of the long-term value is,
because it tells the next person which arguments have already been had. The public
[mobile ADRs](docs/mobile/adr/README.md) are the worked example.

## Things that are not up for negotiation in a PR

These are settled by [ADR-011](docs/privacy-statement.md) and its mobile
counterparts, and a PR that weakens one will be declined regardless of how good the
rest of it is:

- **No telemetry.** No analytics, no crash-reporting SDK, no phone-home, not even
  opt-in in the first instance.
- **Offline by default, and no silent cloud fallback.** When on-device inference
  fails the user gets an actionable error, not a quiet round trip to someone's API.
- **No ambient capture.** The microphone opens when a human holds something down or
  explicitly starts a session.
- **New features ship off by default.** An upgrade never changes behaviour the user
  did not ask for.
- **Honesty about what exists.** Nothing is described as working — in the README, the
  docs, a store listing or a release note — until it is wired and tested. The feature
  registry distinguishes *wired* from *planned* and refuses to pretend otherwise.

Several of these are enforced by CI rather than by review, on purpose.

## Disagreement

Argue in the open, on the issue or the ADR PR. "This is wrong because…" is welcome
and is the point of writing decisions down before building. If a discussion does not
converge, the maintainer decides and records **why** in the ADR — including the
argument that lost, so it can be revisited when the facts change.

If you think a decision aged badly, the mechanism is a superseding ADR, not a
re-litigation in someone else's PR review.

## Growing the maintainer group

The project currently has one maintainer, which is a single point of failure and
not a permanent state. Someone becomes a maintainer by having been a steward who
consistently reviewed well, exercised judgement in line with the principles above,
and stayed around. There is no election and no quota — it is an invitation, and the
bar is trust rather than commit count.

If the maintainer becomes unreachable for an extended period, the project is
Apache-2.0 and the community is free to fork; the maintainer would rather that
happen than have the work stall.

## Code of conduct

The [Code of Conduct](CODE_OF_CONDUCT.md) applies to every space this project uses,
and enforcement is the maintainer's responsibility. Report privately to
mohsen.seyedkazemi@gmail.com.

## Security

Vulnerabilities go through [private reporting](SECURITY.md) — never a public issue.

## Funding

The project takes no money and has no sponsor tier. If that changes it will be
announced, and it will never buy a decision: patches are judged on merit.
