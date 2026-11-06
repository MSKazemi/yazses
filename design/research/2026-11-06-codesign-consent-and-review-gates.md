# Co-design, consent and research-review gates for hands-free work

**Date:** 2026-11-06 · **Baseline:** `main` at `8a72bbc6` · **Issue:** [#814](https://github.com/MSKazemi/yazses/issues/814) (NEXT-A11Y-02), epic [#790](https://github.com/MSKazemi/yazses/issues/790)
**Status:** Research draft, review pending. Not a decision, not a protocol, not legal advice. ADR-030 freeze unchanged.
**Scope:** read-only audit of this repository's existing consent and study documents against the five products #814 names. No `src/` change, no participant, no recruitment, no recording, no new external source.
**Siblings:** [#813 task inventory](2026-11-05-handsfree-task-inventory-and-evidence-gaps.md) · [#816 stop/unintended-activation threat model](2026-11-05-emergency-stop-and-unintended-activation-threat-model.md) · [#815 arbitration](2026-11-06-multimodal-arbitration-comparison.md) · #817 measurement · #819 go/no-go. Coordinates with [#419](https://github.com/MSKazemi/yazses/issues/419), [#425](https://github.com/MSKazemi/yazses/issues/425), [#427](https://github.com/MSKazemi/yazses/issues/427) as #814 asks.

## 1. Question and answer in one paragraph

#814 asks what must be decided about consent, recruitment, study risk, participant autonomy and withdrawal before any real hands-free user study. **Answer:** most of the *study-side* rules already exist, but they were written for the eye/camera programme and three things a hands-free study needs are missing. [Verified-in-docs] `design/eye-control/` already separates community QA from research, keeps raw camera data local, defines withdrawal, unbundles quotation consent and requires an ethics determination before recruitment. What it does not cover: (a) **co-design sessions** as distinct from study sessions; (b) **consent and autonomy for people who cannot sign, click or type**, including the assistant who helps them; (c) **the microphone and biosignal channels** that a hands-free study uses besides the camera. One hard blocker sits in front of all of it: **no responsible research institution is named anywhere**, so no determination can exist yet.

## 2. Method and labels

Read at `8a72bbc6`: `design/eye-control/{DATA_SHARING,RESEARCH_PARTICIPANT_TEMPLATE,CODESIGN_PROTOCOL_REQUIREMENTS}.md`, the relevant parts of `GOVERNANCE.md`, `PAPER_EVIDENCE.md`, `TRACEABILITY.md`, ADR-v2-150 and ADR-v2-148, and the three sibling notes above. Absences were found with `grep -rniE` over `design/eye-control/`, ADR-v2-150 and `design/hci-huggingface/EEG_EOG_FEASIBILITY_PROTOCOL.md`; the exact patterns are given with each claim.

Labels: **[Verified-in-docs]** read in a repository document at the cited line. **[Verified-grep-absence]** a `grep` found nothing; that is not proof of absence. **[Proposal]** my suggestion, for the maintainer or a research team to adopt, change or reject. **[Unknown]** not determinable from the repository.

External policy pages (ACM, European Commission) are cited **as the repository cites them** in `DATA_SHARING.md:134-137` and `RESEARCH_PARTICIPANT_TEMPLATE.md:225-230`; they were not re-read for this note.

## 3. What is already decided (cite, do not re-decide)

| #814 product | Existing contract | Where |
|---|---|---|
| Community QA is not research | "A public GitHub hardware report is engineering QA. It is not automatically consent to be a participant in a research paper." Four data classes A-D. | `DATA_SHARING.md:7-8`, `:60-98`; ADR-v2-150 Rule 1 (**Proposed**, 2026-09-22, `adr-v2-150-…md:3`) |
| No "I consent" checkbox on GitHub | "Do **not** implement a GitHub checkbox saying 'I consent to this paper'" | `DATA_SHARING.md:111-112`; forms are one-way `:203-215` |
| Determination before recruitment | "determine the applicable ethics/IRB/review requirement **before recruitment**"; ADR-v2-150 Rule 7 "pre-collection gate" | `DATA_SHARING.md:116-127`; ADR-v2-150 `:105-113`; `PAPER_EVIDENCE.md:6-7`, `:306-322` |
| Voluntary, no penalty | Not taking part "does not affect your ability to use YazSes, report bugs, contribute code" | `RESEARCH_PARTICIPANT_TEMPLATE.md:23-26` |
| Raw sensor data stays local | Raw camera "processed locally and are NOT uploaded or retained"; Class D "do not collect it centrally" | `RESEARCH_PARTICIPANT_TEMPLATE.md:51-68`; `DATA_SHARING.md:90-98` |
| Not collected | microphone recordings, diagnosis, GitHub username in analysis set | `RESEARCH_PARTICIPANT_TEMPLATE.md:108-120`; diagnosis also `PAPER_EVIDENCE.md:215-216` |
| Separate, unbundled sharing and quotation choices | "Do not bundle optional public release or quotation into one mandatory checkbox" | `RESEARCH_PARTICIPANT_TEMPLATE.md:161-170`; `DATA_SHARING.md:157` |
| Withdrawal and its limits | cutoff, unreleased rows removed, aggregates and public QA posts may persist | `RESEARCH_PARTICIPANT_TEMPLATE.md:172-188`; `DATA_SHARING.md:179-190` |
| Publication / release | prefer code, protocol, fixtures, aggregates; never consent forms, names, GitHub usernames, raw frames | `DATA_SHARING.md:162-177`; `RESEARCH_PARTICIPANT_TEMPLATE.md:150-159` |
| Compensation | "must not depend on successful feature performance" | `RESEARCH_PARTICIPANT_TEMPLATE.md:190-194` |
| Authorship ≠ participation | separate decisions | `DATA_SHARING.md:192-199` |
| Stop conditions (proposed minimum) | eight facilitator-must-stop conditions; a stop method "that does not depend on accurately controlling the experimental pointer" | `CODESIGN_PROTOCOL_REQUIREMENTS.md:40-59`; `RESEARCH_PARTICIPANT_TEMPLATE.md:40-41` |
| Co-design outside #425 stays out of participant analysis | enforced by `tests/test_eye_eval_schema.py::test_community_qa_cannot_declare_itself_research_grade` | `CODESIGN_PROTOCOL_REQUIREMENTS.md:89-91`; `TRACEABILITY.md:192` |

Two of these rest on a **Proposed** ADR (v2-150). Its rules are already mirrored in `DATA_SHARING.md` and one is enforced by a test, but the ADR itself is not accepted. This note does not change that.

## 4. Gaps, ranked by what blocks a study first

**R1 — No responsible institution or determination route.** [Verified-in-docs] Every document leaves it as a placeholder: `RESEARCH_PARTICIPANT_TEMPLATE.md:10-12` (`<INSTITUTION>`, `<APPROVAL/EXEMPTION/NOT-REQUIRED CONTEXT + REFERENCE>`), `CODESIGN_PROTOCOL_REQUIREMENTS.md:3-9` ("It has no protocol ID, no ethics determination"). An open-source project with no host institution cannot issue its own determination. Until a named institution or a documented independent review route exists, **every gate below is moot** for publishable research. Community QA (Class B) can continue as it is.

**R2 — Co-design is not defined as its own activity.** [Verified-in-docs] `CODESIGN_PROTOCOL_REQUIREMENTS.md:38` records `absent :: co-design consent`; the only co-design rule is the *negative* one (stays out of participant analysis, `:89-91`). Nothing says what a co-design session *is*: who is invited, what they are asked, what is written down, whether they are credited or paid for expertise, and whether a disagreement with the maintainer is recorded. #814 asks for "voluntary co-design" specifically. [Proposal] in section 5, item C.

**R3 — Consent and autonomy for people who cannot sign, click or type.** [Verified-grep-absence] `grep -rniE "capacity to consent|proxy|caregiver|assent|supported decision|legally authori[sz]ed|guardian"` over `design/eye-control/`, ADR-v2-150 and the EEG/EOG protocol finds only an unrelated "proxy" (a gaze-confidence metric, `README.md:264`). The template's consent record (`RESEARCH_PARTICIPANT_TEMPLATE.md:206-217`) assumes the participant can operate a consent mechanism. For the population #790 targets, the consent channel, a helper's role and the helper's own data are undefined. `CODESIGN_PROTOCOL_REQUIREMENTS.md:37` already lists `absent :: alternative format`, `absent :: read aloud`, `absent :: untimed` for the protocol's own accessibility; R3 is the consent-specific part of that row.

**R4 — Undue influence from dependence on the tool.** [Verified-grep-absence] `grep -rniE "undue|coerc|power imbalance|relationship"` over the same files: no hits. The template's no-penalty sentence (`:25-26`) covers community standing, not the case where a participant *uses YazSes as their way into the computer* and is asked by its maintainer to test a change. A person in that position may feel unable to say no or to report a failure. [Proposal] in section 5, item B.

**R5 — Lockout is a participant risk, not only a product gap.** [Verified-in-docs] The #816 threat model ranks G2: "Stop is final for a no-hands user; resume has no hands-free route" (`2026-11-05-emergency-stop-…md:83`), and the #813 inventory finds every pause, restart, update and reboot ends PAUSED with resume by CLI or Settings only (`2026-11-05-handsfree-task-inventory-…md:63`). The stop conditions (`CODESIGN_PROTOCOL_REQUIREMENTS.md:46-59`) cover a stop that fails (condition 3) but not a stop that works and leaves the participant stranded. Also, pause keeps the camera pipeline available (`…inventory…md:69`), so "paused" is not "camera off"; the information sheet's sensor section (`RESEARCH_PARTICIPANT_TEMPLATE.md:43-49`) does not say so.

**R6 — Microphone and biosignal channels are outside the data-class rules.** [Verified-in-docs] The template and data-class rules are titled and scoped for "eye / camera" (`DATA_SHARING.md:1`, `RESEARCH_PARTICIPANT_TEMPLATE.md:1`, `:19-21`). A hands-free study also uses the microphone (voice stop phrase, voice commands) and may use biosignal hardware. `DATA_SHARING.md:92` names "identifiable audio" as Class D, and the template excludes "microphone recordings" (`:115`), but there is no audio counterpart of the raw-camera policy (`:51-68`) saying the mic is processed locally and nothing is retained. [Verified-grep-absence] `grep -niE "eeg|biosignal|eog|emg"` over `DATA_SHARING.md` and the template: no hits; the only neural-data rule is in a feasibility note ("do not upload raw EEG…", `state-of-the-art/2026-11-03-brain-interface-feasibility.md:108`). ThinkGear runtime remains gated on #827; nothing here changes that.

**R7 — Retention has no ceiling and no deletion trigger.** [Verified-in-docs] Retention appears only as `<RETENTION>` (`RESEARCH_PARTICIPANT_TEMPLATE.md:14`) and as a topic to explain (`DATA_SHARING.md:124`, `GOVERNANCE.md:106`). There is no default for the contact/consent mapping, no event that deletes it (e.g. after the withdrawal cutoff), and no rule for the measurement set after publication. The number belongs to the institution; the *shape* can be fixed now. [Proposal] item F.

**R8 — Accessible invitation and recruitment channel.** [Verified-in-docs] The template has a plain-language invitation (`:17-26`) but no channel, format or timing rule, and `CODESIGN_PROTOCOL_REQUIREMENTS.md:37` lists the format terms as absent. Public GitHub issues may ask only whether a tester "is willing to be contacted separately" (`DATA_SHARING.md:209`); there is no stated route for *how* that contact happens or what it may contain.

## 5. Design checklist (proposal)

Every line is **[Proposal]**. A research team or the maintainer adopts, changes or rejects it; nothing is authorized by this note. Values in `<…>` belong to them.

**A. Gate before anything else (R1)**
- [ ] A named responsible institution or independent review body, and its determination reference, entered in `RESEARCH_PARTICIPANT_TEMPLATE.md:10-12`. Without it: community QA only, no human-participant claims, no co-design quotes in papers.
- [ ] The decision on ADR-v2-150 (accept, amend or reject) is the maintainer's; this checklist assumes its rules as written but does not depend on its status.

**B. Voluntariness and influence (R4)**
- [ ] The person inviting is not the person the participant depends on for support, or the dependence is disclosed and a third party handles consent.
- [ ] A stated promise: declining, stopping or reporting failure changes nothing about support, releases or the participant's own install.
- [ ] Sessions never run on the participant's daily install without a restore step and a check that it is back as it was. (Grounded in R5: a changed config can strand the person.)

**C. Co-design as a separate activity (R2)**
- [ ] Definition: co-design partners shape requirements and review designs; they are not measured. Output is a written design decision with the partner's view recorded, including disagreement.
- [ ] Its own short agreement covering: voluntariness, what notes are kept, quotation only with separate consent (#419, `CODESIGN_PROTOCOL_REQUIREMENTS.md:38`), credit choice (named, anonymous or none), and payment for expertise if any.
- [ ] Nothing said in co-design becomes participant data later, consistent with `CODESIGN_PROTOCOL_REQUIREMENTS.md:89-91`.
- [ ] First agenda item: the #816 Q1 trade-off (guarded spoken resume vs. no spoken resume, `2026-11-05-emergency-stop-…md:148`). It is the one open design question the threat model hands to #814 by name.

**D. Accessible invitation and consent (R3, R8)**
- [ ] Invitation and information sheet available in `<formats>` (e.g. plain text for a screen reader, read aloud, large print) and through a channel that is not a public GitHub thread.
- [ ] Untimed: no deadline to reply; the participant may take the sheet away and decide later.
- [ ] Consent may be given in any channel the participant controls (spoken and recorded by the facilitator, typed, a switch, or a helper acting on their instruction), with the channel recorded in the private consent record.
- [ ] If a helper is present: their role (operate a device on instruction, not answer for the participant), that they are not a participant, and that none of their data is collected.
- [ ] A determination on capacity and supported decision-making is the institution's; the checklist records that the question was asked, not the answer.
- [ ] Consent is re-confirmed after any stop before the session continues (already proposed, `CODESIGN_PROTOCOL_REQUIREMENTS.md:38`).

**E. Study risk specific to hands-free (R5, R6)**
- [ ] Add to the facilitator-must-stop list (`CODESIGN_PROTOCOL_REQUIREMENTS.md:40-59`): "the participant cannot leave the current state (PAUSED, FAULTED, held microphone) by a route they can produce". The facilitator, with a keyboard, is present for the whole session until this is fixed in product.
- [ ] No session ends with the camera or microphone pipeline running; the end-of-session check names the command that released them.
- [ ] Information sheet states that pause does not turn the camera off.
- [ ] An audio policy paragraph mirroring the raw-camera one (`RESEARCH_PARTICIPANT_TEMPLATE.md:51-68`): microphone processed locally, no recording, no transcript in the dataset; voiceprints never collected (AGENTS.md rule 1 names voiceprints among categories that may never leave).
- [ ] Biosignal: out of scope for any study until #827 resolves and a separate data-class decision exists; the template says so explicitly.
- [ ] Demo content only, no real accounts (already `RESEARCH_PARTICIPANT_TEMPLATE.md:140-141`).

**F. Retention and deletion (R7)**
- [ ] Contact/consent mapping: deleted at `<event, e.g. withdrawal cutoff plus N days>`; date written in the consent record.
- [ ] Measurement set: retained `<period>` set by the institution; the template states period and trigger, never "indefinitely".
- [ ] Co-design notes: kept only as long as the design decision they inform is open, unless the partner opts into longer.
- [ ] Withdrawal: existing rule (`RESEARCH_PARTICIPANT_TEMPLATE.md:172-188`) unchanged.

**G. Publication and sharing**
- [ ] Existing rules (section 3) apply unchanged. Add: no audio-derived or biosignal-derived feature leaves the participant's machine without a separate decision under R6.

## 6. Falsifying evidence and failure modes

- **R1 is falsified** by a committed, non-identifying record naming the institution and determination reference. None exists. [Verified-in-docs]
- **R3/R4 are falsified** by an existing rule covering a non-manual consent channel or the dependent-user case. The greps above found none; a reviewer who finds one should cite it and this note should shrink.
- **The checklist fails** if it makes a study impossible to run for the people it is meant for (e.g. a consent step only a hand user can complete), or if it raises the cost of community QA. Community QA is untouched on purpose.
- AGENTS.md rule 9 applies by analogy: a stop condition that fires on everything gets ignored; condition E1 is a specific, checkable state, not a judgement.

## 7. Proposed ADR text (not authorized)

Per #814's last investigation step, a *narrow proposed* amendment is possible but **not recommended now**: R1 makes any ADR change premature, and the existing rules already sit in a Proposed ADR (v2-150). If the maintainer wants one, the smallest form is a "Hands-free scope" paragraph in ADR-v2-150 extending Rules 4 and 7 from camera to microphone and biosignal channels, and adding co-design as an activity distinct from research. Status would be **Proposed**. No implementation follows.

## 8. Explicit non-claims

- No user study, participant data or measurement of any person.
- No legal, ethical or clinical determination; that belongs to a responsible institution (`DATA_SHARING.md:139-140`).
- No accessibility-compliance claim.
- No ADR status changes; ADR-v2-150 remains Proposed, ADR-030 freeze unchanged, no ThinkGear runtime (#827).
- Grep absences are search results, not proof; statements marked [Proposal] must not be quoted as project rules.
