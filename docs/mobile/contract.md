---
description: "The shared behaviour contract every YazSes implementation must satisfy: six units and 191 cases, live and enforced in CI, so desktop and mobile cannot silently diverge."
---

# The YazSes core contract — one behaviour, many implementations

**Status:** **shipped and enforced in CI** (2026-08-07) · normative decision in
[ADR-MOB-008](adr/adr-mob-008-cross-platform-contract.md)
**Implements:** [`contract/`](https://github.com/MSKazemi/yazses/blob/main/contract/README.md)
— six units live (`clean_text`, `disfluency`, `voice_punctuation`, `spacing`,
`vocabulary`, `grammar`; 191 cases), guarded by `tests/test_contract_vectors.py`. The
hold detector and the VAD gate land with the implementations that need them.
**Last updated:** 2026-08-09

> **It earned its keep on day one.** The first 54 cases surfaced **three real bugs** in
> shipped code: `"that is likely correct"` became `"that is ly correct"`, `basically_fn`
> became `_fn`, and a URL silently lost a path segment — a filler regex was missing a
> trailing word boundary and the code-identifier guard was inspecting the matched filler
> instead of the token containing it. A year of use had not caught them. Writing down
> what *should* happen, and then reading what *does*, is the entire mechanism.

The Android app shares **no code** with the Python desktop, yet must be the same product.
This document specifies the mechanism that makes that checkable rather than aspirational:
a language-neutral contract of golden test vectors that every implementation runs.

If you are here to contribute a Kotlin module, the short version is: **your module is
correct when `contract/vectors/<your-file>.json` is green.** You do not need to read Python.

---

## 1. Layout

```
contract/
  README.md                 how to run and extend the contract
  VERSION                   semver, e.g. 4.0.0
  schema/
    config.schema.json      every config section, key, type, default
    features.schema.json    capability-registry shape
    transcript.schema.json  Transcript / segment / token-confidence shape
  vectors/                  PARITY — generated from the shipped implementation
    clean_text.json
    disfluency.json
    voice_punctuation.json
    spacing.json
    vocabulary.json
    grammar_classify.json
    hold_detector.json
    vad_gate.json
  semantic/                 MEANING — hand-authored, never regenerated (§8)
    dimensions.json         conserved dimensions + extraction patterns
    invariants.json         invariants + minimal pairs
  audio/                    short licence-clean clips for end-to-end fixtures
```

## 2. Vector format

Every vector file is a JSON object with a `unit`, the contract version it was generated
under, and a list of cases:

```json
{
  "unit": "postprocess.clean_text",
  "contract_version": "4.0.0",
  "source": "src/yazses/postprocess/cleaner.py::clean_text",
  "cases": [
    {
      "id": "strips-blank-audio-marker",
      "description": "Whisper emits [BLANK_AUDIO] on silence; it must never be delivered",
      "options": {},
      "input": "[BLANK_AUDIO]",
      "expected": ""
    },
    {
      "id": "strips-leading-punctuation",
      "description": "a burst starting with a comma is a decode artefact",
      "options": {},
      "input": ", hello world",
      "expected": "hello world"
    }
  ]
}
```

Rules:

- `id` is stable and kebab-case; renaming an id is a breaking change to the vector file.
- `options` carries only the config keys the unit actually reads, using the **shared key
  names** from `schema/config.schema.json`.
- `input`/`expected` are JSON values, not necessarily strings — `hold_detector` takes an
  event trace, `grammar_classify` returns an intent object.
- Every unit MUST include the ugly cases: empty, whitespace-only, punctuation-only,
  unicode and RTL (Persian is a first-class test language for this project), very long
  input, repeated-word input, and the adversarial sequences the disfluency filter exists
  for ("no wait, scratch that").

## 3. Generation and the drift guard

```
scripts/gen-contract-vectors.py     runs the shipped Python implementation, writes vectors/
tests/test_contract_vectors.py      re-runs every vector against Python; fails on mismatch
```

This is the same generate-and-guard pattern the repo already uses for the CLI reference
(`scripts/gen-docs.py` + `tests/test_gen_docs.py`).

The consequence is the point: **a desktop PR that changes shared behaviour fails CI until
the author regenerates the vectors**, which turns silent cross-platform drift into a
visible diff and a contract-version bump. Reviewers must read that diff — a regenerated
vector file is a behaviour change, not a formatting change.

Case *inputs* are hand-written and reviewed (they encode intent); only *expected* outputs
are generated. A generator that invents its own inputs would happily bless a bug.

## 4. Consumption

| Implementation | How |
|---|---|
| Python desktop | `tests/test_contract_vectors.py` (pytest, parameterised over every case) |
| Android | `:core:contract-test` reads the same files from the repo; JUnit parameterised tests |
| iOS (later) | XCTest over the same files, contract version recorded in About |

No implementation may ship a "known-failing vectors" list. A vector that a platform
genuinely cannot satisfy is a contract bug: either the vector is wrong, or the behaviour
needs a platform-conditional expectation added explicitly to the case.

## 5. Versioning

`contract/VERSION` is semver:

- **patch** — new cases for existing behaviour, no expectation changes;
- **minor** — a new unit / vector file;
- **major** — any changed expectation, i.e. a deliberate behaviour change. Requires the
  justification a behaviour change deserves, and every implementation must be updated or
  explicitly recorded as satisfying the older version.

Each implementation reports the contract version it satisfies (the Android About screen
shows it next to the app version), so "is my phone behaving like my laptop?" has an
answer a user can read off the screen.

## 6. What the contract deliberately does not cover

- **Model output.** Vectors start *after* speech recognition, from recognised text. Engines
  differ and are not deterministic across platforms; acoustic quality is `:bench`'s job.
- **Platform surfaces.** Injection, IME behaviour, lifecycle, permissions — no shared
  semantics exist, so pretending otherwise would be noise.
- **APIs.** The contract constrains behaviour, never class names or module structure. Each
  platform stays idiomatic.

## 7. The semantic layer — the half the desktop cannot generate

Everything above pins **parity**: every implementation delivers the same string. That is
necessary and not sufficient, and the gap is structural rather than accidental.

Because §3 generates every expectation by running the shipped Python, one commit can
change the implementation, the generator and the golden data together. CI stays green,
the vectors stay green, and a cleanup rule that erased a real distinction is now the
cross-platform consensus — inherited by Android and iOS as *the specification*.

`contract/semantic/` closes that hole with expectations **no generator can write**
(ADR-MOB-008 §8, proposed by @YossiMH in
[#98](https://github.com/MSKazemi/yazses/issues/98)). Each case records the delivered
text a human says the user must receive, plus the dimensions that must survive:

> Post-processing may simplify form, but it must not silently erase or invert a
> distinction that changes what a downstream reader should understand or do.

```json
{
  "id": "polarity-medication-not-taken",
  "input": "I did not take the medication",
  "expected": "I did not take the medication",
  "must_preserve": {"polarity": "negative", "actor": ["speaker"]},
  "minimal_pair": {"partner": "polarity-medication-taken", "differs_in": "polarity"}
}
```

**Minimal pairs are the sharp edge.** Two utterances differing in exactly one
consequential dimension must not collapse into the same delivered text — a check no
per-case assertion can make, because each output looks entirely plausible alone:

```
she is stable          ->  "she is stable"
she is sort of stable  ->  "she is stable"     <- identical: the hedge is gone
```

On its first run the layer found **five shipped behaviours that destroy meaning**
([#146](https://github.com/MSKazemi/yazses/issues/146)) — including `that dose is not
right` delivered as `that dose is not` — while all 191 parity vectors were green. Each
was recorded as `known-gap` and strict-xfail: green while the gap is documented, **red
the moment the code is fixed**, so the case must be promoted rather than forgotten.

All five have since been fixed (contract 6.0.0) by removing `like`, `right`, `sort of`,
`kind of` and `actually` from the default filler list, and the strict-xfail did its job
— the invariants went red on the fix and are now `holds`. The example above is what the
code used to do; a current implementation must deliver `she is sort of stable`
unchanged. Note what the fix is *not*: nothing got cleverer about telling a hesitation
from a hedge. The filter cannot, so the ambiguous words leave the default list and stay
available to anyone who opts back in.

For a phone or a watch implementation this changes the promise. "Match Python" is a
weaker guarantee than "preserve these meanings" — and only the second one survives the
desktop being wrong.

## 8. Why this is worth the extra step in desktop PRs

1. It converts "port this module" into a weekend-sized task with an unambiguous
   definition of done — the single biggest lever on contributor throughput.
2. It gives the desktop a regression net over behaviour that is currently specified only
   implicitly by its own tests.
3. It makes the iOS wave cheap: the spec already exists and is executable.
4. It means a user can be told, truthfully, that the phone and the laptop clean, filter,
   punctuate and classify their speech identically.
