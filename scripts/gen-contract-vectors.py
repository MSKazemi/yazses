#!/usr/bin/env python3
"""Generate the cross-platform contract vectors in `contract/vectors/`.

The Android port (and, later, iOS) shares **no code** with this Python tree, yet has
to be the same product: given the same recognised words and the same settings, every
implementation must deliver the same text. `docs/mobile/adr/adr-mob-008-cross-platform-contract.md`
makes that checkable instead of aspirational — a language-neutral set of golden test
vectors that every implementation runs.

The split that makes this trustworthy:

* **Inputs are hand-written** in this file (see `CASES`). They encode intent, they are
  reviewed like code, and a human decides what is worth pinning. A generator that
  invented its own inputs would happily bless a bug.
* **Expectations are generated** by running the shipped implementation.

Consequence, and the whole point: a change to shared behaviour makes
`tests/test_contract_vectors.py` fail until the author regenerates, which turns silent
cross-platform drift into a reviewable diff. **A regenerated vector file is a behaviour
change, not a formatting change** — read the diff.

Usage:
    uv run python scripts/gen-contract-vectors.py          # write the vectors
    uv run python scripts/gen-contract-vectors.py --check  # fail if they would change
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from yazses.config import DisfluencyConfig  # noqa: E402
from yazses.postprocess.cleaner import clean_text  # noqa: E402
from yazses.stt.filters.disfluency import filter_transcript  # noqa: E402

CONTRACT_DIR = ROOT / "contract"
VECTOR_DIR = CONTRACT_DIR / "vectors"
CONTRACT_VERSION = (CONTRACT_DIR / "VERSION").read_text().strip()


# ── the units under contract ──────────────────────────────────────────────────
#
# Each entry maps a unit name to (source_reference, runner). The runner takes the
# case's `input` and `options` and returns the value that goes in `expected`.
#
# Runners deliberately return only what is portable. `filter_transcript` also reports
# `chars_removed`, which is excluded on purpose: it is a length in Python `str`
# code points, and Kotlin/Swift count UTF-16 units, so pinning it would make the
# contract fail on emoji and other astral-plane text for no behavioural reason.

def _run_clean_text(text: str, options: dict[str, Any]) -> str:
    assert not options, "clean_text takes no options"
    return clean_text(text)


def _run_disfluency(text: str, options: dict[str, Any]) -> str:
    return filter_transcript(text, DisfluencyConfig(**options)).text


UNITS: dict[str, tuple[str, Callable[[Any, dict[str, Any]], Any]]] = {
    "postprocess.clean_text": (
        "src/yazses/postprocess/cleaner.py::clean_text",
        _run_clean_text,
    ),
    "filters.disfluency": (
        "src/yazses/stt/filters/disfluency.py::filter_transcript (.text)",
        _run_disfluency,
    ),
}


# ── hand-written cases ────────────────────────────────────────────────────────
#
# Every case needs a stable kebab-case `id` and a `description` saying what the case
# is *for*. Renaming an id is a breaking change to the vector file.
#
# Contributors: issue #83 is an open invitation to add the nastiest cases you can
# think of here. Unicode, RTL (Persian is a first-class test language for this
# project), pathological repetition, and text that only *looks* like a disfluency
# are all wanted.

CASES: dict[str, list[dict[str, Any]]] = {
    "postprocess.clean_text": [
        {"id": "empty-string", "description": "empty input survives untouched",
         "input": ""},
        {"id": "whitespace-only", "description": "a burst of pure whitespace yields nothing",
         "input": "   \t \n  "},
        {"id": "strips-blank-audio-marker",
         "description": "Whisper emits [BLANK_AUDIO] on silence; it must never be delivered",
         "input": "[BLANK_AUDIO]"},
        {"id": "strips-blank-parenthetical", "description": "the (blank) artefact variant",
         "input": "(blank)"},
        {"id": "strips-inaudible-marker", "description": "the [INAUDIBLE] artefact variant",
         "input": "[INAUDIBLE]"},
        {"id": "strips-silence-marker", "description": "the [silence] artefact variant",
         "input": "[silence]"},
        {"id": "blank-marker-with-surrounding-space",
         "description": "the artefact is matched after stripping, not before",
         "input": "  [BLANK_AUDIO]  "},
        {"id": "blank-marker-embedded-is-kept",
         "description": "an artefact inside real speech is NOT a whole-burst artefact; "
                        "dropping the sentence would lose the user's words",
         "input": "the meeting [BLANK_AUDIO] starts at noon"},
        {"id": "strips-leading-comma",
         "description": "a burst starting with punctuation is a decode artefact",
         "input": ", hello world"},
        {"id": "strips-leading-period", "description": "leading full stop is stripped",
         "input": ". hello world"},
        {"id": "strips-leading-ellipsis", "description": "leading ellipsis character is stripped",
         "input": "… and then we left"},
        {"id": "strips-leading-dot-run", "description": "a run of dots and spaces is stripped",
         "input": ". . .  hello"},
        {"id": "keeps-trailing-punctuation",
         "description": "only LEADING punctuation is an artefact; the user's full stop stays",
         "input": "hello world."},
        {"id": "keeps-internal-punctuation", "description": "sentence-internal punctuation survives",
         "input": "hello, world. and again"},
        {"id": "punctuation-only", "description": "a burst of nothing but punctuation",
         "input": "..."},
        {"id": "leading-question-mark-is-kept",
         "description": "only whitespace, dots and ellipsis are stripped — not every mark",
         "input": "? really"},
        {"id": "idempotent-on-clean-input",
         "description": "already-clean text passes through unchanged (clean_text must be idempotent)",
         "input": "the quick brown fox"},
        {"id": "unicode-accents-preserved", "description": "non-ASCII letters are untouched",
         "input": "café naïve Ångström"},
        {"id": "rtl-persian-preserved",
         "description": "RTL text must survive byte-for-byte; Persian is a first-class "
                        "test language for this project",
         "input": "سلام دنیا"},
        {"id": "rtl-persian-leading-punctuation",
         "description": "leading-punctuation stripping must not corrupt RTL text",
         "input": ". سلام دنیا"},
        {"id": "emoji-preserved", "description": "astral-plane characters are untouched",
         "input": "ship it 🚀 today"},
        {"id": "internal-newlines-preserved",
         "description": "only the ends are trimmed; internal structure is the user's",
         "input": "  first line\nsecond line  "},
        {"id": "code-identifier-preserved",
         "description": "code identifiers must survive dictation into an editor",
         "input": "call parse_config() in main.py"},
    ],
    "filters.disfluency": [
        {"id": "empty-string", "description": "empty input is returned unchanged",
         "input": ""},
        {"id": "whitespace-only", "description": "whitespace-only input short-circuits",
         "input": "   "},
        {"id": "disabled-passes-through",
         "description": "with enabled=false the filter is a no-op, even on obvious fillers",
         "input": "um so like the thing", "options": {"enabled": False}},
        {"id": "removes-single-filler", "description": "Rule A: a leading filler is removed",
         "input": "um the meeting is at noon"},
        {"id": "removes-multiple-fillers", "description": "Rule A: several fillers in one burst",
         "input": "um so like the meeting is uh at noon"},
        {"id": "removes-multiword-filler", "description": "Rule A: multi-word fillers ('you know')",
         "input": "the meeting you know is at noon"},
        {"id": "capitalised-filler-is-protected",
         "description": "the guard protects any token with an uppercase letter, so a "
                        "sentence-initial 'Um' — the commonest filler position, because "
                        "Whisper capitalises it — is NOT removed. Deliberate (it is also how "
                        "proper nouns survive), but a real limitation; see issue #117",
         "input": "Um the meeting is at noon"},
        {"id": "protects-proper-noun-lookalike",
         "description": "Rule A must not strip a capitalised token that happens to be a "
                        "filler word — 'Like' could be a product name",
         "input": "the Like button is broken"},
        {"id": "protects-code-identifier",
         "description": "a filler appearing INSIDE a code identifier must not be stripped — "
                        "this returned 'call _fn in main.py' until the guard was fixed to "
                        "test the enclosing token",
         "input": "call basically_fn in um main.py"},
        {"id": "filler-substring-not-matched",
         "description": "word boundaries: 'like' inside 'likely' must survive — this returned "
                        "'that is ly correct' until a trailing \\b was added",
         "input": "that is likely correct"},
        {"id": "sentence-that-is-only-fillers",
         "description": "a burst containing nothing but fillers",
         "input": "um uh er"},
        {"id": "repeated-3gram-survives",
         "description": "Rule B collapses 2-grams only, so a repeated THREE-word phrase "
                        "passes through. Pinned so both platforms agree on the limit",
         "input": "send it to send it to Alice"},
        {"id": "dedup-repeats-until-stable",
         "description": "Rule B runs to a fixed point, not once",
         "input": "go to go to go to line ten"},
        {"id": "legitimate-repetition-kept",
         "description": "'had had' is grammatical; the filter must not eat real language "
                        "that merely looks repeated",
         "input": "the report that he had had approved"},
        {"id": "self-correction-scratch-that",
         "description": "Rule C: 'scratch that' rolls back to the last sentence boundary",
         "input": "send it to Bob. scratch that send it to Alice"},
        {"id": "self-correction-no-wait",
         "description": "Rule C: the 'no wait' trigger",
         "input": "meet at three. no wait meet at four"},
        {"id": "self-correction-at-start",
         "description": "Rule C with no preceding sentence to roll back to",
         "input": "scratch that send it to Alice"},
        {"id": "self-correction-trigger-inside-quote",
         "description": "the trigger phrase can appear in genuine speech; documents whatever "
                        "the shipped behaviour is so both platforms agree",
         "input": "he said never mind the cost and left"},
        {"id": "collapse-repetitions-off-by-default",
         "description": "ADR-015 collapse is opt-in; a stutter survives by default",
         "input": "b-b-because it works"},
        {"id": "collapse-repetitions-on",
         "description": "ADR-015: hyphenated stutter collapsed when enabled",
         "input": "b-b-because it works", "options": {"collapse_repetitions": True}},
        {"id": "collapse-repetitions-spaced",
         "description": "ADR-015: space-separated stutter fragments",
         "input": "b b because it works", "options": {"collapse_repetitions": True}},
        {"id": "collapse-word-repetition",
         "description": "ADR-015: a repeated whole short word",
         "input": "the the the meeting", "options": {"collapse_repetitions": True}},
        {"id": "collapse-prolongations-off-by-default",
         "description": "prolongation collapse is opt-in",
         "input": "sooo good"},
        {"id": "collapse-prolongations-on",
         "description": "ADR-015: a prolonged vowel run is collapsed when enabled",
         "input": "sooo good", "options": {"collapse_prolongations": True}},
        {"id": "prolongation-min-run-respected",
         "description": "a run shorter than prolongation_min_run is left alone",
         "input": "soo good", "options": {"collapse_prolongations": True,
                                          "prolongation_min_run": 4}},
        {"id": "clean-sentence-untouched",
         "description": "text with no disfluency must pass through byte-for-byte",
         "input": "the quick brown fox jumps over the lazy dog"},
        {"id": "collapses-double-spaces",
         "description": "removing a filler must not leave a double space behind",
         "input": "the um meeting"},
        {"id": "rtl-persian-untouched",
         "description": "RTL text with no English fillers must survive unchanged",
         "input": "سلام دنیا این یک آزمایش است"},
        {"id": "long-input-many-fillers",
         "description": "a long burst — the filter must stay correct at meeting length",
         "input": ("um so " * 40) + "the actual point is here"},
        {"id": "url-preserved",
         "description": "a URL path segment that happens to be a filler word must survive — "
                        "this ate 'actually' out of the middle of the URL until the guard "
                        "was fixed",
         "input": "um see https://example.com/actually for details"},
        {"id": "numbers-preserved", "description": "digits and times survive filtering",
         "input": "um the deploy is at 0900 on 2026-08-07"},
    ],
}


def build(unit: str) -> dict[str, Any]:
    """Run the shipped implementation over a unit's hand-written cases."""
    source, runner = UNITS[unit]
    cases = []
    seen: set[str] = set()
    for case in CASES[unit]:
        cid = case["id"]
        if cid in seen:
            raise SystemExit(f"duplicate case id in {unit}: {cid}")
        seen.add(cid)
        options = case.get("options", {})
        cases.append({
            "id": cid,
            "description": case["description"],
            "options": options,
            "input": case["input"],
            "expected": runner(case["input"], options),
        })
    return {
        "unit": unit,
        "contract_version": CONTRACT_VERSION,
        "source": source,
        "cases": cases,
    }


def filename(unit: str) -> str:
    return unit.split(".", 1)[1] + ".json"


def render(doc: dict[str, Any]) -> str:
    """Stable, diff-friendly JSON: one case per block, keys in a fixed order."""
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if any vector file is out of date")
    args = ap.parse_args()

    VECTOR_DIR.mkdir(parents=True, exist_ok=True)
    stale: list[str] = []
    for unit in UNITS:
        path = VECTOR_DIR / filename(unit)
        text = render(build(unit))
        if args.check:
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            if current != text:
                stale.append(str(path.relative_to(ROOT)))
            continue
        path.write_text(text, encoding="utf-8")
        n = len(CASES[unit])
        print(f"wrote {path.relative_to(ROOT)}  ({n} cases)")

    if stale:
        print("Out of date:\n  " + "\n  ".join(stale))
        print("\nRun: uv run python scripts/gen-contract-vectors.py")
        print("Then READ THE DIFF — a changed expectation is a behaviour change.")
        return 1
    if args.check:
        print("contract vectors are up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
