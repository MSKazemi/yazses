# Final approval protocol — YazSes paper v2

This document defines the operational state machine for authorship consent, manuscript review, immutable final approval, and publication authorization.

## 1. State model

Each candidate has one authorship state:

- INVITED
- QUESTION_PENDING
- CONSENTED
- DECLINED
- UNREACHABLE
- WITHDRAWN

Each confirmed author has one manuscript-review state:

- NOT_SENT
- REVIEW_SENT
- CHANGES_REQUESTED
- RESOLVED
- NO_CHANGES_REQUESTED

Each confirmed author has one final-approval state:

- NOT_REQUESTED
- REQUESTED
- APPROVED
- CHANGES_REQUESTED
- WITHDRAWN
- INVALIDATED_BY_NEW_VERSION

The publication has one aggregate state:

- ROSTER_OPEN
- AUTHORSHIP_BLOCKED
- AUTHORSHIP_COMPLETE
- REVIEW_IN_PROGRESS
- REVIEW_BLOCKED
- READY_TO_FREEZE
- FINAL_APPROVAL_IN_PROGRESS
- FINAL_APPROVAL_BLOCKED
- APPROVED_FOR_PUBLICATION
- PUBLISHED
- SUPERSEDED

## 2. Allowed transitions

### Candidate authorship

~~~text
INVITED -> QUESTION_PENDING
INVITED -> CONSENTED
INVITED -> DECLINED
INVITED -> UNREACHABLE

QUESTION_PENDING -> CONSENTED
QUESTION_PENDING -> DECLINED
QUESTION_PENDING -> UNREACHABLE

CONSENTED -> WITHDRAWN
~~~

UNREACHABLE is not consent. DECLINED, WITHDRAWN, and UNREACHABLE all block publication under the all-contributors policy.

### Draft review

~~~text
NOT_SENT -> REVIEW_SENT
REVIEW_SENT -> NO_CHANGES_REQUESTED
REVIEW_SENT -> CHANGES_REQUESTED
CHANGES_REQUESTED -> RESOLVED
RESOLVED -> CHANGES_REQUESTED
RESOLVED -> NO_CHANGES_REQUESTED
~~~

Final freeze is permitted only when every confirmed author is either RESOLVED or NO_CHANGES_REQUESTED and there are zero outstanding change requests.

### Final approval

~~~text
NOT_REQUESTED -> REQUESTED
REQUESTED -> APPROVED
REQUESTED -> CHANGES_REQUESTED
REQUESTED -> WITHDRAWN

APPROVED -> INVALIDATED_BY_NEW_VERSION
CHANGES_REQUESTED -> INVALIDATED_BY_NEW_VERSION
~~~

Any material manuscript change creates a new version and sets every existing approval to INVALIDATED_BY_NEW_VERSION.

## 3. Freeze procedure

The editor creates a final freeze only after Gate 2 is complete.

Record:

- manuscript title;
- full ordered author list;
- author-count N;
- source Git commit SHA;
- repository URL;
- evidence cutoff SHA/tag;
- PDF filename;
- PDF SHA-256;
- source archive filename/hash if one is distributed;
- final author metadata digest;
- date/time created;
- person creating the freeze.

Recommended manifest structure:

~~~yaml
protocol_version: 1
paper: yazses-v2
status: awaiting-final-approval
title: "..."
source_commit: "40-hex-sha"
evidence_cutoff: "40-hex-sha-or-tag"
pdf:
  filename: "yazses-paper-v2-final.pdf"
  sha256: "64-hex"
author_roster:
  count: 28
  digest_sha256: "64-hex"
approval_round: 1
created_at: "ISO-8601"
~~~

The public repository may contain this manifest once it contains no private email addresses or private message excerpts.

## 4. Author-roster digest

Create the roster digest from a normalized public-author record for each confirmed author, in final byline order.

Recommended normalized line:

~~~text
position|preferred_name|affiliation|orcid_or_blank|github_handle|credit_roles
~~~

Join records with LF, UTF-8 encode, and calculate SHA-256.

This prevents a byline or affiliation change from being mistaken for the same final version.

## 5. What counts as explicit final approval

A valid approval must:

1. come from the author or a communication channel already verified as theirs;
2. contain unambiguous approval language;
3. identify the exact final fingerprint, preferably the PDF SHA-256;
4. arrive after the approval request for that fingerprint;
5. not have been superseded by a later requested change or withdrawal.

Preferred reply:

~~~text
APPROVE YAZSES-V2 <pdf-sha256>
~~~

Do not count:
- an emoji reaction alone;
- “looks good” from an earlier draft round;
- approval of a different hash;
- silence;
- a third party speaking for the author;
- an approval sent before the final freeze;
- a conditional approval whose condition is unresolved.

## 6. Evidence storage

Maintain the private approval evidence register outside public Git.

For each author record:

~~~text
author_id
approval_round
source_commit
pdf_sha256
request_sent_at
response_received_at
response_channel
evidence_reference
approval_state
notes
~~~

Evidence_reference should point to the original communication, such as an email message ID, private document record, or public GitHub comment URL.

Do not transcribe more private message content than is necessary to establish the state.

## 7. Approval verification pass

Before declaring APPROVED_FOR_PUBLICATION, one coordinator should run this checklist independently from the manuscript editor where practical:

- [ ] frozen roster N matches the final byline N;
- [ ] every candidate is CONSENTED;
- [ ] no candidate is DECLINED, UNREACHABLE, or WITHDRAWN;
- [ ] all required metadata is complete;
- [ ] author order is the agreed order;
- [ ] all draft review requests are resolved;
- [ ] final source commit exists;
- [ ] final PDF hash independently recalculates to the recorded value;
- [ ] every author approved this exact hash;
- [ ] every approval arrived after this approval round was issued;
- [ ] no later withdrawal or requested change exists;
- [ ] manuscript files have not changed since the approvals;
- [ ] intended Internet Archive metadata matches the approved title/byline/license package.

Only then change aggregate status to APPROVED_FOR_PUBLICATION.

## 8. Reapproval triggers

Restart unanimous final approval whenever any of the following changes:

- title;
- subtitle;
- author list;
- author order;
- spelling of an author name;
- affiliation;
- corresponding-author designation;
- abstract;
- body text;
- figures;
- tables;
- captions;
- equations;
- result values;
- references;
- appendices/supplement that form part of the publication package;
- acknowledgements;
- funding;
- conflicts;
- CRediT statement;
- license statement.

A correction of an Internet Archive field that does not alter the approved manuscript may be handled as archive metadata maintenance, but the corrected metadata must still match what authors approved.

## 9. Withdrawal handling

Before publication, an author may withdraw consent.

When a withdrawal is received:

1. stop publication immediately;
2. mark the author WITHDRAWN;
3. mark aggregate status FINAL_APPROVAL_BLOCKED or AUTHORSHIP_BLOCKED;
4. acknowledge the withdrawal;
5. do not pressure the contributor to reverse it;
6. do not silently remove the person from the byline merely to preserve publication under this all-contributors policy;
7. keep their software/project contribution credit unchanged.

If the project later chooses a materially different authorship policy, that is a separate governance decision and must not be represented as satisfying this protocol.

## 10. After publication

After the Internet Archive item is live:

- record the identifier and landing-page URL;
- record the uploaded PDF SHA-256;
- verify the uploaded file hash where the service permits retrieval;
- verify title and creator order;
- add the archive identifier to the project citation/publication records as appropriate;
- send the publication-completed message to all authors.

A manuscript correction after publication becomes a new version. Prepare a corrected manuscript, create a new fingerprint, repeat unanimous approval, and publish/version it in a way that preserves the historical record.

## 11. Audit summary

A public audit summary may state:

- frozen roster count;
- number consented;
- number finally approved;
- source commit;
- PDF SHA-256;
- approval completion date;
- publication identifier.

Do not publish private emails, private message excerpts, or sensitive personal information as proof.

The audit goal is to prove the process state, not expose the communications.
