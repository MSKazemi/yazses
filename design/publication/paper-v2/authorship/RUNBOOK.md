# Operational runbook — YazSes paper v2 authorship and publication

This runbook turns the policy documents in this directory into a concrete sequence of actions.

It intentionally separates **public GitHub state** from **private author-contact state**. Public Git should show the process and aggregate readiness. Individual email addresses, private messages, and private consent evidence stay in the private registry.

## Phase 0 — prepare the process

- [ ] Merge/review the authorship governance package.
- [ ] Name the publication coordinator.
- [ ] Name the manuscript editor.
- [ ] Name the evidence steward.
- [ ] Decide where the private registry will live.
- [ ] Copy PRIVATE_REGISTRY_TEMPLATE.csv to that private location.
- [ ] Do not fill the private registry inside this public repository.
- [ ] Create a secure backup of the private registry.
- [ ] Confirm that access is limited to people operating the publication process.

Exit condition: roles and private storage are ready.

## Phase 1 — freeze the candidate roster

1. Choose the intended authorship/evidence cutoff commit on main.
2. Read .all-contributorsrc at that commit.
3. Read CONTRIBUTORS.md at that commit.
4. Compare the two contributor sets.
5. Check merged PRs since the last roster snapshot for contributors not yet reflected in either file.
6. Check for renamed GitHub accounts and aliases.
7. Do not infer that two similar names are the same person.
8. Produce the final candidate roster count N.
9. Record the cutoff SHA and roster digest in the private registry and public status record.

Current seed snapshot, not yet the final freeze:

- main commit: 247913a5f7cdf4a48035ac77aa4f179144b89c33
- seed date: 2026-09-23
- seed count: 29
- source: .all-contributorsrc + CONTRIBUTORS.md
- note: the all-contributors badge text may lag the actual array count; count contributor records, not the badge string.

Exit condition: the roster is frozen and every candidate has one private registry row.

## Phase 2 — obtain explicit authorship decisions

For each candidate:

1. Send the public GitHub contact message only if needed to establish a private contact route.
2. Do not post a private email address in a public issue.
3. Send the private authorship invitation.
4. Record invitation date and evidence reference.
5. If YES:
   - collect the author information form;
   - verify preferred name;
   - verify affiliation;
   - verify public-email preference;
   - collect ORCID if offered;
   - collect CRediT roles;
   - collect funding/conflict disclosure;
   - mark CONSENTED only after the consent statement is explicit.
6. If QUESTION:
   - answer the question;
   - keep the state QUESTION_PENDING until an explicit decision follows.
7. If NO:
   - mark DECLINED;
   - acknowledge respectfully;
   - set aggregate publication state to AUTHORSHIP_BLOCKED.
8. If there is no answer:
   - send reminders at the protocol cadence;
   - never convert silence to consent;
   - mark UNREACHABLE only after the outreach round is exhausted;
   - publication remains blocked.

Exit condition under this manuscript policy: every candidate is CONSENTED and every required metadata field is complete.

## Phase 3 — construct the proposed author list

- [ ] Normalize each confirmed author's preferred name exactly as supplied.
- [ ] Normalize affiliations exactly as supplied.
- [ ] Include ORCID only when supplied and intended for publication.
- [ ] Build the CRediT statement from confirmed roles.
- [ ] Prepare the proposed author order.
- [ ] Send author-order proposal to every confirmed author.
- [ ] Resolve objections before manuscript freeze.
- [ ] Do not state equal contribution unless all affected authors explicitly agree and the statement is true.
- [ ] Prepare the public author metadata file only from fields authors agreed may be public.

Exit condition: every confirmed author has agreed to their own metadata, contribution statement, and the proposed byline order.

## Phase 4 — manuscript review round

- [ ] Freeze a review draft commit.
- [ ] Give every author the same draft identifier.
- [ ] Send the draft-review template.
- [ ] Track NO CHANGES REQUESTED, CHANGES REQUESTED, and QUESTION states privately.
- [ ] Log every requested change.
- [ ] Resolve each request and send the resolution back to the requesting author.
- [ ] Keep the request open until the author agrees that it is resolved.
- [ ] If a requested change alters another author's contribution statement or attribution, explicitly ask that affected author to verify it.
- [ ] Do not start final approval with unresolved comments.

Exit condition: every author is RESOLVED or NO_CHANGES_REQUESTED; outstanding requests = 0.

## Phase 5 — freeze the final manuscript

The manuscript editor:

1. chooses the final source commit;
2. generates the PDF outside the repository;
3. calculates SHA-256 of the exact PDF;
4. generates the final public author metadata;
5. computes the roster digest;
6. fills FINAL_APPROVAL_MANIFEST.template.yml;
7. independently re-hashes the PDF;
8. verifies that the PDF corresponds to the frozen source commit;
9. changes no content after the fingerprint is created.

Before sending final approval, verify:

- [ ] title frozen;
- [ ] abstract frozen;
- [ ] author names/order frozen;
- [ ] affiliations frozen;
- [ ] CRediT frozen;
- [ ] acknowledgements frozen;
- [ ] funding/conflicts frozen;
- [ ] all result values frozen;
- [ ] figures/tables frozen;
- [ ] references frozen;
- [ ] license text frozen;
- [ ] source commit recorded;
- [ ] PDF SHA-256 recorded;
- [ ] author-roster digest recorded.

Exit condition: one immutable final fingerprint exists.

## Phase 6 — unanimous final approval

For every author:

1. send the exact same final approval package;
2. require the preferred reply:
   `APPROVE YAZSES-V2 <pdf-sha256>`;
3. record response time and evidence reference;
4. accept no approval for another hash;
5. accept no approval from an earlier draft;
6. accept no conditional approval while the condition is unresolved.

If any author requests a change:

1. stop the round;
2. make the requested change only after resolving it;
3. create a new source commit;
4. generate a new PDF;
5. calculate a new hash;
6. increment approval_round;
7. mark all earlier approvals INVALIDATED_BY_NEW_VERSION;
8. send the new final package to every author.

If any author withdraws:
- stop publication;
- mark WITHDRAWN;
- acknowledge the decision;
- do not remove the author merely to make the gate pass.

Exit condition:

~~~text
consented == N
metadata_complete == N
final_approved == N
unresolved_changes == 0
declined == 0
withdrawn == 0
unreachable == 0
all_approvals_reference_same_hash == true
~~~

## Phase 7 — Internet Archive publication

Follow ARCHIVE_ORG_PUBLICATION_CHECKLIST.md.

Before upload:

- [ ] recalculate PDF SHA-256;
- [ ] compare it to the approved hash;
- [ ] verify title and author order;
- [ ] verify public email choices;
- [ ] inspect every uploaded file for private material;
- [ ] ensure the private registry is not in the upload package.

After upload:

- [ ] verify landing-page title;
- [ ] verify creator order;
- [ ] verify license;
- [ ] verify the project-supplied original;
- [ ] record the archive identifier;
- [ ] record the publication date;
- [ ] send the publication-completed message to every author;
- [ ] update repository citation/publication metadata without erasing the first paper incorrectly.

## Phase 8 — corrections after publication

A scientific, byline, affiliation, contribution, figure, table, or manuscript-text correction is a new version.

- [ ] create corrected source commit;
- [ ] create corrected PDF;
- [ ] calculate new hash;
- [ ] document the change;
- [ ] repeat unanimous final approval;
- [ ] publish a versioned correction;
- [ ] preserve the previous archive record;
- [ ] notify all authors.

## Daily/weekly operating discipline

During outreach/review, the coordinator should keep a private aggregate dashboard:

~~~text
N candidates:
Invited:
Questions pending:
Consented:
Declined:
Unreachable:
Metadata complete:
Draft review complete:
Open manuscript requests:
Final approval requested:
Final approved:
Withdrawn:
Aggregate state:
~~~

Only aggregate values need to be copied to a public status comment if desired.

## Stop conditions

Stop the publication workflow immediately when:

- roster reconciliation is unresolved;
- an authorship decision is NO;
- a candidate cannot be reached;
- an author withdraws;
- an author disputes their name, affiliation, role, order, or scientific content;
- a requested manuscript change is unresolved;
- the final source/PDF fingerprint changes;
- the PDF being uploaded does not match the approved hash;
- private contact/consent material is found in a public artifact.

The workflow resumes only after the blocking condition is actually resolved.
