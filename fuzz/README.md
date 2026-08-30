# Fuzzing YazSes

Two harnesses, both aimed at the same place: **the code that runs on whatever a
speech model happened to emit.**

Everything downstream of the decoder is handed text nobody wrote. A transcript is
not user input in the usual sense — no one typed it, no one reviewed it, and the
model will occasionally produce a 4,000-character run of one repeated syllable, a
lone combining mark, an unpaired surrogate, or Arabic embedded in English. Those
strings then travel through the cleaner, the disfluency filter, the punctuation
substituter and the command grammar, and out the other end they become
**keystrokes on the user's real keyboard**. A crash there is a dictation session
that dies mid-sentence; a hang there is a stuck modifier key.

The second harness fuzzes config loading, which has an unusually strong oracle:
ADR/issue #52 says loading is **total** — no file, however malformed, may stop the
daemon starting. "Never raises" is not a wish here, it is the documented contract,
which is exactly what a fuzzer is good at attacking.

## Why Atheris and not (only) Hypothesis

The suite already property-tests this pipeline with Hypothesis (#115), and those
tests stay. Hypothesis generates from a *declared* strategy — it explores the space
you thought to describe. Atheris is coverage-guided: it mutates toward inputs that
reach branches nothing has reached yet, which is a different search and finds a
different class of bug (pathological backtracking in one regex, a decoder edge case
behind three conditionals).

There is a second, smaller reason, stated plainly because it would otherwise look
like the first one: OpenSSF Scorecard's `Fuzzing` check scores this repository 0/10
despite #115, because its Python probe matches `import atheris` and nothing else —
property-based detection exists for Erlang, Haskell, Elixir, Gleam, JavaScript,
TypeScript, C# and F#, and not for Python
([`checks/raw/fuzzing.go`](https://github.com/ossf/scorecard/blob/main/checks/raw/fuzzing.go)).
That is a detection gap, not a testing gap. It is worth closing only because
coverage-guided fuzzing of this surface is worth having on its own; a harness added
to satisfy a scanner and never run would be a claim the project could not back.

## Running them

    uv pip install atheris        # Linux/x86_64 wheels for CPython 3.12-3.14
    python fuzz/fuzz_text_pipeline.py -atheris_runs=200000
    python fuzz/fuzz_config.py     -atheris_runs=200000

    # or with a corpus directory, which is how CI runs it
    python fuzz/fuzz_text_pipeline.py fuzz/corpus/text -max_total_time=180

`.github/workflows/fuzz.yml` runs both on a schedule and on pushes that touch the
pipeline, for a bounded time, and uploads any crashing input as an artifact.

## When a harness finds something

Do not fix it and move on. The corpus entry that triggered it goes into the suite
as a regression test with the real string in it, the way #115's findings became
contract vectors — a fuzzer that finds the same bug twice has been wasted.
