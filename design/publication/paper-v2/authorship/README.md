# YazSes paper v2 — authorship, consent, and publication approval protocol

**Status:** proposed operating policy for the second YazSes paper  
**Applies to:** the paper-v2 manuscript and its planned Internet Archive publication  
**Policy owner:** project maintainer / delegated publication coordinator  
**Core rule:** the paper is not publishable until every contributor in the frozen candidate roster has explicitly agreed to authorship and every confirmed author has explicitly approved the exact final manuscript.

This directory turns that rule into a reproducible process. It is intentionally stricter than the minimum practice used by many projects: a missing response is not treated as consent, a contributor is not silently removed to make the byline easier, and a final approval is tied to an immutable manuscript fingerprint.

## 1. The three gates

### Gate 1 — freeze the contributor roster and collect author metadata

Goal: establish exactly who must be invited and collect the information needed to form a valid byline.

1. Choose an AUTHORSHIP_CUTOFF_SHA on main. It should be the code/evidence commit that the manuscript describes.
2. Regenerate the contributor set from both .all-contributorsrc and CONTRIBUTORS.md at that commit.
3. Reconcile any discrepancy manually before outreach.
4. Record the total N. The current seed roster contains 29 people as of 2026-09-23; see CANDIDATE_AUTHOR_ROSTER.md.
5. Contact every candidate.
6. Collect privately:
   - preferred publication name;
   - GitHub handle;
   - contact email;
   - whether that email may appear in the published paper;
   - affiliation exactly as the person wants it printed, or “Independent” / no affiliation if they prefer;
   - ORCID, optional;
   - CRediT contribution roles;
   - funding/conflict disclosure relevant to the paper;
   - accessibility or format needs for manuscript review, optional;
   - explicit yes/no authorship decision.
7. Never scrape a private email address and never infer a legal name, affiliation, or ORCID. Ask the contributor.
8. Never commit private contact emails or raw private consent messages to this public repository unless the contributor explicitly asks for them to be public.

**Gate 1 passes only when N of N candidates have given an explicit authorship YES and all required metadata is complete.**

Under the policy requested for this manuscript:

- YES -> candidate becomes a confirmed author.
- NO -> publication is blocked.
- no response -> publication is blocked.
- ambiguous response -> publication is blocked until clarified.
- YES but required author metadata is incomplete -> publication remains blocked.

There is no automatic timeout that converts silence into consent, and there is no automatic “move this person to acknowledgements” escape hatch.

### Gate 2 — collaborative manuscript review

Goal: let every confirmed author inspect and change the scientific text before final approval.

1. Draft the manuscript in the paper-v2 branch.
2. Keep claim-to-artifact traceability from the existing research package.
3. Send every confirmed author the same review version and the same review instructions.
4. Invite comments on:
   - title and abstract;
   - scientific claims and limitations;
   - methods and reproducibility language;
   - figures and tables;
   - byline spelling;
   - author order;
   - affiliations and ORCIDs;
   - CRediT statement;
   - acknowledgements;
   - funding and conflicts;
   - data/code availability;
   - license and publication venue metadata.
5. Track every requested change to resolution. Do not mark a comment resolved merely because an editor disagrees; record the resolution and communicate it.
6. If a new contributor is added to the project and the manuscript/evidence advances to include that contribution, reopen Gate 1, update N, and invite the new person.
7. Do not ask for “final approval” while substantive edits are still expected.

Gate 2 is complete when all author comments have either been incorporated or explicitly resolved and no author has an outstanding change request.

### Gate 3 — freeze one exact manuscript and obtain unanimous final approval

Goal: prove that every author approved the exact text that will be published.

1. Freeze the manuscript source at one Git commit.
2. Generate the final PDF outside the repository. The repository rules prohibit committing PDFs.
3. Compute SHA-256 for the exact PDF distributed for approval.
4. Freeze the exact:
   - title;
   - ordered author list;
   - author spellings;
   - affiliations;
   - corresponding-author designation;
   - abstract;
   - main text;
   - figures/tables/captions;
   - CRediT statement;
   - acknowledgements;
   - funding/conflict statements;
   - references;
   - license statement.
5. Create a final-approval manifest containing the source commit and PDF SHA-256.
6. Send the final approval request in COMMUNICATION_TEMPLATES.md to every author.
7. Accept only an unambiguous APPROVE response tied to that fingerprint.
8. If anyone requests a change, returns WITHDRAW, or does not respond, publication is blocked.
9. If any approved manuscript content changes after approval, generate a new fingerprint and restart final approval for every author.

**Gate 3 passes only when N of N confirmed authors approve the same frozen commit and PDF hash.**

Only after Gate 3 passes may the Internet Archive upload begin.

## 2. Non-negotiable invariants

1. **Silence is never consent.**
2. **No person is put on the public byline without explicit opt-in.**
3. **No final author is removed merely to make the approval count reach 100%.**
4. **The project does not publish this paper if the frozen contributor roster is not unanimous under this policy.**
5. **An approval belongs to one exact manuscript fingerprint, not to “the paper in general.”**
6. **Any content or byline change after the final freeze invalidates all prior final approvals.**
7. **A contributor may withdraw consent at any time before publication. A withdrawal blocks publication immediately.**
8. **Refusing authorship does not affect a person's software credit, contribution history, license rights, project standing, or ability to contribute later.**
9. **Raw private email addresses and private consent messages stay off the public Git repository unless the person explicitly authorizes publication of them.**
10. **Author order and CRediT roles must describe reality. Do not state “equal contribution” unless the authors actually agree that it is true.**

## 3. Candidate author versus confirmed author

A contributor is a **candidate author** because the project has chosen to invite every contributor on the frozen roster.

A candidate becomes a **confirmed author** only after they:

- explicitly opt in;
- provide a preferred publication name;
- identify at least one truthful contribution role;
- agree to review the manuscript;
- accept responsibility for their own contribution and for raising concerns they notice in the manuscript;
- agree that publication requires their final approval of the frozen text.

No GitHub entry, merged PR, or prior software credit is itself permission to put someone's name on a scholarly paper.

## 4. Authorship contribution model

Use the CRediT taxonomy as the vocabulary for contribution statements where it fits. Likely roles in this project include:

- Conceptualization
- Methodology
- Software
- Validation
- Formal analysis
- Investigation
- Data curation
- Writing — original draft
- Writing — review & editing
- Visualization
- Resources
- Project administration

Translation, field testing, bug reporting, design review, accessibility review, and platform validation should be mapped honestly to the closest applicable role(s) and described in prose when CRediT alone is too coarse.

The project policy is inclusive with respect to contribution type: code is not privileged over testing, documentation, translation, research/design review, or field evidence. The final contribution statement should still be specific enough that a reader can understand what each author contributed.

## 5. Author order

Author order is part of the material that requires explicit agreement.

Recommended default proposal for discussion:

1. corresponding / coordinating author first;
2. remaining confirmed authors alphabetically by preferred publication family name.

This is only a default proposal, not an automatic rule. If the group chooses another ordering principle, document it and obtain explicit agreement from all authors before final freeze.

Do not imply equal contribution merely because the byline is long.

## 6. Private registry

Maintain one private registry outside the public repository. It may be a private spreadsheet, encrypted file, or access-controlled document.

Minimum columns:

~~~text
candidate_id
github_handle
preferred_publication_name
contact_email_private
email_may_be_public
affiliation_public
orcid_public
credit_roles
funding_or_conflict_disclosure
authorship_decision
authorship_consent_received_at
authorship_consent_evidence_ref
draft_review_state
outstanding_change_request
final_approval_state
approved_source_commit
approved_pdf_sha256
final_approval_received_at
final_approval_evidence_ref
withdrawn
notes
~~~

The evidence reference may be a private email message ID, private document reference, or public GitHub comment URL if the contributor intentionally gave consent in public.

Do not store passwords, account secrets, unnecessary personal data, home addresses, phone numbers, or identity documents.

## 7. Public repository artifacts

The public repository should contain process and publication-safe metadata only.

Before consent:
- this protocol;
- candidate roster built from already-public contributor data;
- communication templates;
- approval protocol;
- publication checklist.

After unanimous Gate 1 consent:
- a public author metadata file may be created containing only fields authors agreed to publish, such as name, affiliation, ORCID, GitHub handle, and CRediT roles.

After unanimous Gate 3 approval:
- the final approval manifest may record aggregate readiness and the frozen manuscript fingerprint.
- Do not publish private response text unless every affected author explicitly agrees.

## 8. Reminder cadence

A suggested non-coercive cadence:

- Day 0: initial invitation.
- Day 7: friendly reminder.
- Day 14: second reminder.
- Day 21: final status note explaining that the manuscript remains blocked without an explicit answer.

A deadline is an organizational aid only. It never converts silence to consent.

If a candidate remains unreachable, the result under this paper's policy is **blocked publication**, not presumed consent.

## 9. Change control after an approval

The following require a new freeze and unanimous re-approval:

- any author added, removed, renamed, or reordered;
- title or abstract changes;
- any scientific text change;
- any number, table, figure, caption, result, limitation, conclusion, or reference change;
- CRediT changes;
- affiliation changes;
- funding/conflict changes;
- license changes.

Purely mechanical Internet Archive identifiers assigned by the platform after upload do not change the manuscript. Everything supplied by the project in the upload metadata must match the approved package.

## 10. Publication readiness formula

Let:

- N = number of people in the frozen candidate roster;
- C = number with explicit authorship consent;
- M = number with complete required metadata;
- A = number who approved the final frozen fingerprint;
- R = number with unresolved requested changes;
- W = number who withdrew or declined.

Publication is allowed only when:

~~~text
roster_is_frozen
AND C == N
AND M == N
AND A == N
AND R == 0
AND W == 0
AND manuscript_has_not_changed_since_approval
~~~

Anything else is NOT READY.

## 11. Roles for operating the process

### Publication coordinator
- freezes and reconciles the candidate roster;
- sends invitations/reminders;
- keeps the private registry;
- verifies consent evidence;
- never changes a person's metadata without their confirmation.

### Manuscript editor
- integrates review changes;
- keeps unresolved comments visible;
- announces any change after freeze;
- creates the final source commit.

### Evidence steward
- checks every central result against repository artifacts;
- confirms the manuscript uses the agreed evidence freeze;
- prevents later code/results changes from silently entering the paper.

### Corresponding author / uploader
- may prepare the Internet Archive item only after the gate is green;
- uploads exactly the approved files;
- verifies creator order and metadata after upload;
- records the final archive identifier in the repository.

One person may hold several of these roles, but the checks remain separate.

## 12. Files in this package

- CANDIDATE_AUTHOR_ROSTER.md — current 29-person seed roster derived from public project contributor data.
- COMMUNICATION_TEMPLATES.md — ready-to-send invitation, consent, review, reminder, final-approval, withdrawal, and publication messages.
- APPROVAL_PROTOCOL.md — state machine, immutable fingerprint, approval record format, and audit rules.
- ARCHIVE_ORG_PUBLICATION_CHECKLIST.md — preflight, upload, verification, and post-publication checks.
- RUNBOOK.md — step-by-step operating sequence from roster freeze through corrections.
- PRIVATE_REGISTRY_TEMPLATE.csv — headers for the private registry; copy it outside the repository before adding any real data.
- FINAL_APPROVAL_MANIFEST.template.yml — publication-safe immutable fingerprint and aggregate approval manifest.
- PUBLIC_STATUS_TEMPLATE.md — aggregate public progress reporting without exposing individual consent records.

## 13. Definition of done

This authorship process is complete only when:

- the candidate roster is frozen against a named source commit;
- every candidate has explicitly opted in;
- every author has complete verified publication metadata;
- author order and CRediT statement are agreed;
- all manuscript review comments are resolved;
- one exact final source commit and PDF hash are frozen;
- every author explicitly approves that fingerprint;
- the Internet Archive upload matches the approved package;
- the archive identifier and citation metadata are recorded back in the repository.

If any one of these is false, the paper is not ready to publish.
