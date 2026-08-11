# Reviewing YazSes contributions

For people reviewing someone else's pull request. If you are sending one, you want
[`CONTRIBUTING.md`](CONTRIBUTING.md); if you want to know who decides what,
[`GOVERNANCE.md`](GOVERNANCE.md).

**Honest state:** there is currently one maintainer. This file exists so that reviewing
does not require being that person — it is written to be handed to someone on their first
review, not to describe a team that already exists.

## The only rule that matters

**A contributor should never be worse off for having contributed.** Someone who spent an
evening on a task and gets a terse "needs work" learns not to come back. If a PR is wrong
because the *task* was wrong, that is ours to fix and you should say so plainly. If it is
90% right, it is usually faster and kinder to merge it and follow up than to send it back.

## What you can approve

`risk` comes from the task in [`campaign/tasks.json`](campaign/README.md) and decides who
reviews, not how hard the work is.

| Lane | Typical | You are checking | Time |
|---|---|---|---|
| **L0** | A compatibility record, a microphone row, a semantic vector | Is the evidence plausible and non-duplicate? Is anything personal in the diff? | ~4 min |
| **L1** | An app config, a translated section, a troubleshooting page | Does it match reality? Do the commands work? | ~7 min |
| **L2** | Wiring a capability, a regression test | Tests present and meaningful, no new dependency, nothing enabled by default | ~15 min |
| **L3** | Privacy, IPC, dependencies, public interfaces, release path | Maintainer only, plus an ADR where the decision is new | 30 min+ |

Automation has already checked scope, personal data, sign-off, lint and tests before you
open the page. You are not re-running CI. You are judging the things a machine cannot:
**is this true, and is it useful.**

Promote to L3 and stop if a PR touches anything that could send audio or text off the
machine, microphone permissions, shell execution, dependency or lockfile changes, a public
interface or accepted ADR, or the default enabled/disabled state of a feature — regardless
of what lane the task claimed.

## What a machine may never decide

- Whether a translation reads naturally to a native speaker.
- Whether hardware behaved the way a report claims.
- Whether an architectural change is right.

If you cannot personally judge one of these, say so and hand it on. "I can't verify this,
passing to someone who speaks Tamil" is a complete and useful review.

## Review responses

Adapt these; do not paste them verbatim into a first-time contributor's PR.

**Approving**

> This satisfies the task and the evidence is clear. Thank you — your \[specific thing]
> fills \[specific gap]. Approving.

**One thing missing**

> This is in scope and close. One acceptance criterion is still open: \[criterion].
> Could you \[exact action]? Nothing else needs to change.

**The task was wrong, not the PR**

> You followed the task as written; the problem is in our instructions. I have corrected
> the task and will help adapt this. This is not a failed contribution on your side.

**Someone got there first**

> Another PR reached this exact environment first — that is our scheduling failure, not
> yours. Your work is still useful as independent verification if \[difference], or I can
> reserve \[alternative] for you. No pressure either way.

## Things not to do on a first PR

- Drive-by style opinions unrelated to the task. Open a separate issue if it matters.
- Asking for a refactor the task did not ask for.
- Silence. A holding comment beats an unanswered PR; the queue being long is not the
  contributor's fault and they cannot see it.
- Approving something you did not understand, to be nice. Say you are unsure instead.

## Becoming a reviewer

There is a real path and it does not start with permissions:

1. **Apprentice** — draft a review on two open PRs in a lane you know; a maintainer
   checks it before it posts. No access needed.
2. **Reviewer** — approve L0/L1 in one lane.
3. **Captain** — calibrate other reviewers, take disputed calls, approve bounded L2.
4. **Module steward** — [`GOVERNANCE.md`](GOVERNANCE.md) already defines this: two
   non-trivial PRs to a module and it is yours to review.

Write access is not required for steps 1–2 and is not the reward; a maintainer merges what
you approve until the project's governance says otherwise.

## When to stop taking contributions

Pause promotion, publicly, if any of these is true — an overloaded queue harms
contributors more than a quiet week does:

- More than 25 PRs waiting on a human.
- Median first response over 48 hours.
- Reviewers spending more time than they volunteered.
- A task family producing files nothing reads.
