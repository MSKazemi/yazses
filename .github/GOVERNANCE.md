# Governance

How decisions get made in YazSes, who makes them, and how you get a say. This is
deliberately lightweight — the project is small and the goal is that a contributor
never has to guess who can say yes.

---

## Roles

| Role | What it means | How you get it |
|---|---|---|
| **Visitor** | You use YazSes, join a Discussion, report what happened, or ask a question. No repository permission is needed. | Show up |
| **Contributor** | You opened an issue or PR, reviewed a translation, tested hardware, or otherwise contributed useful evidence. | Do it |
| **Regular contributor** | You have contributed repeatedly and shown that you understand the project's review, privacy, and scope rules. You can review bounded L0/L1 work and help triage newcomers; this is recognition, not automatic write access. | Usually after roughly three meaningful contributions, including at least one merged PR. There is no hard counter: ask, or a maintainer may invite you |
| **Module steward** | You own a module's *internal* design: you review its PRs, and your call decides how it works inside the boundaries its ADRs set. | Ship two non-trivial PRs to that module, review well, then ask on the issue or the relevant epic |
| **Maintainer** | Architecture, ADRs, releases, signing keys, L3 review, and the final call when consensus does not appear. | See *Growing the maintainer group* |
| **Core team** | The active maintainers and active module stewards, as a public shorthand for the people carrying ongoing project responsibility. It is not a separate permission tier. | Automatic while active in one of those roles |

Stewards are recorded in [`.github/CODEOWNERS`](CODEOWNERS), which also makes
GitHub request their review automatically. Adding yourself there is part of the PR
that makes you a steward.

Stewardship **lapses quietly after 30 days without substantive project activity**. This is
not a penalty: the purpose is to keep review ownership and CODEOWNERS aligned with people
who are currently available. The role can be restored when someone returns and becomes
active again. Announcing a break is always welcome.

**Current maintainer:** [@MSKazemi](https://github.com/MSKazemi)
(Mohsen Seyedkazemi Ardebili).

## Promotion path

The normal path is:

`Visitor → Contributor → Regular contributor → Module steward → Maintainer`

The **Core team** is not another rung after maintainer; it is the active maintainers and
module stewards viewed as one group.

Promotion is about **trust and judgement, not collecting commits**. Code, documentation,
translation review, hardware testing, issue triage, reproductions and thoughtful PR review
all count when they are useful to the project.

### Regular contributors

Regular contributor is deliberately a responsibility step before repository write access.
A regular contributor may:

- review and approve **L0/L1** work described in [`REVIEWING.md`](../REVIEWING.md) when
  they can personally verify it;
- help triage issues and point newcomers at a well-scoped task;
- review translations, documentation, hardware reports and other areas where human
  judgement matters;
- draft or perform reviews without being responsible for merging the change.

A maintainer still performs the merge unless repository permissions have been delegated
separately. Roughly three meaningful contributions is a useful signal, not a rule: one
excellent sustained contribution can matter more than several mechanical ones.

### Module stewards

A module steward has bounded ownership. After two non-trivial contributions to an area and
evidence of good review judgement, they can be added to [`.github/CODEOWNERS`](CODEOWNERS).
Within that area they may review and approve **L0-L2** work, unless the change escalates to
L3 because it touches privacy, dependencies, permissions, public interfaces, release paths,
accepted ADRs or other protected boundaries.

### Active-role review

Delegated roles are **active responsibilities, not permanent titles**. They are reviewed
continuously and may be narrowed, paused or removed when that is safer for the project.

- **Inactivity:** after **30 days without substantive project activity**, an active steward
  role lapses and any associated CODEOWNERS or delegated repository permission may be
  removed. Returning contributors can regain the role after becoming active again.
- **Review quality:** repeated inaccurate approvals, repeated failure to follow the review
  lanes, or repeatedly approving work the reviewer could not verify can lead to a narrower
  role or loss of review authority. A single ordinary mistake should normally lead to
  feedback, not removal.
- **Project boundaries:** bypassing privacy, permission, dependency, security or ADR
  boundaries can cause an immediate pause of delegated authority while the change is
  reviewed.
- **Conduct or permission misuse:** repository permissions may be removed immediately when
  needed to protect contributors, users or the repository. Public explanations should be
  given when appropriate; security and Code-of-Conduct matters may need to remain private.

Reducing a role does not erase past credit. `CONTRIBUTORS.md` records work that happened;
CODEOWNERS and repository permissions record who is responsible **now**.

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
[mobile ADRs](../docs/mobile/adr/README.md) are the worked example.

**What is protected on `main`.** Rulesets block force-pushes and deletion of
`main` and of every `v*` release tag, so published history and the commits that
release artifacts were built from cannot be rewritten. Pull requests and passing
checks are deliberately *not* required to merge: with one maintainer, requiring
review would mean self-approval theatre, and requiring status checks would block
direct pushes rather than only merges. That is a trade made knowingly, and it is
the first thing to revisit when there is a second maintainer.

## Things that are not up for negotiation in a PR

These are settled by [ADR-011](../docs/privacy-statement.md) and its mobile
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
not a permanent state. A future maintainer will normally have been a module steward
who has stayed active over time, consistently reviewed other people's work well,
handled disagreement constructively, understood the privacy and ADR boundaries, and
helped carry project work beyond their own patches (for example triage, releases or
cross-module review).

There is no election, quota or required PR count. Maintainer access is an invitation,
and the bar is trust and judgement rather than commit count.

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
