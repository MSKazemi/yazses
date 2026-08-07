# The YazSes cross-platform contract

**One behaviour, many implementations.** This directory is the normative definition of
the behaviour every YazSes implementation shares — the Python desktop today, the Kotlin
Android app next, iOS after that. It is language-neutral on purpose: JSON that any
platform can read as test data.

Decision and rationale: [ADR-MOB-008](../docs/mobile/adr/adr-mob-008-cross-platform-contract.md).
Fuller narrative: [docs/mobile/contract.md](../docs/mobile/contract.md).

---

## If you are implementing a module in Kotlin (or Swift)

**Your module is correct when its vector file is green.** That is the whole definition.
You do not need to read Python, and you do not need a reviewer to tell you whether an
edge case was intentional — every case carries a `description` saying what it is for.

```json
{
  "id": "protects-code-identifier",
  "description": "a filler appearing INSIDE a code identifier must not be stripped …",
  "options": {},
  "input": "call basically_fn in um main.py",
  "expected": "call basically_fn in main.py"
}
```

`options` uses the **shared config key names** (`enabled`, `collapse_repetitions`, …),
so the settings your implementation reads are the same ones the desktop reads.

## Layout

```
contract/
  VERSION                    semver for the contract itself
  vectors/
    clean_text.json          postprocess.clean_text        Whisper artefact stripping
    disfluency.json          filters.disfluency            filler / repetition / self-correction
    voice_punctuation.json   postprocess.voice_punctuation spoken punctuation -> symbols
    spacing.json             postprocess.spacing           separator between bursts
    vocabulary.json          stt.vocabulary                initial_prompt merge
    grammar.json             commands.grammar              dictate vs command classification
```

**121 cases across six units.** Together they cover everything the Android
`:core:postprocess` ([#86](https://github.com/MSKazemi/yazses/issues/86)) and
`:core:commands` / `:core:vocab` ([#94](https://github.com/MSKazemi/yazses/issues/94))
modules have to reproduce — so both issues have a complete, executable definition of done.

`grammar.json` is the highest-stakes file here: it decides dictate-versus-command. A
divergence means the phone *types* "delete the last word" instead of doing it, so the
cases lean hard on the direction that matters — a command phrase buried in ordinary
prose must stay dictation.

Still to come, with the implementations that need them: the hold detector and the VAD
gate.

## How it is maintained

```sh
uv run python scripts/gen-contract-vectors.py           # write the vectors
uv run python scripts/gen-contract-vectors.py --check   # fail if they are stale
uv run python -m pytest tests/test_contract_vectors.py  # the guard
```

- **Inputs are hand-written** in `scripts/gen-contract-vectors.py` and reviewed like
  code. A human decides what is worth pinning; a generator that invented its own inputs
  would happily bless a bug.
- **Expectations are generated** by running the shipped implementation.

So a change to shared behaviour turns the guard red until it is regenerated, which makes
silent cross-platform drift into a reviewable diff.

> **A regenerated vector file is a behaviour change, not a formatting change.** Read the
> diff. Every other platform now has to follow it.

## Adding cases

Please do — this is the cheapest useful contribution in the project, and
[issue #83](https://github.com/MSKazemi/yazses/issues/83) is an open invitation.

1. Add `{id, description, input}` (plus `options` if relevant) to `CASES` in the
   generator. Ids are stable kebab-case; renaming one is a breaking change.
2. Run the generator.
3. **Read every expectation it produced.** If one surprises you, that is either a bug
   worth its own issue or a limitation worth documenting in the `description`. Say which
   in your PR.

Step 3 is not ceremony. The first 54 cases written for this contract surfaced **three
real bugs** in shipped code — `"that is likely correct"` became `"that is ly correct"`,
`basically_fn` became `_fn`, and a URL lost a path segment — because a filler regex was
missing a trailing word boundary and the code-identifier guard was inspecting the wrong
string. Nobody had noticed in a year of use. Cases we thought were boring found them.

Wanted: empty and whitespace-only input, punctuation-only, unicode, **RTL (Persian is a
first-class test language here)**, emoji and other astral-plane characters, very long
input, pathological repetition, and — most valuable — text that only *looks* like a
disfluency and must survive untouched.

## Versioning

`VERSION` is semver:

- **patch** — new cases for existing behaviour, no expectation changes
- **minor** — a new unit / vector file
- **major** — any changed expectation, i.e. a deliberate behaviour change

Every implementation records the contract version it satisfies, so "is my phone behaving
like my laptop?" has an answer a user can read off the About screen.

## What the contract deliberately does not cover

- **Model output.** Vectors start *after* speech recognition, from recognised text.
  Engines are not deterministic across platforms; acoustic quality is the benchmark
  harness's job, not this one's.
- **Platform surfaces.** Injection, IME behaviour, lifecycle, permissions — no shared
  semantics exist, so pretending otherwise would be noise.
- **APIs.** Behaviour only, never class names or module structure. Each platform stays
  idiomatic.
- **Encoding-dependent values.** `filter_transcript` also returns `chars_removed`; it is
  excluded because it is a length in Python code points while Kotlin and Swift count
  UTF-16 units, so pinning it would fail on emoji for no behavioural reason.
