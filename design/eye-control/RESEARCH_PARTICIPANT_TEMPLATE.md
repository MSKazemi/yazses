# Template — eye-control research participant information and consent

> **DO NOT USE THIS TEMPLATE FOR RECRUITMENT AS-IS.**
>
> The responsible research team must complete the placeholders, obtain the applicable
> institutional/local ethics determination, and have the final document approved where required
> **before collecting publication-intended human-participant data**.

Protocol ID/version: `<PROTOCOL-ID / VERSION>`  
Responsible institution: `<INSTITUTION>`  
Principal/responsible researcher: `<NAME / ROLE>`  
Ethics/review determination: `<APPROVAL/EXEMPTION/NOT-REQUIRED CONTEXT + REFERENCE>`  
Private contact for questions/withdrawal: `<CONTACT>`  
Data retention period: `<RETENTION>`  
Study software commit/release: `<COMMIT>`

## Plain-language invitation

You are invited to take part in a study of hands-free computer interaction using YazSes. The study
examines how reliably a normal computer camera can support coarse gaze targeting, head-driven pointer
movement and/or deliberate facial gestures used as switches.

Taking part is voluntary.

Choosing not to participate, or stopping early, does not affect your ability to use YazSes, report
bugs, contribute code, or participate in the open-source community.

## What you will do

You will complete the following tasks:

`<LIST EXACT TASKS>`

Expected duration:

`<DURATION>`

You may pause or stop at any time.

The study must provide a stop/pause method that does not depend on accurately controlling the
experimental pointer.

## Sensors used

The study may use:

- your computer's camera for local face/eye/head inference;
- normal keyboard/mouse only for setup or comparison when the protocol says so;
- `<OTHER SENSOR, IF ANY>`.

### Raw camera policy

Default YazSes eye-control research policy:

**raw camera video/images are processed locally and are NOT uploaded or retained by the research
dataset.**

If this particular study intends to record/store raw video or images, replace the sentence above
with an explicit explanation of:
- exactly what is recorded;
- why it is necessary;
- where it is stored;
- who can access it;
- retention/deletion;
- whether it is shared;
- the separate consent required.

A study that records raw face data is outside the normal eye-control community-testing protocol.

## Data we plan to collect

Complete this list before recruitment.

### Machine/environment

Possible fields:
- YazSes version/commit;
- operating system/version/session;
- broad computer/CPU/RAM class;
- camera model/category without serial number;
- display resolution/scaling/topology;
- configured feature settings;
- lighting category;
- approximate viewing distance;
- glasses yes/no/prefer-not-to-say when scientifically relevant.

### Task measurements

Depending on the protocol:
- target attempts;
- correct/wrong/fallback gaze outcomes;
- calibration error/drift;
- pointer target completion/movement time/misses;
- accidental clicks;
- intended/missed/false face-switch activations;
- activation latency;
- task completion time;
- recovery/fallback counts;
- tracking-loss events.

### Optional questionnaire

`<LIST EXACT ITEMS/SCALE>`

Do not add new questionnaire items after data collection starts without versioning/amending the
protocol.

## Data we do NOT collect under this protocol

Unless explicitly amended and consented, we do not collect:

- raw face photos/video;
- raw private screen recordings;
- raw private dictated text;
- microphone recordings;
- diagnosis/medical records;
- precise home/work location;
- hardware serial numbers;
- passwords/tokens;
- GitHub username in the analysis dataset.

## Participant identity

Your measurements will use a random participant identifier such as `P023`.

The file connecting your identity/contact information to that identifier, if one is needed, is kept
separately from the measurement dataset and is not published.

## Possible discomfort or risk

Possible experiences include:
- frustration when tracking fails;
- unintended pointer movement/clicks;
- eye/head/neck fatigue from repeated control;
- temporary discomfort from holding a deliberate facial gesture;
- privacy concern associated with camera use.

You may pause, recalibrate, switch modality or stop.

The study must use non-sensitive demo content so an unintended click does not cause a real-world
destructive action.

## Benefits

There is no guaranteed direct personal benefit.

The results may improve the reliability and accessibility of YazSes and may contribute to research on
privacy-local hands-free interaction.

## What will be public?

Complete before recruitment:

- aggregate results in papers/reports: `<YES/NO + DESCRIPTION>`;
- de-identified trial-level dataset: `<YES/NO + DESCRIPTION>`;
- analysis code/protocol: `<YES/NO>`;
- anonymous quotes: `<SEPARATE OPTIONAL CONSENT>`.

Raw consent/contact records are never published.

## Data sharing choice

The final study should offer clear choices such as:

- I agree that my de-identified measurements may be analyzed for this study.
- I agree / do not agree that de-identified derived trial-level data may be released publicly.
- I agree / do not agree that anonymous verbatim comments may be quoted.

Do not bundle optional public release or quotation into one mandatory checkbox unless the research
ethics determination explicitly supports that design.

## Withdrawal

Before recruitment, define:
- how the participant requests withdrawal;
- the withdrawal deadline/cutoff;
- what can still be removed;
- what cannot reasonably be withdrawn after aggregate/publication/release.

Suggested policy shape:

> If you withdraw before `<CUTOFF>`, the research team will remove your unreleased measurement rows
> from future analysis and releases where required by the protocol. Once anonymous aggregate results
> have been published, it may not be possible to remove your contribution from those already
> published aggregate statistics. Public GitHub QA posts are outside this research dataset and may
> also persist in third-party archives.

The responsible institution must approve the actual wording.

## Compensation

`<COMPENSATION OR "NONE">`

Compensation, if any, must not depend on successful feature performance.

## Questions / concerns

Research contact:

`<CONTACT>`

Independent ethics/participant-rights contact where required:

`<CONTACT>`

## Consent record

The final approved consent mechanism should record that the participant:

- received and understood the study information;
- had the opportunity to ask questions;
- understands participation is voluntary;
- understands the camera/raw-data policy;
- understands what derived data is collected;
- understands publication/data-sharing choices;
- understands withdrawal;
- agrees to participate.

**Do not store signed/name-bearing consent records in the public GitHub repository.**

## Publication references for maintainers

Before submission, re-check the target venue's current policies.

- ACM policy on research involving human participants:
  https://www.acm.org/publications/policies/research-involving-human-participants-and-subjects
- European Commission information on valid consent:
  https://commission.europa.eu/law/law-topic/data-protection/information-individuals_en
- GDPR processing principles / data minimisation:
  https://commission.europa.eu/law/law-topic/data-protection/information-business-and-organisations/principles-gdpr_en

This template is a project process aid, not legal advice.
