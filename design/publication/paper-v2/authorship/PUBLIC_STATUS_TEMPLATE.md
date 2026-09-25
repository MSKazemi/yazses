# YazSes paper v2 — public publication status template

This file is a template for a publication-safe status update. Copy the structure into a GitHub issue/PR comment or a public status file only when useful.

Do **not** list individual authorship decisions, private email addresses, private message excerpts, or evidence IDs here.

## Snapshot

- Authorship cutoff commit: `<sha>`
- Candidate roster size (N): `<N>`
- Aggregate workflow state: `ROSTER_OPEN | AUTHORSHIP_BLOCKED | AUTHORSHIP_COMPLETE | REVIEW_IN_PROGRESS | REVIEW_BLOCKED | READY_TO_FREEZE | FINAL_APPROVAL_IN_PROGRESS | FINAL_APPROVAL_BLOCKED | APPROVED_FOR_PUBLICATION | PUBLISHED`
- Last updated: `<ISO-8601>`

## Aggregate gate status

| Gate | Requirement | Current | Pass? |
|---|---|---:|---|
| Candidate consent | N/N explicit YES | <C>/<N> | no |
| Required metadata | N/N complete | <M>/<N> | no |
| Draft review | N/N complete | <D>/<N> | no |
| Open requested changes | 0 | <R> | no |
| Final approval | N/N same fingerprint | <A>/<N> | no |
| Declined | 0 | <count> | no |
| Unreachable | 0 | <count> | no |
| Withdrawn | 0 | <count> | no |

## Final fingerprint

Populate only after freeze:

- Source commit: `<sha>`
- PDF SHA-256: `<sha256>`
- Public author-roster digest: `<sha256>`
- Approval round: `<round>`

## Publication

Populate only after unanimous approval:

- Authorized for upload: `yes/no`
- Internet Archive identifier: `<identifier>`
- Published at: `<date>`

## Privacy rule

This public snapshot proves aggregate process state. It is not the evidence store.

Per-person answers, contact information, and raw consent/approval messages remain private unless the person deliberately made them public.
