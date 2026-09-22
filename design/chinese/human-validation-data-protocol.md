# Chinese support — human validation and data-handling protocol

**Status:** Proposed community QA protocol  
**Scope:** Native-language review, real-device validation, and optional speech-quality testing for Mandarin support.

This document keeps two activities separate:

1. **Product QA / contribution evidence** — a contributor proves that a feature works on their machine or that a Chinese phrase is natural.
2. **Human-subjects research / publication data** — results are collected systematically to answer a research question or support a paper.

A GitHub contribution is **not automatically consent for research or publication use**, and a tester should never have to upload their voice to help validate YazSes.

## 1. Default rule: local test, public result, no audio upload

The preferred validation workflow is:

```text
public fixed prompt / public command fixture
        ↓
tester speaks locally
        ↓
YazSes runs locally
        ↓
tester records only expected vs observed text + environment
        ↓
public PR/report contains no audio and no private dictated content
```

This is enough for most:

- injection checks;
- language switching;
- command phrase review;
- model/runtime smoke tests;
- platform compatibility;
- Simplified/Traditional output checks.

Voice recordings are biometric/sensitive personal data and must not be collected merely because they would be convenient.

## 2. Public QA report fields

A compatibility/acceptance report may contain:

### Required technical fields

- report/task ID;
- YazSes commit/version;
- OS and version;
- desktop/session where relevant (X11/Wayland/macOS/Windows);
- CPU architecture/model where performance matters;
- RAM amount where model fit matters;
- STT engine/model identifier;
- compute type/device;
- speech language setting;
- Han script setting;
- command-language setting if testing commands;
- test fixture/scenario ID;
- expected output;
- observed output;
- pass/fail;
- fallback used, if any;
- validation command/tool version where applicable.

### Optional language-review fields

Only when genuinely needed:

- reviewer states they are comfortable reviewing Simplified Chinese, Traditional Chinese, or Mandarin phrasing;
- preferred written script for the review;
- short free-text explanation of unnatural/ambiguous wording.

Do **not** require ethnicity, nationality, legal name, age, gender, home location, employer, or other demographic data for ordinary product QA.

Do not infer “native speaker” from location, username, name, or repository history. The reviewer may self-describe their language competence if they wish.

## 3. Never put these in a public compatibility report

- raw microphone/audio recordings;
- private dictated notes;
- clipboard contents beyond the fixed public fixture;
- home-directory paths;
- hostname;
- IP/network identifiers;
- email address unless the contributor deliberately uses it as public contact elsewhere;
- medical/legal/work content used in everyday dictation;
- API keys/tokens;
- full crash dumps that may contain user text;
- unrelated application/window titles if they expose private information.

The campaign preflight/privacy checks should reject obvious leaks, but the task contract must prevent them before submission.

## 4. Fixed public prompt set

For device/platform validation, prefer short fixed prompts committed to the repository. That gives comparable evidence without asking people to disclose their own speech content.

Suggested categories:

### Script

Simplified:

```text
你好，世界。简体中文测试 123，YazSes。
```

Traditional:

```text
你好，世界。繁體中文測試 123，YazSes。
```

### Mixed technical text

```text
今天 review PR #378，然后保存文件。
```

A native reviewer should approve the final prompt set before it becomes a test fixture. The mixed sentence is a stress fixture, not a claim of code-switch support.

### Commands

Use the reviewed command-vector corpus, not spontaneous private commands.

## 5. Native-language phrase review

This task usually needs **no microphone**.

Reviewer sees:

- semantic action;
- candidate Simplified phrase(s);
- candidate Traditional phrase(s);
- negative/prose examples.

Reviewer records:

- acceptable / unnatural / ambiguous;
- preferred phrase;
- whether the phrase could commonly occur as normal prose;
- whether wording differs materially between Simplified/Traditional usage.

The goal is command naturalness and false-positive safety, not a demographic survey.

## 6. Optional speech QA without uploading audio

A tester can run a local helper that computes metrics and emits only a report:

```text
fixture_id
model
decode_time
reference text (public fixture)
hypothesis text
CER components
environment
```

The helper should not persist audio after the test unless the tester explicitly chooses to keep their local copy.

If a fixed prompt is public, hypothesis/reference text is safe to publish because it contains no private content.

## 7. When audio collection is actually necessary

Examples:

- reproducing an acoustic/model failure that cannot be reproduced from text;
- building a controlled research evaluation;
- studying accents/noise conditions.

Then ordinary GitHub QA consent is insufficient.

Before collecting audio, define:

- purpose;
- exact fields/audio collected;
- who can access it;
- storage location;
- encryption/access control;
- retention period;
- deletion procedure;
- whether redistribution is allowed;
- whether model training is allowed;
- whether publication of derived/aggregate results is allowed;
- whether identifiable quotations/audio snippets may ever be published;
- withdrawal process where applicable.

Do not commit such audio to the public repository.

## 8. Separate research/publication consent

If the project intends to use volunteer test results in a paper, archive, dataset, model training, or systematic human-subject study:

1. define the research question and data protocol first;
2. obtain whatever ethics/institutional/legal review is applicable to the project/team;
3. give participants a separate research consent notice;
4. state whether their name/handle may appear in acknowledgments/authorship separately from data consent;
5. state whether raw audio is retained or shared;
6. state how withdrawal/deletion works for data that has not already been irreversibly aggregated/published;
7. do not retroactively treat historical GitHub QA submissions as research consent.

This design record is an engineering rule, not legal advice; the applicable institution/jurisdiction decides formal research requirements.

## 9. QA consent text for public task reports

A bounded compatibility/native-review task can display text like:

> This task publishes the report you submit in the YazSes repository. Do not include private speech, audio, clipboard contents, identifiers, or unrelated application data. By opening the contribution you are choosing to publish the report text/diff under the repository contribution terms. This does not grant YazSes permission to use a private voice recording for research, model training, or a publication dataset.

If no audio is requested, say so explicitly:

> **Do not upload audio for this task.**

## 10. Audio-request consent checklist

If a later issue truly requires audio, the task must not open until it can answer all of these:

- [ ] Why text-only evidence is insufficient.
- [ ] Is audio optional or required?
- [ ] Exact maximum duration/format.
- [ ] Where it is uploaded (not public Git).
- [ ] Who can access it.
- [ ] Retention/deletion date or rule.
- [ ] Whether it can be used only for bug reproduction.
- [ ] Whether research/publication use is separately requested.
- [ ] Whether model training is allowed (default: **no** unless separately explicit).
- [ ] Whether redistribution is allowed (default: **no**).
- [ ] Contact/process for withdrawal or deletion before irreversible publication/aggregation.

## 11. Report identity and attribution

For product QA, a GitHub username is enough attribution if the contributor wants public credit.

A contributor may also choose a report ID with no additional profile information.

Do not collect emails solely to validate Chinese support.

If a future publication needs author/acknowledgment information, use the project’s separate authorship/approval workflow. Authorship consent, acknowledgment consent, and test-data consent are different decisions.

## 12. Minimal machine-readable report shape

A future validator may use:

```json
{
  "schema_version": 1,
  "task_id": "CHN-INJECT-WAYLAND-001",
  "yazses_commit": "<sha>",
  "environment": {
    "os": "Linux",
    "session": "Wayland",
    "cpu": "<model or architecture when relevant>",
    "ram_gb": 16
  },
  "configuration": {
    "engine": "faster-whisper",
    "model": "small",
    "language": "zh",
    "chinese_script": "simplified"
  },
  "fixture_id": "han-mixed-001",
  "expected": "你好，世界。简体中文测试 123，YazSes。",
  "observed": "你好，世界。简体中文测试 123，YazSes。",
  "result": "pass",
  "fallback": ""
}
```

The schema should reject fields known to invite sensitive data such as `audio_path`, `home_directory`, `hostname`, or free-form clipboard dumps.

## 13. Retention

### Public QA reports

They are repository history and should be treated as public/permanent once merged. Therefore collect only data suitable for permanent public disclosure.

### Private bug audio

Default to the shortest retention that solves the reproduction, then delete.

### Research data

Follow the separately approved research protocol; never silently inherit the retention policy of GitHub issues/PRs.

## 14. Release-gate evidence

ADR-v2-139’s native-speaker requirement can be satisfied without raw audio publication.

The release record should state:

- number of independent Simplified reviewers;
- number of independent Traditional reviewers;
- what surfaces they reviewed;
- whether material phrase/UX changes resulted;
- unresolved limitations.

Do not publish unnecessary demographics.

## 15. Campaign-task rule

Any Mandarin task involving human evidence must declare one of:

- `cloud_agent_ready=true` only when all evidence is deterministic and container-produced;
- `cloud_agent_ready=false` for native-language judgment;
- `cloud_agent_ready=false` for hardware/device behavior;
- `cloud_agent_ready=false` for model/performance measurements tied to real hardware.

An agent may format a human’s evidence. It may not invent it.
