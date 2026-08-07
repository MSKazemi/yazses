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

from yazses.commands.grammar import classify  # noqa: E402
from yazses.config import DisfluencyConfig  # noqa: E402
from yazses.postprocess.cleaner import clean_text  # noqa: E402
from yazses.postprocess.spacing import continuation_prefix  # noqa: E402
from yazses.postprocess.voice_punctuation import apply_voice_punctuation  # noqa: E402
from yazses.stt.filters.disfluency import filter_transcript  # noqa: E402
from yazses.stt.vocabulary import merge_initial_prompt  # noqa: E402

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


def _run_voice_punctuation(text: str, options: dict[str, Any]) -> str:
    assert not options, "apply_voice_punctuation takes no options"
    return apply_voice_punctuation(text)


def _run_spacing(text: str, options: dict[str, Any]) -> str:
    return continuation_prefix(text, had_recent_injection=options["had_recent_injection"])


def _run_vocabulary(parts: list[str | None], options: dict[str, Any]) -> str | None:
    assert not options, "merge_initial_prompt takes no options"
    return merge_initial_prompt(*parts)


def _run_grammar(text: str, options: dict[str, Any]) -> dict[str, Any]:
    """Serialise CommandIntent to a portable shape.

    This is the highest-stakes unit in the contract: it decides dictate-vs-command,
    so a divergence means the phone TYPES "delete the last word" instead of doing it.
    The optional SLM router and macro table are deliberately not exercised — they are
    injected, model-dependent and not shared behaviour.
    """
    intent = classify(text, profile=options.get("profile", "default"))
    return {
        "intent": intent.intent.value,
        "action": intent.action,
        "args": intent.args,
        "raw_text": intent.raw_text,
    }


UNITS: dict[str, tuple[str, Callable[[Any, dict[str, Any]], Any]]] = {
    "postprocess.clean_text": (
        "src/yazses/postprocess/cleaner.py::clean_text",
        _run_clean_text,
    ),
    "filters.disfluency": (
        "src/yazses/stt/filters/disfluency.py::filter_transcript (.text)",
        _run_disfluency,
    ),
    "postprocess.voice_punctuation": (
        "src/yazses/postprocess/voice_punctuation.py::apply_voice_punctuation",
        _run_voice_punctuation,
    ),
    "postprocess.spacing": (
        "src/yazses/postprocess/spacing.py::continuation_prefix",
        _run_spacing,
    ),
    "stt.vocabulary": (
        "src/yazses/stt/vocabulary.py::merge_initial_prompt",
        _run_vocabulary,
    ),
    "commands.grammar": (
        "src/yazses/commands/grammar.py::classify",
        _run_grammar,
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
        {"id": "removes-sentence-initial-capitalised-filler",
         "description": "Option 2 for #117: utterance-initial capitalised fillers are "
                        "stripped — Whisper capitalises the first word, so 'Um' at "
                        "position 0 is almost always a filler, not a proper noun",
         "input": "Um the meeting is at noon"},
        {"id": "strips-sentence-initial-uh",
         "description": "utterance-initial 'Uh' is unambiguous and still stripped",
         "input": "Uh so I think"},
        {"id": "protects-sentence-initial-capitalised-multiword-filler",
         "description": "multi-word fillers are not relaxed at position 0: 'You know "
                        "the meeting is at noon' can be a real sentence addressed to "
                        "someone, so it stays protected (#120 decision)",
         "input": "You know the meeting is at noon"},
        {"id": "protects-sentence-initial-right",
         "description": "sentence-initial 'Right' is content (a direction), not a "
                        "filler — #120 narrows the #117 relaxation",
         "input": "Right turn at the corner"},
        {"id": "protects-sentence-initial-like",
         "description": "sentence-initial 'Like' can name a UI element and must not "
                        "be treated as a filler",
         "input": "Like button is broken"},
        {"id": "protects-sentence-initial-actually",
         "description": "sentence-initial 'Actually' can be a real content word",
         "input": "Actually is a strong word"},
        {"id": "protects-sentence-initial-literally",
         "description": "the leading 'Literally' survives while the trailing lowercase "
                        "'literally' is still removed as a filler",
         "input": "Literally means literally"},
        {"id": "protects-proper-noun-lookalike",
         "description": "Rule A must not strip a capitalised token that happens to be a "
                        "filler word mid-utterance — 'Like' could be a product name",
         "input": "the Like button is broken"},
        {"id": "protects-mid-sentence-capitalised-filler-lookalike",
         "description": "mid-utterance capitalised filler lookalikes stay protected even "
                        "after the sentence-initial relaxation (#117 option 2)",
         "input": "open the Actually settings panel"},
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
    "postprocess.voice_punctuation": [
        {"id": "empty-string", "description": "empty input is unchanged", "input": ""},
        {"id": "no-punctuation-words", "description": "ordinary speech passes through untouched",
         "input": "the quick brown fox"},
        {"id": "comma", "description": "'comma' attaches to the preceding word, no space before",
         "input": "hello comma world"},
        {"id": "period", "description": "'period' becomes a full stop",
         "input": "hello world period"},
        {"id": "full-stop-alias", "description": "'full stop' is an alias for 'period'",
         "input": "hello world full stop"},
        {"id": "question-mark", "description": "'question mark' becomes ?",
         "input": "are you there question mark"},
        {"id": "exclamation-variants", "description": "both 'mark' and 'point' spellings",
         "input": "wow exclamation mark and again exclamation point"},
        {"id": "semicolon-and-colon", "description": "semicolon/colon symbols",
         "input": "first semicolon second colon third"},
        {"id": "semi-colon-two-words", "description": "'semi colon' spelled as two words",
         "input": "first semi colon second"},
        {"id": "new-line", "description": "'new line' becomes a newline character",
         "input": "first new line second"},
        {"id": "newline-one-word", "description": "'newline' spelled as one word",
         "input": "first newline second"},
        {"id": "new-paragraph", "description": "'new paragraph' becomes a blank line",
         "input": "first new paragraph second"},
        {"id": "tab-key", "description": "'tab key' becomes a tab character",
         "input": "name tab key value"},
        {"id": "longest-phrase-wins",
         "description": "'new paragraph' must not be parsed as 'new' + 'paragraph'; "
                        "the longest matching phrase wins",
         "input": "first new paragraph second"},
        {"id": "word-boundary-protects-substring",
         "description": "'command' contains 'comma' and must survive intact — the single "
                        "most likely regression in this unit",
         "input": "run the command now"},
        {"id": "period-inside-word",
         "description": "'periodic' begins with 'period' and must not be substituted",
         "input": "a periodic review"},
        {"id": "colon-inside-word",
         "description": "'colonial' begins with 'colon' and must not be substituted",
         "input": "the colonial era"},
        {"id": "multiple-punctuation-in-one-burst",
         "description": "several markers in a single utterance",
         "input": "dear Bob comma thanks for the update period"},
        {"id": "punctuation-word-at-start",
         "description": "a marker with no preceding word to attach to",
         "input": "comma hello"},
        {"id": "case-insensitive-marker",
         "description": "Whisper capitalises sentence-initial words; document the behaviour",
         "input": "Hello Comma world"},
        {"id": "rtl-persian-untouched",
         "description": "text with no English markers survives unchanged",
         "input": "سلام دنیا"},
        {"id": "code-identifier-untouched",
         "description": "an identifier containing a marker word must survive",
         "input": "call comma_separated_values now"},
    ],
    "postprocess.spacing": [
        {"id": "no-recent-injection", "description": "a fresh burst gets no separator",
         "input": "hello", "options": {"had_recent_injection": False}},
        {"id": "continues-recent-burst",
         "description": "a burst continuing a recent one is separated by a single space",
         "input": "hello", "options": {"had_recent_injection": True}},
        {"id": "suppressed-before-full-stop",
         "description": "no space before closing punctuation — otherwise you get 'word .'",
         "input": ".", "options": {"had_recent_injection": True}},
        {"id": "suppressed-before-comma", "description": "same for a comma",
         "input": ", and then", "options": {"had_recent_injection": True}},
        {"id": "suppressed-before-question-mark", "description": "same for a question mark",
         "input": "?", "options": {"had_recent_injection": True}},
        {"id": "suppressed-before-closing-bracket", "description": "same for ) ] }",
         "input": ") done", "options": {"had_recent_injection": True}},
        {"id": "suppressed-before-ellipsis", "description": "same for the ellipsis character",
         "input": "… later", "options": {"had_recent_injection": True}},
        {"id": "suppressed-before-percent", "description": "same for a percent sign",
         "input": "% of users", "options": {"had_recent_injection": True}},
        {"id": "not-suppressed-before-opening-quote",
         "description": "an opening delimiter still wants a leading space — deliberate "
                        "asymmetry with closing punctuation",
         "input": "\"quoted", "options": {"had_recent_injection": True}},
        {"id": "not-suppressed-before-opening-paren",
         "description": "a new clause starting with ( wants its space",
         "input": "(aside)", "options": {"had_recent_injection": True}},
        {"id": "empty-text-continuing",
         "description": "an empty burst after a recent injection",
         "input": "", "options": {"had_recent_injection": True}},
        {"id": "empty-text-fresh", "description": "an empty burst with no recent injection",
         "input": "", "options": {"had_recent_injection": False}},
        {"id": "leading-space-already-present",
         "description": "the separator is added blind, so text that already begins with a "
                        "space would be double-spaced. Unreachable in the real pipeline "
                        "(clean_text strips leading whitespace first) — pinned so a port "
                        "that calls the units in a different order knows the ordering matters",
         "input": " already spaced", "options": {"had_recent_injection": True}},
        {"id": "rtl-persian-continuing",
         "description": "RTL continuation still gets its separator",
         "input": "سلام", "options": {"had_recent_injection": True}},
    ],
    "stt.vocabulary": [
        {"id": "no-parts", "description": "nothing configured still primes the app name",
         "input": []},
        {"id": "all-none", "description": "explicit Nones behave like nothing configured",
         "input": [None, None]},
        {"id": "all-empty-strings", "description": "empty strings are not content",
         "input": ["", "   "]},
        {"id": "single-part", "description": "one configured vocabulary string",
         "input": ["Kubernetes, Prometheus"]},
        {"id": "two-parts-merged", "description": "configured prompt plus personal dictionary",
         "input": ["Kubernetes", "Grafana, Loki"]},
        {"id": "app-name-comes-first",
         "description": "the coined app name is primed AHEAD of user vocabulary so it is "
                        "not mis-transcribed (see stt/vocabulary.py)",
         "input": ["Kubernetes"]},
        {"id": "app-name-preamble-is-unconditional",
         "description": "the app-name preamble is prepended even when the user already "
                        "listed it, so it can appear twice. Harmless for prompt priming "
                        "(repetition only reinforces the spelling) and cheaper than a "
                        "substring check that could false-positive",
         "input": ["YazSes, Kubernetes"]},
        {"id": "none-between-parts", "description": "a None between real parts is skipped",
         "input": ["Kubernetes", None, "Grafana"]},
        {"id": "whitespace-part-skipped", "description": "a whitespace-only part is skipped",
         "input": ["Kubernetes", "   ", "Grafana"]},
        {"id": "rtl-persian-vocabulary", "description": "non-Latin vocabulary is preserved",
         "input": ["تهران، اصفهان"]},
    ],
    "commands.grammar": [
        {"id": "empty-string", "description": "empty input is dictation, never a command",
         "input": ""},
        {"id": "whitespace-only", "description": "whitespace-only input is dictation",
         "input": "   "},
        {"id": "plain-sentence-is-dictation",
         "description": "the default must always be DICTATE — typing a command by mistake "
                        "is recoverable, executing dictation by mistake is not",
         "input": "the quick brown fox jumps over the lazy dog"},
        {"id": "undo-that", "description": "a canonical single command",
         "input": "undo that"},
        {"id": "select-all", "description": "another canonical command",
         "input": "select all"},
        {"id": "save-file", "description": "save the current file",
         "input": "save file"},
        {"id": "go-to-line-digits", "description": "line number given as digits",
         "input": "go to line 42"},
        {"id": "go-to-line-numword",
         "description": "spoken number words are normalised to digits before matching",
         "input": "go to line seven"},
        {"id": "delete-last-word",
         "description": "singular form yields NO 'n' argument — the dispatcher defaults to 1. "
                        "A port must treat a missing 'n' as 1, not as 0 or an error",
         "input": "delete the last word"},
        {"id": "delete-last-three-words", "description": "word deletion with a spoken count",
         "input": "delete the last three words"},
        {"id": "undo-n-times", "description": "repeat count on undo",
         "input": "undo five times"},
        {"id": "trailing-punctuation-tolerated",
         "description": "Whisper adds a full stop; the grammar must still match — "
                        "otherwise commands work only when the model omits punctuation",
         "input": "undo that."},
        {"id": "leading-and-trailing-punctuation",
         "description": "outer punctuation is stripped before matching",
         "input": ", select all."},
        {"id": "case-insensitive-command",
         "description": "sentence-initial capitalisation must not defeat the grammar",
         "input": "Undo that"},
        {"id": "command-embedded-in-a-sentence",
         "description": "the grammar is whole-utterance: a command phrase inside real "
                        "prose must stay dictation, or the user cannot dictate about them",
         "input": "then I told him to undo that and he did"},
        {"id": "command-word-as-prose",
         "description": "'save file' discussed rather than commanded",
         "input": "the save file dialog was confusing"},
        {"id": "unknown-command-is-dictation",
         "description": "an unmatched imperative is typed, not guessed at",
         "input": "reticulate the splines"},
        {"id": "rtl-persian-is-dictation",
         "description": "non-English speech is dictation — the grammar is English-only today",
         "input": "سلام دنیا"},
        {"id": "numbers-in-dictation-stay-dictation",
         "description": "a sentence containing a number is not a go-to-line command",
         "input": "we shipped 42 features this year"},
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
