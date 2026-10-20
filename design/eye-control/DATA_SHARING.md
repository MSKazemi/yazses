# Eye / camera testing — data sharing, privacy and research consent

**Audience:** testers, contributors, maintainers and future paper authors.

The key rule:

> **A public GitHub hardware report is engineering QA. It is not automatically consent to be a
> participant in a research paper.**

This separation lets people help YazSes without accidentally enrolling themselves in a study.

## What YazSes asks community testers to share

The default community report should contain only information needed to reproduce an engineering
result:

- YazSes version/commit;
- OS/version/session/compositor;
- broad CPU/RAM/architecture provenance;
- camera model/category without serial number;
- display count/resolution/scaling;
- feature/config values relevant to the test;
- counts/timings/errors from the scripted test;
- whether the test passed/failed/was blocked;
- optional comments about recovery/usability.

### Never required in a public issue

Do **not** post:

- face photo/video;
- screenshots containing private content;
- raw webcam frames;
- raw face mesh / eye images;
- biometric identity templates;
- full gaze trajectory over private desktop activity;
- microphone recordings;
- dictated/private text;
- diagnosis or medical history;
- home/work address;
- email/phone;
- hostname;
- hardware serial number;
- access tokens/logs containing secrets.

A tester may say "glasses: yes/no" or give approximate viewing distance/lighting when relevant, but
those are optional and should never be treated as identity or health data.

## GitHub issues are public

A tester must be told **before posting**:

- the issue and GitHub username are public;
- search engines, mirrors, forks and archives may preserve public content;
- therefore sensitive information should never be posted in the first place;
- deleting/editing later cannot guarantee deletion from third-party copies.

The project's report template repeats this warning.

## Four data classes

### Class A — automated/non-human engineering data

Examples:
- CI results;
- synthetic traces;
- dependency install result;
- OS build;
- fake portal protocol result.

May be archived and published with provenance.

### Class B — community QA result

A person runs a script/fixture on their machine and posts derived metrics.

Default purpose:
**engineering validation only**.

It may be summarized internally for bug/support prioritization, but is not automatically included as
participant-level evidence in a paper.

### Class C — research participant data

Collected under a named research protocol after the participant receives the required information and
gives valid consent/authorization under the applicable institutional/legal process.

This is the source for human-performance paper claims.

### Class D — sensitive/raw sensor data

Raw face video/images, detailed facial landmarks, identifiable audio, private screen content.

**Default programme policy: do not collect it centrally.**

If a future research question genuinely requires any Class D data, it needs a separate risk/ethics
decision, protocol, storage/retention plan and explicit consent. It is not covered by ordinary
eye-control testing.

## Community QA and future research

A tester can choose one of these positions:

1. **QA only.** Use my public report to fix/validate the software; do not treat it as research
   participant data.
2. **Contact me separately about research.** The public report remains QA-only; research consent
   happens separately before any research collection/use.
3. **Already enrolled under protocol X.** The public issue may link to a non-identifying protocol/run
   identifier, but the consent record remains private.

Do **not** implement a GitHub checkbox saying "I consent to this paper" as a substitute for a proper
research consent process.

## If data may support a paper

Before collecting human-participant data intended for publication:

1. identify the responsible research institution/team;
2. determine the applicable ethics/IRB/review requirement **before recruitment**;
3. freeze the protocol, measures and analysis plan;
4. tell participants what data is collected;
5. tell them the purposes, including publication/research;
6. tell them what will be public vs private;
7. tell them retention period;
8. explain withdrawal and its limits;
9. minimize collection;
10. keep identity/contact/consent records separate from measurement data.

ACM's current publication policy expects human-participant research to follow the applicable ethics
requirements of the authors' research environment and for authors to be able to explain that context.
EU Commission guidance for consent likewise emphasizes that consent should be freely given,
specific, informed and unambiguous and should explain purposes/data use.

References:
- https://www.acm.org/publications/policies/research-involving-human-participants-and-subjects
- https://commission.europa.eu/law/law-topic/data-protection/information-individuals_en
- https://commission.europa.eu/law/law-topic/data-protection/information-business-and-organisations/principles-gdpr_en

This document is an engineering/research-process rule, not legal advice; the responsible research
institution must make the actual determination.

## Participant-facing minimum information

A research consent/information sheet for eye-control should plainly state:

- **Purpose:** what question is being studied.
- **Tasks:** what the participant will do and approximate duration.
- **Sensors:** camera use is local; whether any raw video is recorded (default: no).
- **Collected data:** exact derived metrics and optional questionnaire answers.
- **Not collected:** raw frames, private desktop content, diagnosis, etc., unless separately stated.
- **Risks/discomfort:** possible fatigue/frustration/false pointer actions; participant may pause/stop.
- **Benefits:** no guaranteed personal benefit.
- **Voluntary:** participation is optional; stopping does not affect contribution/status.
- **Storage/access:** where measurement data is kept and who can access it.
- **Publication:** aggregates may appear in papers; whether de-identified row-level data may be
  released.
- **Quotes:** separate optional permission for anonymous verbatim comments.
- **Withdrawal:** how to request withdrawal and the cutoff/limits once aggregates or public releases
  are finalized.
- **Contact:** responsible researcher/institution.

## Research data release policy

Preferred public artifact:
- analysis code;
- protocol;
- task fixtures;
- aggregate tables;
- de-identified derived event/trial data only when permitted.

Avoid releasing:
- consent forms;
- names/contact info;
- GitHub usernames;
- raw camera frames;
- face landmarks that are not necessary for reproducibility;
- private text/screens.

## Withdrawal

For research data:
- maintain a private mapping from participant/contact to random participant ID only if needed;
- on valid withdrawal before the stated cutoff, remove that participant's unreleased research rows
  from future analysis/releases where required by the protocol;
- preserve an audit marker that the row was withdrawn without keeping the removed measurement in the
  analysis dataset.

For a **public GitHub QA issue**, the project can stop using the report for research/analysis, but
cannot promise that public content disappeared from third-party GitHub mirrors/archives. This is why
sensitive content must never be requested there.

## Authorship is separate

Running a test or participating in a study does **not automatically make someone a paper author**.
Authorship follows the publication's contribution/accountability criteria.

Community/test contributions should still be acknowledged/credited through the project's contributor
and publication-credit processes where appropriate, but participation, data consent and authorship
must remain separate decisions.



## Public GitHub forms are always community QA

The repository's eye/camera issue forms are deliberately one-way:

- a public no-code/hardware form produces `community_qa`;
- it requires a linked READY validation/measurement issue;
- it may ask whether the tester is willing to be contacted separately about future research;
- it never turns the submitted issue itself into `research` data.

If someone is already enrolled under a research protocol, their participant/session measurements use
that protocol's approved private/de-identified collection path. A public GitHub issue may separately
summarize a non-sensitive engineering finding only when appropriate, but that summary is still
`community_qa`.

This avoids a dangerous ambiguity where a public issue could contain both an identifiable GitHub
account and what appears to be a participant research record.
