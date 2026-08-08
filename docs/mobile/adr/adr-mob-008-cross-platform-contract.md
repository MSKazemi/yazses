# ADR-MOB-008 — One behaviour, many implementations: a language-neutral contract with golden vectors

**Status:** Accepted (2026-08-07) · **amended 2026-08-08** — §8 adds a hand-authored
semantic-invariant layer that the desktop cannot generate ([#98](https://github.com/MSKazemi/yazses/issues/98))
**Deciders:** Mohsen Seyedkazemi Ardebili
**Review credit:** §8 exists because **@YossiMH** read this ADR before any code was
written and found the flaw described there.
**Context links:** [[adr-mob-001]] (monorepo), [[adr-mob-002]] (pure-Kotlin cores),
[[adr-mob-010]] (Apple wave), desktop analogues: `src/yazses/postprocess/`,
`src/yazses/commands/grammar.py`, `src/yazses/config.py`, `src/yazses/system/features.py`,
`scripts/gen-docs.py` + `tests/test_gen_docs.py` (the sync-guard pattern this reuses)

---

## Context

The Android port shares no code with the desktop ([[adr-mob-002]]) but must be *the same
product*. "Same product" has a precise meaning here, and it is not vague: given the same
recognised words and the same settings, both platforms must produce the same delivered
text and the same command classification. Concretely that covers Whisper-artefact
cleaning, the three-pass disfluency filter, voice punctuation, continuation spacing between
bursts, the personal-vocabulary → `initial_prompt` merge (including the built-in "YazSes"
priming), and the Tier-1 command grammar.

Today that behaviour exists only as Python source plus its pytest suite. If an Android
contributor reimplements it by reading `postprocess/cleaner.py`, three things happen: they
must read Python to write Kotlin (halving the contributor pool), they will get edge cases
subtly wrong, and six months later a desktop PR will change behaviour with no signal that
Android now diverges. The same trap awaits iOS.

The repo already contains the pattern that solves this: `scripts/gen-docs.py` generates the
CLI reference and `tests/test_gen_docs.py` fails when the checked-in output drifts from the
code. Generate-and-guard, applied to behaviour instead of documentation, is the mechanism.

## Decision

1. **A new top-level `contract/` directory is the normative definition of shared
   behaviour.** It is language-neutral (JSON), version-controlled, and reviewed like code:

   ```
   contract/
     README.md                 how to read, run and extend the contract
     VERSION                   contract semver; bumped by any vector change
     schema/
       config.schema.json      every config section/key/type/default (mirrors config.py)
       features.schema.json    the capability registry shape (mirrors system/features.py)
       transcript.schema.json  Transcript / segment / token-confidence shape
     vectors/
       clean_text.json         Whisper-artefact stripping
       disfluency.json         filler removal → 2-gram dedup → self-correction rollback
       voice_punctuation.json  spoken punctuation → symbols
       spacing.json            continuation prefix between bursts
       vocabulary.json         initial_prompt merge, incl. built-in "YazSes" priming
       grammar_classify.json   utterance → CommandIntent + confidence tier
       hold_detector.json      key-down/up event trace → burst start/end decisions
       vad_gate.json           frame RMS trace → keep/discard
   ```

   Each vector file is a list of `{id, description, options, input, expected}` cases,
   including the ugly ones (empty input, whitespace-only, punctuation-only, unicode,
   RTL/Persian text, very long input, adversarial "scratch that" sequences).

2. **The desktop generates the vectors and is guarded by them.**
   `scripts/gen-contract-vectors.py` exports each case by *running the shipped Python
   implementation*, and a pytest (`tests/test_contract_vectors.py`) re-runs every vector
   against that implementation and fails on mismatch. Therefore: a desktop change that
   alters shared behaviour fails CI until the author regenerates the vectors — which makes
   the divergence a visible, reviewable diff and an explicit contract-version bump, instead
   of silent drift. **Regenerating without reading the diff is the one failure mode to
   watch for in review.**

3. **Every other implementation consumes the same files as test data.** Android:
   `:core:contract-test` reads `contract/vectors/*.json` from the repo and drives JUnit
   parameterised tests against `:core:postprocess` / `:core:commands` / `:core:vad`. A
   Kotlin module is "done" when its vectors are green — a definition of done a contributor
   can check locally in seconds without a device, a model, or any Python.

4. **The contract is a *behaviour* contract, not an API contract.** It says nothing about
   class names, module layout or idiom; each platform stays idiomatic. It also does not
   cover platform-specific surfaces (injection, IME, lifecycle) — those have no meaningful
   shared semantics.

5. **Config keys are shared even though storage is not.** Android stores settings in
   DataStore, but the key names, sections, types and defaults come from
   `contract/schema/config.schema.json` and are validated against it. The app can therefore
   **import and export a desktop `config.toml`**, which is the migration path for a user who
   already runs YazSes on a laptop, and it keeps documentation shared.

6. **Contract versioning.** `contract/VERSION` is semver. A vector *addition* is a minor
   bump; a changed expectation is a major bump and requires the ADR-level justification a
   behaviour change deserves. Implementations record the contract version they satisfy, and
   the Android app shows it in its About screen next to the desktop version it matches.

7. **New shared behaviour lands contract-first.** Any future feature intended for both
   platforms adds its vectors in the same PR as the desktop implementation. This is the
   rule that keeps mobile from falling permanently behind: the desktop pays a few minutes,
   and the mobile port gets an executable specification for free.

8. **The desktop is not the sole oracle. A second, hand-authored layer pins *meaning*.**
   (Amendment, 2026-08-08.) Decisions 2 and 6 make the shipped Python the source of every
   expectation. That is correct for parity and structurally unsafe for correctness: one
   commit can change the implementation, the generator and the golden data together, so a
   cleanup rule that erases a high-consequence distinction becomes cross-platform
   consensus with every vector green. Parity vectors cannot detect this, because they were
   asked what the code does, not what the user must receive.

   `contract/semantic/` is therefore normative alongside `contract/vectors/`, and is
   **never mechanically regenerated**:

   ```
   contract/semantic/
     dimensions.json   conserved dimensions + their extraction patterns
     invariants.json   hand-authored cases
   ```

   Each case carries the exact delivered text a *human* says the user must receive, plus
   the dimensions that must survive it — `polarity`, `actor`, `time`, `quantity`, `unit`,
   `certainty`, `request_or_refusal`, `correction_marker`, `assessment`. The governing
   rule is one sentence:

   > Post-processing may simplify form, but it must not silently erase or invert a
   > distinction that changes what a downstream reader should understand or do.

   Two enforcement mechanisms, both in `tests/test_semantic_invariants.py`:

   - **Invariants.** `must_preserve` catches a lost distinction; `must_not_acquire`
     catches an inverted or invented one. Every case also pins its `commands.grammar`
     classification, because a clinical sentence misread as a command is not typed at all.
   - **Minimal pairs.** Two utterances differing in exactly one consequential dimension
     must not collapse to the same delivered text. This is the check no per-case
     assertion can make: `she is stable` and `she is sort of stable` are each perfectly
     plausible outputs, and only the pair reveals that the hedge was destroyed.

   **When the two layers disagree, this one wins.** A parity vector records what the code
   does; a semantic invariant records what it must do. An invariant is never edited to
   match the output — a case that fails is either a bug to fix or a `known-gap` carrying
   an issue link, decided in the PR and reviewed as a behaviour change. Known gaps are
   strict-xfail, so a gap can be recorded but not forgotten: fixing the code turns CI red
   until the case is promoted.

   This also changes what the contract promises a future implementer. "Match Python" is a
   weaker guarantee than "preserve these meanings" — and the second one survives the
   desktop being wrong.

## Consequences

- **The contributor experience changes qualitatively.** "Port the disfluency filter" stops
  being "read someone else's Python and guess" and becomes "make these 60 JSON cases pass".
  That is a weekend-sized, unambiguous, reviewable task — the shape the Mobile Working
  Group needs to parallelise (`docs/mobile/contributing.md`).
- The desktop gains a regression net over behaviour that is currently only implicitly
  specified, and a machine-readable description of its own config surface.
- The iOS wave gets a spec for free and lands in a fraction of the time ([[adr-mob-010]]).
- Cost: an extra step in desktop PRs that touch post-processing, and a real risk of
  rubber-stamped regeneration. Mitigation: the generator writes a stable, diff-friendly
  format (sorted keys, one case per block), and the PR template asks explicitly whether a
  vector diff is intentional.
- **The semantic layer earned its place on the first run.** Nineteen hand-authored cases
  found five shipped behaviours that destroy meaning ([#146](https://github.com/MSKazemi/yazses/issues/146)):
  `that dose is not right` is delivered as `that dose is not`, and `she is sort of stable`
  is delivered byte-identically to `she is stable`. Every parity vector was green
  throughout, and would have stayed green on Android and iOS too. The cost of the layer is
  that some cases are red on purpose; the alternative was shipping the same silent
  corruption to three platforms.
- Cost: two layers to keep in mind, and a judgement call about which one a new case
  belongs in. The bar for the semantic layer is deliberately high — a case belongs there
  only if getting it wrong would mislead a reader about something consequential, and only
  if the author can name which dimension carries that consequence.
- The contract cannot capture everything — model output itself is not deterministic across
  engines, so vectors deliberately start *after* STT, from recognised text. Audio-level
  parity is handled by `:bench` and device reports, not by vectors.

## Rejected

- **A shared native core (Rust/C++) called from both Python and Kotlin.** It would give
  literal code sharing, and it is what a bigger team would do — but it adds a third
  language, a cross-compilation matrix (5 desktop targets × 4 Android ABIs), and an FFI
  boundary to every pure function, for logic that is a few hundred lines of string
  handling. It would also gut the contributor story: nobody fixes a spacing bug in Rust FFI
  on a Saturday. The project already archived one Rust rewrite (`archive/rust-hci-v1`);
  this ADR declines to start a second.
- **Transpiling or auto-generating Kotlin from Python.** Unmaintainable, unidiomatic,
  unreviewable.
- **A documentation-only spec ("Android should behave like the desktop").** Exactly the
  failure this ADR exists to prevent. Prose is not enforceable; JSON in CI is.
- **Making Android call the desktop over the network to stay in sync.** Contradicts
  [[adr-011]] and the phone-only user.
- **Generating the semantic invariants from the desktop too** (the original §2 approach,
  applied to §8). It would have been consistent, cheap, and worthless: an oracle derived
  from the implementation under test cannot contradict it. The layer's entire value is
  that a human wrote down what the user must receive without asking the code.
- **Leaving §8 to a linter or an LLM judge.** A model that scores "did meaning survive?"
  is unreproducible across runs and platforms, and cannot be re-run by an Android
  contributor with no network. Patterns and minimal pairs are cruder and portable — and a
  test that flags a real regression on a phone in 40 ms beats a better test nobody runs.
