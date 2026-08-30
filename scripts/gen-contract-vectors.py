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
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from yazses.activation.confirm import (  # noqa: E402
    DEFAULT_CONFIRM_THRESHOLD,
    DEFAULT_REJECT_FLOOR,
    classify_consequence,
    decide,
)
from yazses.activation.intent import ActivationIntent, validate  # noqa: E402
from yazses.commands.grammar import classify  # noqa: E402
from yazses.config import DisfluencyConfig  # noqa: E402
from yazses.postprocess.cleaner import clean_text  # noqa: E402
from yazses.postprocess.spacing import continuation_prefix  # noqa: E402
from yazses.postprocess.voice_punctuation import apply_voice_punctuation  # noqa: E402
from yazses.stt.filters.disfluency import filter_transcript  # noqa: E402
from yazses.stt.vocabulary import merge_initial_prompt  # noqa: E402

CONTRACT_DIR = ROOT / "contract"
VECTOR_DIR = CONTRACT_DIR / "vectors"
CONTRACT_VERSION = (CONTRACT_DIR / "VERSION").read_text(encoding="utf-8").strip()


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


def _run_vad_gate(samples: list[float], options: dict[str, Any]) -> bool:
    """The calibrated silence gate: mean(|audio|) below the threshold is silence.

    Input is a plain list of floats rather than a WAV path, so the vector file
    stays readable and every port can run it without an audio decoder. The
    threshold is the same `[accessibility] vad_threshold` key the desktop uses.
    """
    import numpy as np

    from yazses.audio.vad_calibrated import is_silent_calibrated
    from yazses.config import AccessibilityConfig

    cfg = dataclasses.replace(AccessibilityConfig(), **options)
    return is_silent_calibrated(np.array(samples, dtype=np.float32), cfg)


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


def _run_activation(events: list[dict[str, Any]], options: dict[str, Any]) -> list[dict[str, Any]]:
    """Replay a source's event stream and report what the daemon must do (#139).

    We are inviting research groups to plug decoders into YazSes, and without an
    executable contract each of them integrates by reading our source and
    guessing. This unit is device-neutral on purpose: the input is a sequence of
    events any source could emit — onset, offset, intent — and the output is the
    decision for each, so a decoder written in any language can prove conformance
    without owning our pipeline.

    Deliberately excluded: the dispatched key sequence. That is
    platform-specific (see `platform/*/injector.py`), while act/confirm/reject is
    the shared policy.
    """
    vocabulary = tuple(options.get("vocabulary", ()))
    threshold = options.get("threshold", DEFAULT_CONFIRM_THRESHOLD)
    floor = options.get("floor", DEFAULT_REJECT_FLOOR)

    out: list[dict[str, Any]] = []
    holding = False
    for event in events:
        kind = event.get("kind")
        if kind == "onset":
            # A second onset without an offset is a stuck source, not a new hold.
            out.append({"event": "onset", "result": "ignored" if holding else "hold_start"})
            holding = True
        elif kind == "offset":
            out.append({"event": "offset", "result": "hold_end" if holding else "ignored"})
            holding = False
        elif kind == "disappear":
            # The source vanished (unplugged, crashed). Any open hold must be
            # closed, or the daemon records forever.
            out.append({"event": "disappear", "result": "hold_end" if holding else "ignored"})
            holding = False
        elif kind == "intent":
            intent = ActivationIntent(
                label=event.get("label", ""),
                confidence=event.get("confidence", 0.0),
                source=event.get("source", "contract"),
            )
            rejection = validate(intent, vocabulary)
            if rejection is not None:
                out.append({"event": "intent", "result": "refused",
                            "reason": rejection.name.lower()})
                continue
            command = classify(intent.label)
            action = command.action or ""
            if command.intent.value == "dictate" or not action:
                out.append({"event": "intent", "result": "refused",
                            "reason": "not_a_command"})
                continue
            decision = decide(
                intent.confidence, classify_consequence(action),
                threshold=threshold, floor=floor,
            )
            out.append({"event": "intent", "result": decision.value, "action": action})
        else:  # pragma: no cover - guarded by the schema test below
            raise SystemExit(f"unknown activation event kind: {kind!r}")
    return out


UNITS: dict[str, tuple[str, Callable[[Any, dict[str, Any]], Any]]] = {
    "sources.activation": (
        "src/yazses/activation/intent.py::validate + "
        "src/yazses/activation/confirm.py::decide",
        _run_activation,
    ),
    "audio.vad_gate": (
        "src/yazses/audio/vad_calibrated.py::is_silent_calibrated",
        _run_vad_gate,
    ),
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

_VOCAB = ["undo", "save", "copy", "paste", "delete the last word", "go to line 40"]

CASES: dict[str, list[dict[str, Any]]] = {
    # ── activation sources (#139) ──────────────────────────────────────────
    # The boring cases are here on purpose: the existing vector work found three
    # shipped bugs in the disfluency filter, and every one came from an ordinary
    # input rather than a clever one.
    "sources.activation": [
        {"id": "empty-stream", "description": "a source that emits nothing does nothing",
         "options": {"vocabulary": _VOCAB}, "input": []},
        {"id": "onset-offset-pair",
         "description": "the ordinary trigger: one hold, opened and closed",
         "options": {"vocabulary": _VOCAB},
         "input": [{"kind": "onset"}, {"kind": "offset"}]},
        {"id": "offset-without-onset",
         "description": "a stray release (source started mid-hold) must not end a hold",
         "options": {"vocabulary": _VOCAB}, "input": [{"kind": "offset"}]},
        {"id": "double-onset",
         "description": "a repeated onset is a stuck source, not a second hold",
         "options": {"vocabulary": _VOCAB},
         "input": [{"kind": "onset"}, {"kind": "onset"}, {"kind": "offset"}]},
        {"id": "source-disappears-mid-hold",
         "description": "unplugged while held: the hold must close, not record forever",
         "options": {"vocabulary": _VOCAB},
         "input": [{"kind": "onset"}, {"kind": "disappear"}]},
        {"id": "disappear-while-idle",
         "description": "a source vanishing with no hold open changes nothing",
         "options": {"vocabulary": _VOCAB}, "input": [{"kind": "disappear"}]},
        {"id": "confident-reversible-intent-acts",
         "description": "high confidence + undoable action: act without asking",
         "options": {"vocabulary": _VOCAB},
         "input": [{"kind": "intent", "label": "undo", "confidence": 0.97}]},
        {"id": "confident-irreversible-intent-confirms",
         "description": "consequence outranks confidence: save always asks first",
         "options": {"vocabulary": _VOCAB},
         "input": [{"kind": "intent", "label": "save", "confidence": 1.0}]},
        {"id": "unsure-reversible-intent-confirms",
         "description": "below the threshold, even a reversible action asks",
         "options": {"vocabulary": _VOCAB},
         "input": [{"kind": "intent", "label": "undo", "confidence": 0.6}]},
        {"id": "sub-chance-intent-rejected",
         "description": "below the floor the label is dropped, not prompted",
         "options": {"vocabulary": _VOCAB},
         "input": [{"kind": "intent", "label": "undo", "confidence": 0.2}]},
        {"id": "out-of-vocabulary-label-refused",
         "description": "a source may not ask for what it never declared",
         "options": {"vocabulary": _VOCAB},
         "input": [{"kind": "intent", "label": "format disk", "confidence": 0.99}]},
        {"id": "no-declared-vocabulary-refuses-every-intent",
         "description": "a trigger-only source (EMG squeeze) cannot emit intents",
         "options": {"vocabulary": []},
         "input": [{"kind": "intent", "label": "undo", "confidence": 0.99}]},
        {"id": "empty-label-refused",
         "description": "the boring one: a decoder emitting an empty string",
         "options": {"vocabulary": _VOCAB},
         "input": [{"kind": "intent", "label": "", "confidence": 0.99}]},
        {"id": "confidence-above-one-refused",
         "description": "an uncalibrated decoder reporting 1.4 is a bug, not certainty",
         "options": {"vocabulary": _VOCAB},
         "input": [{"kind": "intent", "label": "undo", "confidence": 1.4}]},
        {"id": "negative-confidence-refused",
         "description": "a negative probability is not a probability",
         "options": {"vocabulary": _VOCAB},
         "input": [{"kind": "intent", "label": "undo", "confidence": -0.5}]},
        {"id": "confidence-boundaries-are-inclusive",
         "description": "exactly at the floor confirms; exactly at the threshold acts",
         "options": {"vocabulary": _VOCAB},
         "input": [{"kind": "intent", "label": "undo", "confidence": 0.5},
                   {"kind": "intent", "label": "undo", "confidence": 0.9}]},
        {"id": "in-vocabulary-but-not-a-command",
         "description": "a declared label the grammar reads as prose is not typed",
         "options": {"vocabulary": ["hello there"]},
         "input": [{"kind": "intent", "label": "hello there", "confidence": 0.99}]},
        {"id": "intent-with-an-argument",
         "description": "a parameterised command keeps its argument through the seam",
         "options": {"vocabulary": _VOCAB},
         "input": [{"kind": "intent", "label": "go to line 40", "confidence": 0.95}]},
        {"id": "intent-during-a-hold",
         "description": "an intent mid-hold is decided on its own merits",
         "options": {"vocabulary": _VOCAB},
         "input": [{"kind": "onset"},
                   {"kind": "intent", "label": "undo", "confidence": 0.99},
                   {"kind": "offset"}]},
        {"id": "custom-thresholds-are-honoured",
         "description": "a source with published calibration may set its own gates",
         "options": {"vocabulary": _VOCAB, "threshold": 0.7, "floor": 0.3},
         "input": [{"kind": "intent", "label": "undo", "confidence": 0.75},
                   {"kind": "intent", "label": "undo", "confidence": 0.35}]},
    ],
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
        {"id": "blank-audio-doubled-not-recognized",
         "description": "two artefact markers back to back are not a match for any single "
                        "known artefact string, so the exact-match check leaves both alone",
         "input": "[BLANK_AUDIO] [BLANK_AUDIO]"},
        {"id": "blank-marker-lowercase-not-recognized",
         "description": "artefact matching is case-sensitive; a lowercase variant of the "
                        "marker slips through untouched",
         "input": "[blank_audio]"},
        {"id": "blank-marker-mixed-case-not-recognized",
         "description": "same case-sensitivity gap with a mixed-case variant",
         "input": "[Blank_Audio]"},
        {"id": "blank-parenthetical-inner-spaces-not-recognized",
         "description": "extra spaces inside the parenthetical artefact break the exact match",
         "input": "( blank )"},
        {"id": "blank-marker-preceded-by-word-kept",
         "description": "a word before the marker means the burst is no longer whole-artefact, "
                        "so it is kept — the mirror of the already-covered trailing-word case",
         "input": "extra [BLANK_AUDIO]"},
        {"id": "leading-ellipsis-and-period-combo",
         "description": "a unicode ellipsis immediately followed by an ascii period is still "
                        "one leading punctuation run",
         "input": "…."},
        {"id": "spaced-dot-run", "description": "dots separated by spaces are still a "
                        "punctuation-only burst",
         "input": ". . ."},
        {"id": "doubled-ellipsis-then-content",
         "description": "two consecutive ellipsis characters are stripped as one leading run",
         "input": "…… hello"},
        {"id": "blank-marker-surrounded-by-tabs-and-newlines",
         "description": "whitespace variety around the marker doesn't stop artefact stripping",
         "input": "\t\n[BLANK_AUDIO]\t\n"},
        {"id": "leading-dot-before-rtl-no-space",
         "description": "leading whitespace and a dot immediately butting against RTL text "
                        "with no space between them",
         "input": "   .سلام"},
        {"id": "trailing-period-after-rtl-kept",
         "description": "trailing punctuation after RTL text is untouched, mirroring the "
                        "ASCII trailing-punctuation rule",
         "input": "سلام ."},
        {"id": "emoji-alone-untouched", "description": "a lone emoji survives untouched",
         "input": "👍"},
        {"id": "leading-dot-then-emoji", "description": "leading period stripped, "
                        "astral-plane emoji stays",
         "input": ". 👍"},
        {"id": "leading-ellipsis-glued-to-emoji",
         "description": "no space between the stripped ellipsis and the emoji that follows",
         "input": "...🚀ship it"},
        {"id": "dot-and-trailing-whitespace-only",
         "description": "a lone dot plus trailing whitespace reduces to nothing",
         "input": ".  "},
        {"id": "single-dot-single-trailing-space",
         "description": "a lone dot plus exactly one trailing space also reduces to nothing",
         "input": ". "},
        {"id": "zero-width-space-survives",
         "description": "surprising: U+200B is invisible but Python does not consider it "
                        "whitespace, so it survives strip() and every check untouched",
         "input": "​"},
        {"id": "bom-prefixed-marker-not-recognized",
         "description": "surprising: a leading byte-order-mark is also invisible and also "
                        "not whitespace, so it breaks the exact-string artefact match — a "
                        "BOM-prefixed [BLANK_AUDIO] burst is delivered to the user as "
                        "literal text instead of being stripped",
         "input": "﻿[BLANK_AUDIO]"},
        {"id": "blank-marker-embedded-in-rtl-kept",
         "description": "RTL variant of the embedded-marker-is-kept rule",
         "input": "سلام [BLANK_AUDIO] دنیا"},
        {"id": "very-long-paragraph-leading-punctuation-stripped",
         "description": "correctness must hold at meeting-length input, not just short "
                        "bursts — leading punctuation is still stripped and the rest of a "
                        "long paragraph survives byte-for-byte",
         "input": ". " + ("the quick brown fox jumps over the lazy dog and then it runs "
                          "away before anyone can react ") * 34},
        {"id": "adjacent-artefact-markers-not-recognized",
         "description": "two different markers glued together with no separator are not a "
                        "single recognized artefact string and both survive",
         "input": "[INAUDIBLE][silence]"},
        {"id": "blank-marker-with-comma-prefix-kept",
         "description": "an embedded marker preceded by real words and a comma is kept, "
                        "another embedded variant",
         "input": "well, [BLANK_AUDIO] anyway"},
        {"id": "ideographic-space-is-real-whitespace",
         "description": "contrast with zero-width-space-survives: the full-width "
                        "ideographic space (U+3000) IS Unicode whitespace and is correctly "
                        "stripped from both ends",
         "input": "　hello　"},
        {"id": "nbsp-wrapped-marker-recognized",
         "description": "contrast with bom-prefixed-marker-not-recognized: a non-breaking "
                        "space (U+00A0) IS Unicode whitespace, so it's stripped before the "
                        "exact-match check and the artefact underneath is still recognized",
         "input": "\xa0[BLANK_AUDIO]\xa0"},
        {"id": "leading-dot-before-code-identifier",
         "description": "leading decode-artefact dot is stripped even when it's glued "
                        "directly to a code identifier with no space",
         "input": ".parse_config()"},
        {"id": "mixed-script-passthrough",
         "description": "a burst mixing Latin, Arabic and CJK script in one string has "
                        "nothing to strip and survives whole",
         "input": "hello مرحبا 你好"},
        {"id": "vertical-tab-and-form-feed-whitespace-only",
         "description": "less common ASCII whitespace controls (vertical tab, form feed) "
                        "are still whitespace-only",
         "input": "\v\f  "},
    ],
    "audio.vad_gate": [
        {"id": "empty-audio-is-silence",
         "description": "no samples cannot contain speech; delivering a Whisper "
                        "hallucination on an empty buffer is the failure this prevents",
         "input": []},
        {"id": "digital-silence",
         "description": "all-zero samples are below any threshold",
         "input": [0.0, 0.0, 0.0, 0.0]},
        {"id": "loud-speech-passes",
         "description": "ordinary speech level clears the default gate",
         "input": [0.2, -0.25, 0.18, -0.22]},
        {"id": "quiet-room-is-discarded",
         "description": "room tone below the threshold is discarded rather than "
                        "transcribed — the 'Silent audio -- discarding' path",
         "input": [0.0001, -0.0002, 0.00015, -0.0001]},
        {"id": "mean-not-peak",
         "description": "the metric is mean(|audio|), NOT peak. One loud click among "
                        "fifteen silent samples has a peak of 0.9 and a mean of 0.056, "
                        "so against a 0.1 gate the burst is silence — a door slam does "
                        "not make a burst worth transcribing",
         "options": {"vad_threshold": 0.1},
         "input": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                   0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.9]},
        {"id": "sign-is-ignored",
         "description": "absolute value, so a negative-going waveform is as loud as a "
                        "positive one",
         "input": [-0.2, -0.2, -0.2, -0.2]},
        {"id": "a-lower-threshold-passes-quieter-speech",
         "description": "the whole point of calibration: someone with a quiet voice "
                        "lowers the gate and their speech stops being discarded",
         "options": {"vad_threshold": 0.00005},
         "input": [0.0001, -0.0002, 0.00015, -0.0001]},
        {"id": "a-higher-threshold-rejects-ordinary-speech",
         "description": "and raising it too far discards real speech — the failure "
                        "mode `yazses mic-level` exists to diagnose",
         "options": {"vad_threshold": 0.5},
         "input": [0.2, -0.25, 0.18, -0.22]},
        {"id": "exactly-at-the-threshold-is-not-silence",
         "description": "the comparison is strictly less-than, so a burst exactly at "
                        "the gate is delivered rather than discarded",
         "options": {"vad_threshold": 0.2},
         "input": [0.2, -0.2, 0.2, -0.2]},
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
         "description": "an AMBIGUOUS multi-word filler is not relaxed at position 0: "
                        "'You know the meeting is at noon' can be a real sentence "
                        "addressed to someone, so it stays protected (#120 decision, "
                        "refined by #122 — the test is whether the filler contains a "
                        "hesitation particle, not whether it has several words)",
         "input": "You know the meeting is at noon"},
        {"id": "strips-sentence-initial-so-um",
         "description": "#122 case 1: 'so um' contains the hesitation particle 'um', so "
                        "it can never open a real sentence and IS relaxed at position 0 "
                        "— unlike 'you know'. Before #122 the blanket multi-word "
                        "exclusion left the whole phrase intact",
         "input": "So um the meeting is at noon"},
        {"id": "strips-sentence-initial-so-uh",
         "description": "'so uh' qualifies for the same reason as 'so um'",
         "input": "So uh the meeting is at noon"},
        {"id": "protects-sentence-initial-okay-so",
         "description": "#122 boundary decision: 'okay so' has NO hesitation particle — "
                        "it is two ordinary words and 'Okay so what do you think?' is a "
                        "legitimate message, so it stays protected",
         "input": "Okay so the meeting is at noon"},
        {"id": "strips-sentence-initial-filler-with-ellipsis",
         "description": "#122 case 2: Whisper writes a hesitation as 'Uh...'; the "
                        "trailing dot is sentence punctuation, not the dot in 'main.py', "
                        "so the code-token guard must not fire on it. The filler and its "
                        "own trailing punctuation both go",
         "input": "Uh... so I think"},
        {"id": "protects-sentence-final-capitalised-filler-with-dot",
         "description": "the trailing-dot relaxation must not reach 'Actually.' — it is "
                        "not a hesitation particle, so it stays protected (#122)",
         "input": "I think so. Actually."},
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
        {"id": "protects-err-as-a-verb",
         "description": "'err' is an ordinary English verb, so it is not a default filler "
                        "— this returned 'To is human' until #125. Mid-utterance and "
                        "lowercase, so no position-0 or capitalisation guard applies",
         "input": "To err is human"},
        {"id": "protects-sentence-initial-err",
         "description": "'Err on the side of caution' is an instruction, not a hesitation "
                        "— 'err' is excluded from the hesitation particles too (#125)",
         "input": "Err on the side of caution"},
        {"id": "strips-sentence-initial-ah",
         "description": "'ah' stays a filler where 'err' does not: it is an interjection in "
                        "every dictionary sense, so removing it costs tone, never meaning "
                        "(#125 decision)",
         "input": "Ah yes the meeting"},
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
        {"id": "unicode-identifier-survives-round-trip",
         "description": "non-ASCII identifiers are real code — Python 3 allows them and "
                        "codebases outside English use them. Any normalisation or "
                        "accent-stripping produces a name that does not exist, and the "
                        "failure surfaces at import time, far from dictation (#237)",
         "input": "the function is called naïve_bayes and the class is Ωmega"},
        {"id": "code-identifiers-keep-their-exact-shape",
         "description": "underscores, dots and command names must survive byte for byte; "
                        "the filler guard already protects them and this pins the "
                        "guarantee rather than the implementation detail (#240)",
         "input": "call get_user_by_id in main.py then check the kubectl output"},
        {"id": "hedge-word-basically-is-not-a-filler-by-default",
         "description": "'it seems basically correct' is a hedge and 'it seems correct' is a "
                        "claim. #146 removed like/right/actually for exactly this reason; "
                        "basically and literally were missed (#236)",
         "input": "it seems basically correct and literally zero errors"},
        {"id": "trailing-filler-leaves-no-orphan-comma",
         "description": "removing a filler must not strand the punctuation around it — this "
                        "returned 'this is probably fine,' with a dangling comma typed into "
                        "the document (#236)",
         "input": "this is probably fine, you know"},
        {"id": "parenthetical-filler-takes-both-its-commas",
         "description": "'the tests, you know, are slow' returned 'the tests, are slow' — a "
                        "comma between subject and verb, because only the closing comma was "
                        "consumed (#236)",
         "input": "the tests, you know, are slow"},
        {"id": "sentence-opening-with-a-trigger-is-not-a-correction",
         "description": "every phrase in the default trigger list is ordinary English in "
                        "some sentence. This returned 'file when you are done' — the whole "
                        "first half deleted, and the remainder reads as fluent text the "
                        "user never said (#302)",
         "input": "delete that file when you are done"},
        {"id": "opening-trigger-with-its-pause-is-a-correction",
         "description": "the same words with the pause Whisper writes as punctuation really "
                        "are a correction, so the fix cannot be 'stop rolling back' (#302)",
         "input": "scratch that. meet at four"},
        {"id": "self-correction-governed-by-a-modal-is-prose",
         "description": "the mid-sentence half of #302: 'you should never mind the "
                        "warning' has text in front of the trigger, so "
                        "'nothing to roll back' does not apply — but 'should' makes the "
                        "trigger part of the verb phrase, and a correction is an "
                        "interjection that never continues the clause it interrupts",
         "input": "you should never mind the warning"},
        {"id": "self-correction-after-an-auxiliary-is-prose",
         "description": "same signal, different auxiliary (#302)",
         "input": "we can forget that idea"},
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
         "description": "a reporting verb makes the trigger quoted rather than performed, so "
                        "the sentence is prose and survives whole. This vector used to record "
                        "the opposite as 'whatever the shipped behaviour is', which froze a "
                        "meaning-destroying rollback into the contract every platform copies",
         "input": "he said never mind the cost and left"},
        {"id": "self-correction-trigger-after-a-subject-pronoun",
         "description": "a nominative pronoun immediately before the trigger makes the "
                        "trigger the clause's own verb, so the sentence is prose. Rolling "
                        "back left 'the noise from the street' -- fluent text the user "
                        "never said, with the meaning inverted",
         "input": "they never mind the noise from the street"},
        {"id": "self-correction-trigger-after-we",
         "description": "same rule, second person plural, and a gerund rather than a noun "
                        "phrase after the trigger",
         "input": "we never mind waiting for the next train"},
        {"id": "self-correction-after-an-object-pronoun-still-rolls-back",
         "description": "the boundary of the rule above, and why 'it' and 'you' are absent "
                        "from the guard: they are objects as well as subjects, and here 'it' "
                        "is the object being replaced by a genuine correction",
         "input": "i think we should ship it never mind lets wait"},
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
        {"id": "pathological-repetition-four-words-only-half-collapses",
         "description": "surprising: Rule B's 2-gram dedup removes one repeated pair per "
                        "pass over the window it matches; four verbatim repeats of 'the' "
                        "collapse to two, not one",
         "input": "the the the the"},
        {"id": "pathological-repetition-five-words-partial-collapse",
         "description": "an odd repeat count leaves an even stranger remainder — the same "
                        "windowed dedup only removes the first matching pair, leaving three",
         "input": "the the the the the"},
        {"id": "pathological-repetition-fully-collapses-with-repetition-collapse-enabled",
         "description": "shows the full pipeline order: Rule B first shrinks five 'the's to "
                        "three survivors, then Rule B.5's unigram rule (which needs a run "
                        ">= 3) finally collapses them to one",
         "input": "the the the the the", "options": {"collapse_repetitions": True}},
        {"id": "hyphenated-repeat-of-content-word-survives-intact",
         "description": "a stutter on a content word survives intact: 'actually' left the "
                        "default filler list in #146, so Rule A no longer reaches inside "
                        "the hyphenated token 'a-a-actually' and the disfluent-but-meaningful "
                        "token is delivered as spoken",
         "input": "a-a-actually the meeting"},
        {"id": "hyphenated-repeat-of-default-filler-survives-intact",
         "description": "a stutter on a word that happens to be a default filler is left "
                        "exactly as spoken: 'b-b-basically' has a non-filler part, so Rule A "
                        "refuses to open the token rather than eating 'basically' out of its "
                        "middle and gluing 'b-b-' onto the next word (#144)",
         "input": "b-b-basically the meeting"},
        {"id": "hyphenated-token-of-only-fillers-is-dropped-whole",
         "description": "'um-um' is entirely filler, so the whole token goes — removing each "
                        "'um' independently is what used to leave an orphaned hyphen glued "
                        "to the next word (#144)",
         "input": "um-um the meeting"},
        {"id": "hyphenated-real-word-survives-a-filler-part",
         "description": "regression guard for #144 beyond stutters: with 'right' configured "
                        "as a filler, 'right-click' must survive whole rather than becoming "
                        "'-click' — a hyphenated token is only removed when every part of it "
                        "is a filler",
         "input": "right-click the icon",
         "options": {"filler_words": ["um", "uh", "right"]}},
        {"id": "self-correction-trigger-with-own-period-leaves-no-punctuation",
         "description": "a trigger spoken as a complete sentence takes its own period with "
                        "it: Rule C consumes the punctuation belonging to the trigger clause, "
                        "so no bare '. ' is deposited mid-output (#145)",
         "input": "send it to Bob. delete that. send it to Alice"},
        {"id": "self-correction-resolved-in-text-order",
         "description": "triggers resolve in the order they were spoken, not the order they "
                        "happen to sit in the config list — 'scratch that' is applied first "
                        "here even though 'no wait' is declared earlier (#145)",
         "input": "scratch that. no wait meet at four"},
        {"id": "self-correction-three-trigger-chain-resolves-cleanly",
         "description": "a three-clause chain resolves in text order and leaves no orphaned "
                        "punctuation behind (#145)",
         "input": "meet at three. scratch that. no wait meet at four"},
        {"id": "self-correction-forget-that-trigger",
         "description": "exercises the 'forget that' trigger, and pins that its own period "
                        "is consumed with it (#145)",
         "input": "the budget is fine. forget that. the budget is tight"},
        {"id": "self-correction-strike-that-trigger",
         "description": "exercises the 'strike that' trigger, and pins that its own period "
                        "is consumed with it (#145)",
         "input": "draft one is done. strike that. draft two is done"},
        {"id": "self-correction-delete-that-no-period-clean",
         "description": "contrast case: 'delete that' with no period glued to it rolls back "
                        "cleanly, with none of the dangling punctuation from the case above",
         "input": "send it to Bob delete that send it to Alice"},
        {"id": "filler-attached-to-trailing-period-protected",
         "description": "surprising: a lowercase trailing filler glued directly to a period "
                        "is treated as a protected code/path-like token because of the "
                        "embedded dot, so it survives — even though the same filler with no "
                        "period is removed",
         "input": "meeting at noon um."},
        {"id": "filler-attached-to-comma-and-period-protected",
         "description": "same trailing-dot protection, with an extra clause before it",
         "input": "the meeting is at noon, um."},
        {"id": "filler-newline-separated-still-removed",
         "description": "contrast with the trailing-dot cases above: a filler on its own "
                        "line has a bare enclosing token (no glued punctuation) and is "
                        "removed normally",
         "input": "the meeting is at noon\num"},
        {"id": "filler-bare-trailing-removed",
         "description": "contrast pair: the same filler word is removed both at position 0 "
                        "and, since it's bare with no glued dot, at the very end too",
         "input": "um the meeting is at noon um"},
        {"id": "capitalized-multiword-filler-survives-at-start-not-mid-sentence",
         "description": "'sort of' and 'kind of' both left the default filler list in #146 "
                        "(they are hedges of certainty, not hesitation), so neither position "
                        "is touched any more and the qualified sentence is delivered whole",
         "input": "Sort of, kind of, the meeting is at noon"},
        {"id": "capitalized-multiword-default-filler-survives-at-start-not-mid-sentence",
         "description": "the position-0 rule on a multi-word filler that is still a default: "
                        "'You know' has no hesitation particle, so it's protected at the "
                        "start — but the later lowercase 'i mean' is an ordinary mid-sentence "
                        "filler and is removed",
         "input": "You know, i mean, the meeting is at noon"},
        {"id": "uppercase-filler-mid-sentence-protected",
         "description": "contrast with the position-0 relaxation: an all-caps filler "
                        "mid-sentence stays protected because the capitalization guard "
                        "only relaxes at position 0",
         "input": "the meeting is UM today"},
        {"id": "lowercase-filler-word-opens-real-phrase",
         "description": "the #146 fix seen from the other side: 'like' opening a real phrase "
                        "used to be stripped by the position-0 rule regardless of meaning. It "
                        "is no longer a default filler, so the simile survives",
         "input": "like a diamond in the sky"},
        {"id": "lowercase-default-filler-opens-real-phrase",
         "description": "text that only looks like content but isn't protected: a real "
                        "phrase beginning with the lowercase word 'literally' is still "
                        "stripped as a filler, because the position-0 exception only "
                        "protects capitalized tokens",
         "input": "literally a diamond in the sky"},
        {"id": "looks-like-filler-plural-survives",
         "description": "the exact case from issue #83: 'Um' at position 0 is stripped as "
                        "an unambiguous filler, but 'ums' (plural) is a different word and "
                        "the word-boundary regex correctly leaves it alone",
         "input": "Um is a word in this sentence about ums"},
        {"id": "filler-only-protected-at-position-zero-not-elsewhere",
         "description": "'right' left the default list in #146 (it is the predicate in "
                        "'not right'), so it survives at position 0 — while 'okay so', still "
                        "a default filler, is stripped because it isn't at position 0",
         "input": "right okay so the meeting"},
        {"id": "default-filler-only-protected-at-position-zero-not-elsewhere",
         "description": "'hmm' is only ever protected when capitalized at position 0; here "
                        "it's lowercase, so it's stripped, and 'okay so' (itself in the "
                        "filler list) is stripped too since it isn't at position 0 either",
         "input": "hmm okay so the meeting"},
        {"id": "self-correction-inside-rtl-text",
         "description": "an English trigger phrase embedded between two Persian clauses is "
                        "still recognized and the rollback still works",
         "input": "سلام. no wait سلام دوباره"},
        {"id": "mixed-script-filler-removal",
         "description": "filler removal is purely lexical/ASCII, so it works identically "
                        "inside a non-Latin sentence",
         "input": "日本語 um テスト"},
        {"id": "filler-inside-apostrophe-contraction",
         "description": "filler removal next to an apostrophe-bearing foreign phrase",
         "input": "c'est um la vie"},
        {"id": "every-default-hesitation-particle-in-one-burst",
         "description": "every default hesitation particle back to back in one utterance",
         "input": "um, uh, er, ah, hmm, the meeting"},
        {"id": "all-caps-filler-at-start-still-relaxed",
         "description": "a full-caps position-0 filler is still recognized as unambiguous "
                        "and stripped; the rest of the (also all-caps) sentence is untouched",
         "input": "UM THE MEETING IS AT NOON"},
        {"id": "nested-self-correction-and-code-identifier-guard",
         "description": "nested/overlapping disfluencies in one utterance: a filler inside "
                        "a code identifier must stay protected while a later self-correction "
                        "trigger still rolls back correctly",
         "input": "call basically_fn in um main.py, no wait, call other_fn"},
        {"id": "filler-word-as-url-path-segment",
         "description": "a filler word occupying its own path segment, with no leading "
                        "'um' this time, must still survive as part of the URL",
         "input": "the URL is https://example.com/basically/ok"},
        {"id": "disabled-bypasses-repetition-and-self-correction-too",
         "description": "enabled=false is a total no-op, not just a Rule A bypass — "
                        "repetition, dedup and self-correction triggers all pass through too",
         "input": "um um the the the, no wait, scratch that",
         "options": {"enabled": False}},
        {"id": "sentence-that-is-only-a-lowercase-multiword-filler",
         "description": "a lowercase multi-word filler with no protection-triggering "
                        "capitalization is removed even though it's the entire utterance",
         "input": "you know"},
        {"id": "long-input-kitchen-sink-fillers-dedup-and-self-correction",
         "description": "a ~500-word paragraph combining repeated fillers, a multi-word "
                        "filler, pathological word repetition, and a self-correction, to "
                        "prove the three-pass filter stays correct at meeting length, not "
                        "just on short bursts",
         "input": ("um so the quarterly report is you know basically finished. " * 48)
                  + "the the the the final number is forty two. no wait scratch that "
                  + "the final number is forty three."},
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
        {"id": "undo-alone-is-a-command",
         "description": "the bare word is the command, and must stay one (#235)",
         "input": "undo"},
        {"id": "undo-inside-a-sentence-is-dictation",
         "description": "'undo' is an ordinary English verb first; a grammar that "
                        "matched it anywhere would fire a keystroke instead of "
                        "typing the instruction (#235)",
         "input": "undo the last three commits before you deploy"},
        {"id": "run-alone-is-a-terminal-command",
         "description": "`run <anything>` is a real command — the daemon gates it "
                        "to command mode, but the grammar still recognises it",
         "input": "run kubectl get pods"},
        {"id": "run-inside-a-sentence-still-matches-the-grammar",
         "description": "pins WHY the daemon gate exists: `^run (.+)$` cannot tell a "
                        "shell command from an English clause, because the clause is "
                        "the argument. The safety decision belongs to the caller",
         "input": "run the numbers again before Friday"},
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
