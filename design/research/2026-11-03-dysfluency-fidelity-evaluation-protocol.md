# Dysfluency-friendly dictation: semantic-fidelity evaluation protocol

**Date:** 2026-11-03  
**Status:** Research / preregistration proposal. No corpus run, human study, model tuning, user-visible feature, or new ADR has been authorized or completed.  
**Canonical issue:** [#255 — evaluate dictation with dysfluent and dysarthric speakers](https://github.com/MSKazemi/yazses/issues/255).  
**Detailed methods / evidence audit:** [2026-11-03 preregistration worksheet](2026-11-03-dysfluency-study-registration-and-evidence-audit.md) — independent speaker/episode units, data rights, adjudication, statistics, and all unresolved freeze decisions.  
**Existing decisions:** [ADR-015](../adr/adr-015-dysfluency-friendly-mode.md), [ADR-v2-021](../adr/adr-v2-021-atypical-speech-adapter.md), [ADR-011](../adr/adr-011.md); [AGENTS.md](../../AGENTS.md).  
**Related:** [#144](https://github.com/MSKazemi/yazses/issues/144) and [#146](https://github.com/MSKazemi/yazses/issues/146) (both closed), [semantic invariants](../../contract/semantic/invariants.json), [research agenda](../../docs/research/agenda.md).

## Decision-facing summary

YazSes already offers an **opt-in**, fully local dysfluency-friendly filter. The current synthetic regression fixture evaluates collapse behavior, **not** recognition accuracy or user benefit on people who stutter or have dysarthria. In addition to WER, any real-speech evaluation must measure whether cleanup **deletes a content word, inverts a speaker correction, or manufactures unsupported text**. A good mean WER cannot erase a confirmed meaning-destructive case.

**Recommendation:** keep the existing mode off by default and preserve ADR-015. Extend #255 into a rights-cleared, *paired* offline evaluation of the exact same ASR hypothesis with the filter off/on. Publish negative results. Do not claim that YazSes improves atypical speech until the corpus gate and user-informed study separately support it. No proposed human-study threshold or participant preference should be treated as known in advance.

This document operationalizes the pre-recruitment proposal already discussed and accepted in principle in #255. It does **not** take ownership of or overwrite those contributors' methods; it adds a dataset-rights audit, reproducibility requirements, independent dual-reference metrics, and a resolution rule for disputed destructive cases.

## 1. Current implementation and evidence audit (2026-11-03)

| Item | Observed repository state | Implication |
| --- | --- | --- |
| [Disfluency filter](../../src/yazses/stt/filters/disfluency.py) | Optional filler removal, 2-gram deduplication, optional repetition/prolongation collapse, and self-correction handling | Paired filter effects can be measured without retraining an ASR model. |
| [ADR-015](../adr/adr-015-dysfluency-friendly-mode.md) | Accepted; describes 0% false-collapse and 92.9% recall on a fixed labelled **text fixture** | These are in-repository fixture figures, **not** real-speaker or real-audio validation. |
| [Fixture gate](../../tests/test_dysfluency_eval.py) | Checks clean-control false-collapse below 2% and synthetic dysfluency-case recall at least 60% | Keep this software regression gate, but do not report it as clinical/acoustic validation. |
| [ADR-v2-021](../adr/adr-v2-021-atypical-speech-adapter.md) | Accepted held-out improvement gate; fine-tuning and adapter-loading remain deferred | Avoid a duplicate adapter architecture or promise of personalized ASR today. |
| [#144](https://github.com/MSKazemi/yazses/issues/144), [#146](https://github.com/MSKazemi/yazses/issues/146) | Both closed as completed; historically demonstrated token-fragment and meaning-loss classes | Include the original failure families as **regression sentinels**, not open-bug claims. |
| [#255 discussion](https://github.com/MSKazemi/yazses/issues/255) | Proposed fixed SEP-28k sample, identical recognizer text, paired review, adjudication and false-alarm accounting | Preserve these previously agreed controls rather than start a new parallel research issue. |

**Verification limitation:** this is a code/document review of current GitHub content. No local tests, audio decoding, model benchmark, licence approval or participant evaluation were performed for this note.

### Transfer limits from published work

1. **Lea et al., CHI 2023.** Their survey of 61 and recordings from 91 people who stutter motivated changes to endpointing, decoder behavior, and dysfluency refinement. The combined interventions reduced average WER from 25.4% to 9.9% in their experimental setup and reduced cutoff events. These are **not** YazSes numbers, and cannot be attributed to the text filter alone. In YazSes's hold-to-talk path a key release ordinarily defines the endpoint; the endpointer result is not directly transferable. [Publisher landing page](https://machinelearning.apple.com/research/user-perceptions-technical), [DOI landing page](https://doi.org/10.1145/3544548.3581224).
2. **Sridhar and Wu, Interspeech 2025.** Their disability-led study of Whisper on stuttered podcast speech found especially poor behavior on sound repetitions and reports hallucinations on more than 20% of these cases in their setup. Their companion research repository reports *separate literal and semantic manual transcripts* for a subset of SEP-28k. Those two references are precisely why reporting only one WER is inadequate. Neither result estimates the YazSes error rate. [ISCA landing page](https://www.isca-archive.org/interspeech_2025/sridhar25_interspeech.html), [companion repository](https://github.com/aimpowered/stuttered-speech-benchmark).
3. **Raja et al., EMNLP 2025.** In dysarthric case studies, a dysarthria-informed and speaker-adapted model improved accuracy with less individual adaptation data than a purely personalized model. This supports the long-term feasibility question in ADR-v2-021, **not** adding an automatic on-device training dependency now. [ACL Anthology landing page](https://aclanthology.org/2025.emnlp-main.1701/).
4. **Kordt et al., Interspeech 2026.** Explicit disfluency markers and continual learning still involve tradeoffs with general-domain ASR performance. This is a reason to isolate opt-in experiments and prevent degradation on fluent controls. [Publication landing page](https://doi.org/10.21437/Interspeech.2026-2080).

## 2. Dataset feasibility, consent and licensing gate

The research agenda correctly points to SEP-28k as an accessible source of **stuttering-event labels**, but the original release is **not a ready-to-run dictation WER benchmark**.

| Candidate | What it can establish | Constraints / decision before use |
| --- | --- | --- |
| Existing YazSes synthetic text vectors | Deterministic regression, corruption sentinel coverage and reporter schema | No speaker-level benefit claim. Suitable for ordinary CI without real speech. |
| [SEP-28k original release](https://github.com/apple-aiml-research/ml-stuttering-events-dataset) | 3-second clips labelled for stuttering events and fluent controls | Annotations do **not** contain word-for-word reference transcripts. Dataset is CC BY-NC 4.0; podcast audio is not bundled and copyright stays with original podcast owners. Do not redistribute or treat the dataset as Apache-2.0. |
| [Sridhar–Wu Interspeech 2025 companion](https://github.com/aimpowered/stuttered-speech-benchmark) | Candidate verbatim/semantic reference texts and published Whisper hypotheses for an explicitly labelled subset | Repository states that it includes audio. A repository MIT notice does **not** automatically license the underlying SEP-28k annotations or third-party podcast audio. Review file-level terms, consent, reuse scope and transcript rights **before downloading or publishing derivatives**. |
| [TORGO, University of Toronto](https://www.cs.toronto.edu/~complingweb/data/TORGO/torgo.html) | Dysarthric vs matched-control acoustic evaluation | Public description is not an explicit permission to redistribute raw audio or derived participant transcripts. Obtain and record the applicable terms first; do not assume the source is a general open-data licence. |
| [UA-Speech, Illinois](https://speechtechnology.web.illinois.edu/uaspeech/) | More controlled dysarthric speech research | Restricted to government/academic researchers, not commercial use; no redistribution. Ineligible as a bundled YazSes corpus. |
| [Speech Accessibility Project](https://speechaccessibilityproject.beckman.illinois.edu/conduct-research-through-the-project) | Speech plus response transcripts from a diverse group of participants | Requires a signed institutional data-use agreement and proposal. **Not** an anonymous, public, immediately downloadable corpus. |
| [AS-70, Interspeech 2024](https://www.isca-archive.org/interspeech_2024/gong24_interspeech.html) | Potential Mandarin atypical-speech extension, with verbatim transcriptions | Separate language/consent/rights audit before inclusion; never infer an open redistribution licence from the article alone. |

**Hard precondition:** prepare a source and rights ledger for each proposed artifact with dataset version/revision, publisher, audio owner, annotation/reference owner, licence and permitted operations, consent/ethics constraints, distribution permission, and removal procedure. If any use is uncertain, **do not import it**. A public GitHub project with an Apache-2.0 licence must not accidentally relicense CC BY-NC content or participant speech. Do not embed, commit, paste to third-party coding tools, or send any real participant audio/transcripts to cloud services.

The viable low-risk beginning is **pure synthetic vectors** and a *locally run* manifest-driven tool. A real-speech pilot happens only after the rights ledger is approved. A public artifact may contain methods, code, aggregate measurements and non-reversible manifest hashes when permitted; it should not contain the underlying audio or participant transcripts.

## 3. Research question, estimands and the two transcript references

**RQ1 — primary safety:** for an identical recognized string, does the opted-in disfluency filter introduce *meaning-destructive edits* that would not have appeared with filtering off?

**RQ2 — utility:** among evaluable disfluent utterances, how often does the filter remove non-essential repetition/hesitation without losing speech content, and how often does it needlessly change fluent speech?

**RQ3 — recognition validity:** against a manually prepared **verbatim** reference and, if licensed and justified, a distinct **speaker-intent/semantic** reference, how do baseline ASR and filter-on output differ? Keep both metrics visible.

**RQ4 — future human validation:** do people who stutter and people with dysarthria independently prefer the same output style, experience lower correction burden and retain agency over their words? A corpus cannot answer this.

Do **not** infer a participant's intended meaning solely from an ASR output. The verbatim reference documents what is audible; the semantic reference must have a documented annotation policy, ambiguity tag and provenance. Speaker preference can only be established with the speaker's informed input.

### Operational error taxonomy (mutually exclusive primary label, secondary tags allowed)

- **Destructive-content:** a lexical content word, negation, hedge, quantity, name, code token or meaningful qualifier is deleted/substituted without support from the audio/reference.
- **Destructive-correction:** an accepted self-correction is reversed, rejected text is kept as the asserted answer, or corrected text is lost.
- **Destructive-structure:** orphan punctuation, joined fragments or synthetically produced structure not supported by the source.
- **Benign retention:** repetition/hesitation remains, but intended lexical meaning is preserved.
- **Safe cleanup:** a disfluency is removed without changing intended meaning.
- **No material edit:** both strings are equivalent or identical under the predeclared comparator.
- **Unassessable/disputed:** source is ambiguous, reference unavailable, segment cut off, or reviewers disagree; **not counted as a safe outcome**.

Keep secondary tags for affected group (sound repetition, word repetition, prolongation, block, interjection, fluent), and *severity*: content-bearing/clinical/legal/financial consequence potential versus cosmetic. Never diagnose a participant from the label.

### Primary and secondary outputs

**Primary:** number and proportion of utterances with *new, adjudicated meaning-destructive edits* in filter-on versus filter-off, reported by stratum and as paired item examples **only with permission to publish content**. Split confirmed / disputed / unassessable; do not silently drop ambiguous cases.

**Secondary:** proportion of correctly cleaned labelled events, percentage of clean controls modified at all (false-change rate), safe-cleanup yield, retained benign disfluencies, verbatim WER, semantic-reference WER if licensed, insertion/deletion/substitution breakdown, and end-to-end correction effort **only in an approved participant study**. Report numerator and denominator for every rate. If no dual references, say so and omit WER instead of inventing one.

**Statistics:** summarize by speaker where speaker IDs are genuinely known. With podcast data lacking reliable speaker IDs, cluster by episode as a *proxy* and explicitly avoid speaker-level inference. Show paired changes and uncertainty intervals; a 160-clip negative pilot is not proof of a low population error rate. A nonzero confirmed destructive case is a safety finding even if the mean WER improves.

## 4. Pre-registered pilot: methods to freeze before outcome inspection

The #255 thread proposed **160 source clips**: 40 each from sound repetition, word repetition, interjection, and fluent/no-disfluency. Preserve this first-stage target rather than quietly increase sample size after observing outcomes. Blocks and prolongations need a separately declared extension because they are distinct failure modes. Do not label this design already preregistered: the manifest and rights approval do not exist yet.

1. **Licence and researcher gate.** Log what can be downloaded, transcribed, retained and published. If access is disallowed/unknown, stop at synthetic fixtures and publish a blocked-status note, not a substitute convenience corpus.
2. **Freeze selection** without looking at model results. Select only label-qualified items (for example, two of three annotators), uniquely identify source and episode, cap repeated episodes, and document multi-label assignment and shortage handling. Save deterministic algorithm, selection seed, source version and SHA-256 of the locally materialized manifest **before** evaluating the outputs. If consent or licence forbids publishing IDs, publish only the reconstructible method and manifest hash.
3. **Pin engine**: YazSes commit, Python/uv lockfile and installed package versions, ASR backend/model name and model-weight digest, CPU backend/quantization, language, beam, prompts, chunk policy and random/decoding settings. Capture the raw ASR hypothesis once; no model rerun between filter conditions.
4. **Paired conditions**: (A) raw ASR text with the filter disabled; (B) **the exact same UTF-8 raw ASR bytes** run through the documented opt-in disfluency mode. Snapshot the full effective config, including preset expansion. Keep all *other* postprocessing fixed; report default-off and preset-on rather than silently turning on unrelated LLM cleanup.
5. **Independent adjudication**: at least two qualified annotators blind to A/B labels review source speech (where rights permit), verbatim/semantic references and the paired edits. They record reason codes before outcome aggregation. A third adjudicator resolves disagreement if permitted. If no adjudication is possible, retain **unresolved**; never call the case a pass. Record adjudication counts and initial agreement.
6. **Publish an audit trail** of method, manifest hash, software/model digests, counts, paired error taxonomy and aggregation script. Publish concrete excerpts only when expressly authorized by the data owner and participants; otherwise publish redacted/abstracted synthetic examples and aggregate counts.

### Proposed local schema for a future harness (illustrative; not real data)

~~~json
{
  "protocol_id": "yazses-dysfluency-fidelity-v1-proposed",
  "source": "synthetic-only-until-rights-approved",
  "manifest_sha256": "SHA256_OF_FROZEN_MANIFEST",
  "engine": {"repo_commit": "COMMIT_SHA", "backend": "PINNED_ENGINE",
             "model_digest": "MODEL_SHA256", "decoder_config_digest": "SHA256"},
  "items": [{
    "opaque_item_id": "SYNTHETIC_001",
    "group_key": "SYNTHETIC_EPISODE",
    "stuttering_labels": ["word_repetition"],
    "raw_hypothesis_sha256": "SHA256_OF_IDENTICAL_INPUT",
    "condition_off_sha256": "SHA256",
    "condition_on_sha256": "SHA256",
    "primary_label": "destructive-content|destructive-correction|destructive-structure|benign-retention|safe-cleanup|no-material-edit|unassessable-disputed",
    "adjudication": "confirmed|disputed|pending",
    "reviewers": 2,
    "publish_permission": false
  }]
}
~~~

The schema is a **planning example**, not a command to store actual speech-derived hashes in the public repository. A real implementation should separate private local evaluation data from public aggregate reports, explicitly validate the allowed enum values, and carry dataset-specific rights fields.

## 5. Safety gate and adjudication policy (proposed, not a release approval)

The exact zero-tolerance question was raised explicitly in the #255 comments; resolving it **before** collecting data is part of this protocol.

- **Confirmed destructive edit (one or more):** the studied configuration **fails the semantic-fidelity gate**. Publish and investigate it; do not average it away using WER or successful cleanups. This is not an automatic product rollback because the production mode is opt-in and the study may use one dataset; it blocks claims of validation and any proposal to enable the behavior by default.
- **Exactly one disputed candidate:** a blinded third adjudicator reviews it against the frozen policy; until resolved, the gate status is **inconclusive / hold**, not pass. If disagreement persists, publish the uncertainty without revealing restricted content and escalate the policy decision to project maintainers with a public, rights-safe case summary.
- **No confirmed destructive edit:** record **no observed failure in this sample**, not a guarantee of safety. Report false-change rate on fluent controls with denominators, safe-cleanup yield, all unresolved cases, and uncertainty. A gate result never authorizes user-facing efficacy claims without further evidence.
- **Missing source/reference, annotation agreement or rights:** blocked or inconclusive; never silently omit hard clips to recover a passing rate.

**False alarm is mandatory to report**, even when no destructive content is found: count every modification on designated fluent controls as an intervention, then separate changes judged semantically safe from material errors. The historical below-2% synthetic collapse gate in ADR-015 stays unchanged; it is **not** a statistically defensible promise about a 40-clip fluent sample.

## 6. Human study gate — separate from the corpus pilot

Recruitment, direct participation, collection of voice recordings, storing preferences, or publishing verbatim participant words is **out of scope** for this research-only branch.

A later study must be co-designed with people who stutter and people with dysarthria, include a specific research review/ethics determination and accessible informed consent, make retention/deletion explicit, offer skip/withdrawal without penalty, pre-register whether the participant prefers verbatim versus edited transcription, and allow speech to remain unedited by default. Measure task completion and correction cost, not just WER. Do not conflate clinical groups or imply the corpus pilot validates accessibility.

No third-party upload of recordings, transcripts, voiceprints, or participant metadata is permitted by YazSes's repository rules. No study process is part of the shipped daemon; the product must remain fully offline.

## 7. Design options and decision boundary

| Option | Privacy / feasibility | Rationale |
| --- | --- | --- |
| A. Existing opt-in rule-based cleanup + **fidelity evaluation** | Immediate research, no new dependency or runtime changes | **Recommended now.** Generates falsifiable evidence and tests the shipped feature. |
| B. Explicit per-user **verbatim versus cleaned** preference, with non-destructive review and correction | Likely feasible as later UX work but needs design, accessibility feedback and public-interface review | Explore only after evidence; do not silently rewrite content. Check overlaps with existing dictation reflow/preview designs before implementation. |
| C. Speaker-adapted offline ASR | Potentially large gains, but training data, CPU/time, model licensing and overfitting are nontrivial | Already governed by ADR-v2-021; maintain held-out acceptance and opt-in. Do not duplicate it. |
| D. More aggressive filler or correction heuristics enabled by default | Cheap but potentially harmful | Reject absent unusually strong semantic-fidelity and participant preference evidence. |

**Proposed future ADR trigger:** if the pilot shows the single opt-in cleaned representation cannot satisfy both fidelity and usability, prepare a *new* ADR on explicit transcript representations and user-controlled commit semantics. Do **not** reopen or silently override ADR-015 or ADR-v2-021 solely on speculation.

## 8. Actionable handoff for #255 (no new epic needed)

- [ ] **R1 — rights ledger:** confirm actual licence and consent for the chosen 2025 companion transcript CSV and its audio; record what may be downloaded locally, derived, or published. If unknown, stay synthetic.
- [ ] **R2 — freeze protocol:** approve strata, episode cap, label policy, deterministic sample algorithm, adjudication policy, and manifest-hash publication. Record changes **before** source inspection.
- [ ] **R3 — offline pure harness:** compare byte-identical raw hypotheses through off/on settings with a pinned config, emit only summary metrics by default, and test with synthetic stutter/filler/correction/negation/code/quantity fixtures. Do not read restricted speech in CI.
- [ ] **R4 — local corpus run:** once permitted, adjudicate 160 frozen clips, document every destructive, disputed or unassessable case, and report all denominators/uncertainties and separate verbatim/semantic metrics.
- [ ] **R5 — decision memo:** document PASS / FAIL / INCONCLUSIVE against the frozen rules, the exact limitation on claims, and whether any further ADR or UX design is warranted.
- [ ] **R6 — human validation:** only following co-design and institutional/ethical review, recruit consenting users and measure preference, correction cost and task completion; negative results remain publishable.

**Acceptance for this research document:** canonical issue reused, code paths and existing ADRs identified, primary safety outcome specified, false-alarm and adjudication rules explicit, data rights not assumed, reproducibility fields listed, and zero unverified performance claims. **No runtime tests were run; this is a design/research contribution only.**

## 9. Implemented research tool — synthetic-only smoke gate

The review branch also contains a deliberately limited and auditable first step:

- [Evaluation runner](../../scripts/evaluate_dysfluency_fidelity.py): a local, deterministic **text-only** comparison of the **same raw hypothesis** through the currently shipped filter with `enabled=False` versus `enabled=True, collapse_repetitions=True, collapse_prolongations=True`. No decoder, microphone, local LLM, model download, network request or operating-system output injection is involved. This is **filter-only**, not a full replay of the master accessibility preset (which also alters pre-speech padding).
- [Invented example cases](../../tests/fixtures/disfluency/fidelity_synthetic.json): nine synthetic phrases across repetition, prolongation, interjection, one placeholder `block` stratum (no simulated acoustic block) and fluent controls covering a hedge, a negation, code tokens and intentional hyphens.
- [Regression tests](../../tests/test_evaluate_dysfluency_fidelity.py): paired-input equality, independent literal/semantic word error counts, fail-over-pass semantics, disputed/inconsistent oracle handling, explicit denominators, schema checks, private-text leakage prevention and exclusive aggregate-report creation.

Run from the repository root after the ordinary `uv sync`:

~~~sh
uv run python -m pytest tests/test_evaluate_dysfluency_fidelity.py tests/test_dysfluency_eval.py -q
uv run python scripts/evaluate_dysfluency_fidelity.py tests/fixtures/disfluency/fidelity_synthetic.json
# Optional: write an aggregate report to a NEW local file (mode 0600 on POSIX)
uv run python scripts/evaluate_dysfluency_fidelity.py tests/fixtures/disfluency/fidelity_synthetic.json --output /tmp/yazses-synthetic-summary.json
~~~

**Output contract:** JSON contains only counts, rates, a manifest checksum, simplified whitespace/casefold word-error totals and a `PASS_SYNTHETIC` / `FAIL_SYNTHETIC` / `INCONCLUSIVE_SYNTHETIC` label. It contains **no** individual input, text, case ID, reference or per-case transcript checksum. A single confirmed meaning-destructive synthetic case fails regardless of successful cleanups; an unresolved or fixture-mismatched candidate is inconclusive unless a separate confirmed destructive case already fails. Both `fluent_changes` and `safe_cleanup_yield_nonfluent` report numerator and denominator, and undefined rates remain `null`.

This runner **does not** accept any input declaring itself a real audio corpus. It can reject wrong scope declarations but cannot independently verify that a caller's strings are synthetic: operators must never place private/participant transcripts in fixtures or third-party coding assistants. The fixed fixtures have **author-supplied oracles, not independent human adjudication**. Their success is a code-level smoke test, *not* evidence of improvement for people who stutter, people with dysarthria, or any other speakers.

**Verification distinction:** the pure evaluator tests were run in an isolated Python environment on 2026-11-03; real-`yazses` CLI integration, repository-wide gates and CI status must be checked on the PR before claiming green. This does not discharge the real-speech rights/consent and preregistration gates above.

## References (landing pages, not redistributed PDFs)

- Lea et al. (2023), *From User Perceptions to Technical Improvement: Enabling People Who Stutter to Better Use Speech Recognition*, CHI. [DOI](https://doi.org/10.1145/3544548.3581224).
- Sridhar and Wu (2025), *J-j-j-just Stutter: Benchmarking Whisper's Performance Disparities on Different Stuttering Patterns*, Interspeech. [ISCA](https://www.isca-archive.org/interspeech_2025/sridhar25_interspeech.html), [research companion](https://github.com/aimpowered/stuttered-speech-benchmark).
- Raja et al. (2025), *Idiosyncratic Versus Normative Modeling of Atypical Speech Recognition*, EMNLP. [ACL Anthology](https://aclanthology.org/2025.emnlp-main.1701/).
- Kordt et al. (2026), *Learning to Hear Hesitation: Continual Learning for Disfluency-Aware ASR*, Interspeech. [DOI](https://doi.org/10.21437/Interspeech.2026-2080).
- Apple AIML (SEP-28k), [dataset repository and licence](https://github.com/apple-aiml-research/ml-stuttering-events-dataset).
- University of Toronto, [TORGO dataset landing page](https://www.cs.toronto.edu/~complingweb/data/TORGO/torgo.html).
- University of Illinois, [UA-Speech terms](https://speechtechnology.web.illinois.edu/uaspeech/) and [Speech Accessibility Project data use](https://speechaccessibilityproject.beckman.illinois.edu/conduct-research-through-the-project).
