# Milestone policy — delivery, epics and evergreen issues

**Status:** Maintainer policy, decided under [#480](https://github.com/MSKazemi/yazses/issues/480)
(parent epic [#377](https://github.com/MSKazemi/yazses/issues/377)).
**Enforced by:** `scripts/milestone_policy.py`, offline, on an issue snapshot.

A GitHub milestone in this repository is an **outcome**: something a release can finish,
with a progress bar that can reach 100%. Not every open issue is work of that shape. A call
for compatibility reports, a translation review queue or an open research question is never
"done" in the way an outcome is, and putting it in a milestone holds that outcome's progress
below 100% for ever. So the rule is not "every open issue has a milestone". It is:

> **Every open issue is in exactly one class, chosen by its labels. The class says whether
> it carries a milestone. Nothing falls through.**

This is option B of #480 (*typed exceptions*), with the exception carried in a label rather
than inferred from the title.

## The three classes

| Class | Marked by | Milestone | Example |
|---|---|---|---|
| **Delivery** | no class label (the default) | **exactly one**, and it must be open | a bug, a feature, a bounded docs task, a validation slot |
| **Epic** | the `epic` label | **derived** from its sub-issues (below) | #81 Android, #377 traceability |
| **Evergreen** | exactly one `evergreen:<class>` label | **none** | a "test it on your distro" call |

Delivery is the default on purpose. An issue nobody classified is treated as work that owes a
milestone, so forgetting a label produces a violation, not a silent exemption.

### Evergreen classes

The set is closed. A new class is a change to this page *and* to `EVERGREEN_CLASSES` in
`scripts/milestone_policy.py`; a test fails if the two disagree.

| Label | What belongs there |
|---|---|
| `evergreen:research` | An open research question with no delivery outcome of its own — the public research agenda (#251–#258). A *bounded* study inside a programme (a protocol to freeze, a matrix to run) is delivery work in that programme's milestone. |
| `evergreen:field-report` | An open-ended call for compatibility or measurement reports from many people: the per-distro "test YazSes and report" issues, the "Measure it" collectors. A fixed validation *slot* with an acceptance role (the eye-control `EYE-QA-*` slots) is delivery work. |
| `evergreen:translation` | A translation or native-speaker review queue that stays open for volunteers. A bounded localization task (change these 24 pages) is delivery work. |
| `evergreen:community` | A contributor hub, a stewardship invitation, an outreach call. |

Topical labels such as `research`, `measurement-wanted` or `documentation` say what an issue
is *about*; they never exempt it. Only an `evergreen:*` label does, so adding a topic label to
a bug cannot quietly take it out of a milestone.

### Epics and their children

An epic coordinates sub-issues, and **the sub-issues carry the delivery milestones**. The
epic's own milestone follows from them:

- if every open delivery sub-issue sits in the same milestone, the epic carries that one;
- if they span several milestones, the epic carries **none** — it is a programme, not an
  outcome (Android #81 has open sub-issues in all four milestones M0–M3);
- children are linked as **GitHub sub-issues**, not as a list in the epic's body: prose cannot
  be checked, and a policy that cannot be checked drifts.

An epic is never also evergreen: one class per issue.

## Answering the four questions in #480

1. **Is this issue expected to have a milestone?** Delivery: yes, exactly one. Evergreen: no.
   Epic: whatever its open sub-issues share, or none if they span outcomes.
2. **If yes, which outcome owns it?** The milestone it carries. A delivery issue with no
   fitting outcome is a signal that an outcome is missing, not that the issue is exempt —
   propose the milestone.
3. **If no, what exempts it?** Its single `evergreen:<class>` label, or the `epic` label
   together with sub-issues that span milestones.
4. **Can an issue fall through both?** No. With no class label it is delivery and needs a
   milestone; with an unknown or a second class label it is a violation.

## What is checked

`scripts/milestone_policy.py` reads an open-issue snapshot (`gh issue list --json` output or
the REST issues payload) and an optional milestone listing, and reports:

| Rule | Fires when |
|---|---|
| `DELIVERY_WITHOUT_MILESTONE` | a delivery issue has no milestone |
| `EVERGREEN_WITH_MILESTONE` | an evergreen issue carries one |
| `UNKNOWN_EVERGREEN_CLASS` | an `evergreen:*` label names no defined class |
| `CONFLICTING_CLASSES` | an issue carries more than one class label |
| `MILESTONE_UNKNOWN` / `MILESTONE_CLOSED` | the milestone is missing from the listing, or closed (only with a listing) |
| `EPIC_SPANS_MILESTONES` | an epic carries a milestone that some open delivery child does not |
| `EPIC_MILESTONE_MISSING` | an epic has none although all its open delivery children share one |

Epic rules need parent links in the snapshot (a `parent` field per issue). Without them the
report says so and lists each epic as *unverified*; it never reports them as passing.

```sh
gh issue list --state open --limit 1000 --json number,title,labels,milestone > issues.json
gh api repos/MSKazemi/yazses/milestones -X GET -f state=all --paginate > milestones.json
uv run python scripts/milestone_policy.py issues.json --milestones milestones.json
# or, together with the manifest check:
uv run python scripts/check-traceability.py --issues issues.json --milestones milestones.json
```

Exit codes: `0` no violation, `1` violations, `2` an input could not be read. The unit tests
(`tests/test_milestone_policy.py`) run on fixtures and stay offline; fetching live state is
the job of the scheduled live audit (#487).

### In the scheduled live audit

`scripts/check-traceability-live.py` (workflow `.github/workflows/traceability.yml`) applies
this policy to the issue listing it already fetches, through the same
`scripts/milestone_policy.py`, so there is one classifier and no extra API request:

- `epic` and `evergreen:<class>` issues are not reported as `UNMILESTONED_UNCLASSIFIED`; an
  unlabelled, topic-labelled or invalid-class issue without a milestone still is. That drift
  rule *is* `DELIVERY_WITHOUT_MILESTONE`, reported once under the audit's name.
- Every other rule above appears in its own "Milestone policy (#480)" section of the job
  summary and under `milestone_policy` in the `traceability-live` JSON artifact.
- Epic milestones are derived from the listing's sub-issue links (`parent_issue_url`); an epic
  with no open sub-issue there is listed as unverified.

**Advisory, by decision.** In the live audit these findings never change the exit code. That
exit code means "`design/traceability.yml` no longer matches GitHub" (or GitHub could not be
read), and a policy violation is a different fact: an unlabelled new issue would otherwise
turn the manifest audit red every night. To gate on the policy, run
`scripts/milestone_policy.py` (exit `1` on any violation) where a red result is wanted.

## Why not an "Evergreen" milestone

The other way to make every issue carry a milestone is a catch-all bucket milestone. It was
rejected: a milestone that can never close is the thing this policy exists to avoid, its
progress bar would mean nothing, and it would make question 1 always "yes" without making
question 2 any easier to answer.
