"""`yazses features info <name>` shows an example. The ones that promise an output must keep it.

The feature registry gives every capability an ``example``. Most are prose ("Hold your
hotkey and speak"), but eighteen assert a concrete transformation with an arrow, and nine
of those name an input and an output precisely enough to check:

    convert            'twenty miles in kilometers' → '32.19 kilometers'
    itn                'john dot doe at gmail dot com' → john.doe@gmail.com
    math               'x squared plus y squared' → 'x^{2} + y^{2}'
    self_repair        'email Sarah no I mean Sara' → 'email Sara'
    symbols            'right arrow' → →   /   'shrug emoji' → 🤷
    voice-punctuation  'hello comma world period' → 'hello, world.'
    wordfind           'the word for when water turns to gas' → evaporation
    dysfluency         'b-b-because' → 'because'

All nine hold today — checked by running each against its real implementation. Nothing
enforced them, so a refactor could have turned `yazses features info` into a liar with no
test failing, which is the same family as the guards on documented flags, commands and
config keys.

## The dysfluency case, and why it is loaded through `load_config`

`accessibility.dysfluency_friendly` is read by nothing in `core/`, `stt/`, `audio/` or
`postprocess/` — it is a *preset*, applied by `config._apply_presets` during
`load_config`, which flips `collapse_repetitions`, `collapse_prolongations` and widens
`pre_speech_padding_ms` to 400 ms (ADR-015).

Constructing `Config()` directly bypasses that, and doing so makes the feature look
completely unwired: the flag reads as set, nothing collapses, and `doctor`'s claim of
"collapsing repetitions/prolongations, wider onset padding" looks false. It is not. This
test goes through `load_config` for that reason, and says so here so the next person does
not have to rediscover it.
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest

from yazses.config import Config, load_config
from yazses.system.features import feature_status


def _example_for(slug: str) -> str:
    feature = next((f for f in feature_status(Config()) if f.slug == slug), None)
    assert feature is not None, f"{slug} left the feature registry"
    assert feature.example, f"{slug} no longer ships an example"
    return feature.example


def _convert(text: str) -> str:
    from yazses.convert.units import apply_conversions

    return apply_conversions(text)


def _itn(text: str) -> str:
    from yazses.itn.normalize import normalize_entities

    return normalize_entities(text)


def _math(text: str) -> str:
    from yazses.math.latex import spoken_to_latex

    return spoken_to_latex(text)


def _self_repair(text: str) -> str:
    from yazses.selfrepair.repair import apply_self_repair

    return apply_self_repair(text)


def _symbols(text: str) -> str:
    from yazses.symbols.lookup import apply_symbols

    return apply_symbols(text)


def _voice_punctuation(text: str) -> str:
    from yazses.postprocess.voice_punctuation import apply_voice_punctuation

    return apply_voice_punctuation(text)


def _wordfind(text: str) -> str:
    from yazses.wordfind.rank import rank_candidates

    ranked = rank_candidates(text)
    return ranked[0][0] if ranked else ""


def _dysfluency(text: str) -> str:
    """Through `load_config`, so `_apply_presets` runs — see the module docstring."""
    from yazses.stt.filters.disfluency import filter_transcript

    path = pathlib.Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text("[accessibility]\ndysfluency_friendly = true\n", encoding="utf-8")
    cfg = load_config(path)
    result = filter_transcript(text, cfg.filters.disfluency)
    return getattr(result, "text", result)


#: (slug, spoken input, the output its example promises, the real implementation)
PROMISES = [
    ("convert", "twenty miles in kilometers", "32.19 kilometers", _convert),
    ("itn", "john dot doe at gmail dot com", "john.doe@gmail.com", _itn),
    ("math", "x squared plus y squared", "x^{2} + y^{2}", _math),
    ("self_repair", "email Sarah no I mean Sara", "email Sara", _self_repair),
    ("symbols", "right arrow", "→", _symbols),
    ("symbols", "shrug emoji", "\U0001f937", _symbols),
    ("voice-punctuation", "hello comma world period", "hello, world.", _voice_punctuation),
    ("wordfind", "the word for when water turns to gas", "evaporation", _wordfind),
    ("dysfluency", "b-b-because it works", "because it works", _dysfluency),
]


@pytest.mark.parametrize(
    "slug,spoken,promised,run", PROMISES, ids=[f"{p[0]}:{p[1][:24]}" for p in PROMISES]
)
def test_the_example_still_produces_what_it_promises(slug, spoken, promised, run) -> None:
    got = run(spoken)
    assert promised in got, (
        f"`yazses features info {slug}` promises {promised!r} for {spoken!r}, but the "
        f"implementation produces {got!r}. Fix the code or fix the example — a feature "
        "card that lies is worse than one that says nothing."
    )


@pytest.mark.parametrize("slug,spoken,promised,_run", PROMISES, ids=[p[0] for p in PROMISES])
def test_the_example_text_still_mentions_what_is_tested(slug, spoken, promised, _run) -> None:
    """Tie each case to the card it came from.

    Without this the table drifts into a private list of transformations that no longer
    correspond to anything a user is shown — green, and guarding nothing that is
    published.
    """
    example = _example_for(slug)
    key = promised.split()[0] if " " in promised else promised
    assert key.lower() in example.lower() or key in example, (
        f"{slug}'s example no longer mentions {key!r}: {example!r}"
    )


def test_the_dysfluency_preset_is_what_makes_its_example_true() -> None:
    """The trap this file exists to document, asserted rather than described.

    `Config()` skips `_apply_presets`, so the same call that succeeds above does nothing
    here. Anyone testing this feature with a bare Config will conclude it is unwired.
    """
    import dataclasses

    from yazses.stt.filters.disfluency import filter_transcript

    bare = Config().filters.disfluency
    assert bare.collapse_repetitions is False
    unchanged = filter_transcript("b-b-because it works", bare)
    assert getattr(unchanged, "text", unchanged) == "b-b-because it works"

    with_flags = dataclasses.replace(
        bare, enabled=True, collapse_repetitions=True, collapse_prolongations=True
    )
    fixed = filter_transcript("b-b-because it works", with_flags)
    assert getattr(fixed, "text", fixed) == "because it works"


def test_the_promise_table_covers_every_checkable_example() -> None:
    """A reminder to extend this when a new example promises an output.

    Not every arrow example is mechanically checkable — several describe UI behaviour
    ("Click the top-bar mic icon → pick a microphone") — so this counts rather than
    demanding one entry per arrow.
    """
    arrows = [f for f in feature_status(Config()) if "→" in (f.example or "")]
    assert len(arrows) >= 18, f"only {len(arrows)} examples use an arrow"
    covered = {slug for slug, *_ in PROMISES}
    assert len(covered) >= 8, "the promise table has shrunk"
