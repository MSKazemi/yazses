# Fixture schema gap analysis (prototype 0.1 against issue #699)

Status: analysis dated 2026-10-28; documentation only. Part of epic #692 / issue #699. It compares
what the synthetic Space prototype ships (`examples/hci-hf-lab/`, draft PR #703: `fixtures.js`,
`fixtures.schema.json`, schema `0.1-prototype`) with what #699 asks the canonical fixture set to
contain. It does **not** create a second schema: #699 says the Space consumes the dataset and must
not define its own, and the prototype's schema describes itself as provisional.

## 1. Decision needed before any canonical schema is written

#699 prefers `design/hci-huggingface/fixtures/` for the machine-readable schema, the documented
cases, a manifest and a dependency-light validator. The prototype already contains a working
schema, 16 scenarios and a Python validator (in `tests/test_hci_hf_lab.py`). Writing a second copy
under `design/` would create exactly the duplication the issue forbids. The options:

| Option | Effect |
|---|---|
| A. Promote: move the schema and fixtures to `design/hci-huggingface/fixtures/`, grow them to meet section 3, and make the Space import from there | One source of truth in the place the issue names. The Space then needs a build or copy step, because a static Space cannot read files outside its own folder. |
| B. Keep in place: `examples/hci-hf-lab/` stays the home, version it to `1.0`, and document that location in #699 | No move and no copy step. Departs from the path the issue prefers; the issue says "prefer", so this is allowed. |
| C. Split: the schema and validator live in `design/`, the Space ships a generated copy of the fixtures | Cleanest contract, and the Space copy is generated, never hand-edited. Needs a generator and a drift test, like the Hub export. |

No recommendation is made here: the choice affects #703, #696 and any future dataset on the Hub,
and it belongs to the maintainer. Whichever is chosen, the fields in section 3 are the same.

## 2. What the prototype already satisfies

| #699 requirement | Prototype |
|---|---|
| `schema_version` | Top-level `schema_version: "0.1-prototype"` |
| Monotonic relative timestamps | `timeline[].t_ms`, non-decreasing, all at or before `decision_at_ms`; the validator rejects malformed (negative, fractional, non-integer) and non-monotonic values |
| Modality, including experimental EEG/EOG | `modality[]` with an enum of voice intent, gaze, face, EMG and `eeg_eog_experimental`; the validator rejects an unknown modality |
| Freshness | `age_ms` on the gaze and activation inputs (the voice input has no age field) |
| Confidence in `[0, 1]` | Validated (the rejection test covers the gaze confidence) |
| Synthetic scenario metadata | `simulated_conditions` (lighting, device) |
| Explicit `synthetic=true` | Required per scenario and at the top level; the validator rejects a missing or false value |
| Licence and provenance | Top-level `license`, `provenance` and `generator` |
| Decision enum (accept, abstain, ask confirmation, stop) | `expected.decision`, validated; a missing or invalid decision is rejected |
| Negative examples, not only successes | Three scenarios are marked `negative_example` |
| Offline validation, no network, model, GPU or device | The validator and the Node and Python tests run with none |
| Ten or more cases | 16 scenarios |
| No real human data | Hand-authored; guarded by tests |

## 3. Gaps

| # | #699 asks for | Gap in the prototype |
|---|---|---|
| G1 | An event or sequence ID | Scenarios have an `id`; individual timeline events have no ID or sequence number |
| G2 | Signal **quality** as well as freshness | Only `confidence` and, for gaze and activation, `age_ms` exist; quality is not a separate field, so a low-quality signal and a low-confidence one cannot be told apart |
| G3 | Confidence that can be **unknown** | A confidence is always a number; a missing signal is expressed only as `gaze.connected = false` |
| G4 | Observation, intent candidate, target candidate, decision and **verified simulated outcome** as separate stages | The prototype has `inputs` (observations plus an intent hint) and `expected` (decision and target). There are no distinct intent-candidate and target-candidate records, and no verified-outcome field; the outcome exists only as the page's "preview only" line |
| G5 | Missing **consent or decision metadata** where required, rejected by the validator | Decision metadata is validated. No consent field exists, which is reasonable for synthetic-only data, but the schema should state that consent is not applicable rather than leave it absent |
| G6 | Out-of-order timestamps as a **scenario** | Staleness is modelled by `age_ms`. The validator rejects a non-monotonic timeline, but no fixture models events arriving out of order |
| G7 | Muscle hold and release **with bounce** | `accidental_blink` has `bounce_count = 1`. `muscle_hold_release` has `bounce_count = 0` (a hold released early), so hold and release with bounce is not exercised |
| G8 | Ambiguous or **untrusted** target requiring abstention | Conflicting modalities and low confidence abstain. There is no ambiguity between two near targets and no notion of a trusted or untrusted target |
| G9 | Stop, fallback **and recovery** on a missing sensor | Emergency stop and sensor disconnection exist. No scenario shows the sensor returning and the system recovering |
| G10 | A manifest of the fixture set | None; the schema and the fixtures file are the only artifacts |
| G11 | Documented intended metrics, with all sample numbers labelled simulated | The replay report (#700, branch `feat/hci-hf-replay-eval`) defines them; the schema documentation does not yet cross-reference it |

Scenario coverage, for reference, against the ten scenarios #699 lists: covered are correct gaze plus
spoken reference, contradictory voice and gaze, missing or low-confidence camera signal, accidental
blink double-event, destructive command requiring confirmation, and false and negative examples.
Partly covered are stale observation (G6), stop and fallback (G9) and hold and release (G7). Not
covered is ambiguous or untrusted target (G8).

## 4. What closing the gaps would change

G1, G2, G3, G4 and G10 change the schema (new fields and a manifest), so they force a version bump
and a migration of the 16 existing scenarios. G5 is a documentation statement. G6 to G9 add
scenarios and, for G8, may need a small extension of the resolver's rules, which the replay report
and the resolver tests would then cover. None of this is started: it waits for the decision in
section 1.

## 5. Constraints that stay fixed

Synthetic-only data; no real audio, transcripts, face or eye video, voiceprints, learning-corpus
material or biosignals in the repository or on the Hub; no change to the public `contract/`
semantics, the agent APIs, the live daemon or `src/yazses/`; and any Hub publication follows the
gate in [HF_PRIVACY_PREPUBLISH.md](HF_PRIVACY_PREPUBLISH.md) and the playbook in
[HF_PUBLICATION.md](HF_PUBLICATION.md).

Cross-references: epic #692; #693 (draft PR #703); #696 (the EEG/EOG protocol depends on this schema:
[EEG_EOG_FEASIBILITY_PROTOCOL.md](EEG_EOG_FEASIBILITY_PROTOCOL.md)); #700; #701; #698.
