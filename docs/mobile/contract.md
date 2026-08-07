# The YazSes core contract — one behaviour, many implementations

**Status:** design, no code yet · normative decision in `docs/mobile/adr/adr-mob-008-cross-platform-contract.md`
**Implements:** the `contract/` directory (to be created by the M0 issue)
**Last updated:** 2026-08-07

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
  VERSION                   semver, e.g. 1.0.0
  schema/
    config.schema.json      every config section, key, type, default
    features.schema.json    capability-registry shape
    transcript.schema.json  Transcript / segment / token-confidence shape
  vectors/
    clean_text.json
    disfluency.json
    voice_punctuation.json
    spacing.json
    vocabulary.json
    grammar_classify.json
    hold_detector.json
    vad_gate.json
  audio/                    short licence-clean clips for end-to-end fixtures
```

## 2. Vector format

Every vector file is a JSON object with a `unit`, the contract version it was generated
under, and a list of cases:

```json
{
  "unit": "postprocess.clean_text",
  "contract_version": "1.0.0",
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

## 7. Why this is worth the extra step in desktop PRs

1. It converts "port this module" into a weekend-sized task with an unambiguous
   definition of done — the single biggest lever on contributor throughput.
2. It gives the desktop a regression net over behaviour that is currently specified only
   implicitly by its own tests.
3. It makes the iOS wave cheap: the spec already exists and is executable.
4. It means a user can be told, truthfully, that the phone and the laptop clean, filter,
   punctuate and classify their speech identically.
