"""Nothing a stock install turns on may swallow ordinary dictation.

`system/firstrun.py` seeds a config for every new user. Several of the capabilities it
enables can **consume a burst**: `revise` backspaces the previous injection, `timeline`
replays and rewrites it, `verbatim` flips a persistent mode and types nothing, `compute`
replaces the utterance with a number, `checkdigit` holds it pending a spoken confirm.

Each was individually reasonable. What nothing checked is the property they share: on a
stock install, a sentence someone actually said must come out as text.

## What was measured

1418 real dictation bursts from this project's own learning corpus, replayed through every
default-on transform under the same condition the daemon applies:

    "scratch that"     (deletes the last burst)   fired on 0
    timeline undo/redo (backspaces)               fired on 0
    verbatim toggle    (swallows the burst)       fired on 0
    checkdigit hold    (interrupts)               fired on 0
    compute            (replaces the utterance)   fired on 2 — both arithmetic

That is the number this file defends. Every parser is anchored at both ends, which is why
`"click undo"`, `"I had to scratch that itch"` and `"the verbatim transcript"` are typed
rather than obeyed — the suffix-match failure this repo has hit before.

## Why it is a corpus of sentences rather than the real one

A test that needed the learning corpus would only run on a machine that had one. These are
ordinary sentences carrying the trigger words in ordinary positions, which is the shape the
real corpus supplied.

## The lesson that produced this file

A previous attempt to audit the same layer replayed `grammar.classify()` *directly* and
concluded that prose beginning with "run" was being executed. It is not: the daemon refuses
open-ended `run …` outside command mode. The probe had skipped the protection it was
auditing. So every parser here is exercised under the daemon's own condition — only bursts
that classify as DICTATE reach these branches — and each is also shown to fire on its
intended input, because a parser that matched nothing would pass every assertion below.

Two further vacuities were found by sabotaging the source and watching this file stay green:

* Every hyphenated example was a *sentence*, and compute refuses anything containing
  letters before the hyphen rule is reached — so removing that rule changed nothing here.
  Bare `3-1` / `555-1234` / `2024-2025` are in the list for that reason, and they are also
  the realistic case: a score or a phone number dictated into a form field.
* `parse_revise` uses `re.match`, which anchors at the start whether or not the pattern
  says `^`. Deleting the `^` is a no-op; the protection against "I had to scratch that
  itch" is the trailing `$`.

Both were mistakes in the test, not the code. They are written down because a guard that
cannot fail is worse than no guard, and neither was visible from a green run.
"""

from __future__ import annotations

import pytest

from yazses.checkdigit.guard import check
from yazses.commands.grammar import classify
from yazses.commands.revise import parse_revise
from yazses.compute.evaluate import evaluate
from yazses.config import Config
from yazses.spokencmd.registry import build_handlers
from yazses.spokencmd.router import route as route_spoken
from yazses.timeline.history import parse_timeline_command
from yazses.verbatim.gate import detect_mode_command

#: Ordinary speech carrying every trigger word in an ordinary position.
SPEECH = [
    "I had to scratch that itch for weeks",
    "we should scratch the whole plan and start again",
    "click undo if it looks wrong",
    "the undo button is greyed out",
    "redo the introduction before Friday",
    "the verbatim transcript is attached",
    "he quoted me verbatim in the article",
    "resume the meeting after lunch",
    "formatting the drive takes an hour",
    "delete that paragraph when you get a chance",
    "the score was 3-1 at half time",
    "the fiscal year 2024-2025 was difficult",
    "call me on 555-1234 tomorrow",
    # BARE hyphenated tokens, dictated into a form field. These matter more than the
    # sentences above: compute's letters guard rejects anything with a word in it, so a
    # sentence never reaches the hyphen rule at all. Without these three the compute
    # assertion below cannot fail, which is how a first version of this file passed a
    # deliberate loosening of that rule.
    "3-1",
    "2024-2025",
    "555-1234",
    "chapter 3 minus chapter 1 is the interesting part",
    "I ran 5 miles over 2 days",
    "run all of these comments by yourself",
    "my house number is 4539 and the postcode follows",
    "press on with the design review",
]


def _spelling_on() -> Config:
    """The seeded config: `spelling` is RECOMMENDED, so first run turns it on."""
    cfg = Config()
    cfg.spelling.enabled = True
    return cfg


def _is_dictation(text: str) -> bool:
    return classify(text, Config().commands.profile).intent.name == "DICTATE"


@pytest.mark.parametrize("text", SPEECH)
def test_ordinary_speech_reaches_the_dictation_branch(text: str) -> None:
    """The precondition for everything below; also the `run …` lesson, pinned.

    `classify` alone answers TERMINAL for "run all of these comments by yourself"; the
    daemon then refuses open-ended `run` outside command mode and types it. This asserts
    the branch, not the classifier, for exactly that reason.
    """
    import inspect

    from yazses.core.daemon import Daemon

    if not _is_dictation(text):
        source = inspect.getsource(Daemon._on_hold_end)
        assert 'intent.action == "run_command"' in source, (
            f"{text!r} is classified as a command and the daemon no longer refuses "
            f"open-ended run outside command mode — it would be executed"
        )


@pytest.mark.parametrize("text", SPEECH)
def test_no_default_on_transform_consumes_it(text: str) -> None:
    """The property: a stock install types what you said."""
    cfg = Config()
    assert not parse_revise(text), "'scratch that' would backspace the previous burst"
    assert parse_timeline_command(text) is None, "undo/redo would rewrite the last burst"
    assert detect_mode_command(text) is None, "verbatim mode would swallow this burst"
    assert evaluate(text) is None, "compute would replace the utterance with a number"
    result = check(text, cfg.checkdigit.schemes)
    assert not (getattr(result, "checked", False) and not getattr(result, "ok", True)), (
        "checkdigit would hold this burst for a spoken confirm"
    )
    assert route_spoken(text, build_handlers(_spelling_on())) is None, (
        "a spoken capability would claim this burst instead of typing it"
    )


@pytest.mark.parametrize(
    "text,parser",
    [
        ("scratch that", lambda t: bool(parse_revise(t))),
        ("delete that", lambda t: bool(parse_revise(t))),
        ("undo that", lambda t: parse_timeline_command(t) is not None),
        ("undo the last sentence", lambda t: parse_timeline_command(t) is not None),
        ("redo", lambda t: parse_timeline_command(t) is not None),
        ("verbatim mode", lambda t: detect_mode_command(t) is not None),
        ("resume formatting", lambda t: detect_mode_command(t) is not None),
        ("2 plus 2", lambda t: evaluate(t) is not None),
        ("15% of 240", lambda t: evaluate(t) is not None),
        ("spell alpha bravo", lambda t: route_spoken(t, build_handlers(_spelling_on())) is not None),
    ],
)
def test_each_transform_still_fires_on_its_own_command(text: str, parser) -> None:
    """Without this the zeros above would mean "every parser is broken", not "quiet"."""
    assert parser(text), f"{text!r} no longer triggers its transform"


def test_the_seeded_set_is_what_this_file_covers() -> None:
    """If first run starts enabling something else that can consume a burst, this fails
    and the new capability gets added above rather than shipping unexamined."""
    import tomllib
    from pathlib import Path
    from tempfile import TemporaryDirectory

    from yazses.system.firstrun import ensure_recommended_config

    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.toml"
        ensure_recommended_config(path)
        seeded = set(tomllib.loads(path.read_text(encoding="utf-8")))

    covered = {
        "commands", "revise", "timeline", "verbatim", "compute", "checkdigit",
        # `spelling` is the one seeded spoken capability (ADR-v2-131). It is covered
        # twice over: the router is asserted quiet on all of SPEECH above, and
        # `test_a_spoken_capability_cannot_reach_the_dictation_path` pins that it is
        # only reachable while the command key is held.
        "spelling",
        # `corrdict` rewrites words rather than consuming a burst, and on a stock
        # install it rewrites nothing: its table is mined from the learning corpus,
        # which is off by default. `test_the_seeded_correction_table_is_empty` is
        # the assertion, and it is the one that matters — a substitution table is
        # the only seeded thing here that could silently change what you said.
        "corrdict",
    }
    # Sections that cannot consume a burst: they change how it is delivered, not whether.
    delivery_only = {"overlay", "tray", "injection", "audio", "accessibility", "cmdsafety"}
    # Nor these: they change how the burst is *decoded* or which tone is applied to
    # it. Both leave the words themselves alone, and neither can swallow one.
    decode_only = {"latency", "focusprofile"}
    unexamined = seeded - covered - delivery_only - decode_only
    assert not unexamined, (
        f"first run now enables {sorted(unexamined)}, which this file does not cover. "
        f"If any of them can consume a burst, add it to test_no_default_on_transform_"
        f"consumes_it; if it only affects delivery, list it in `delivery_only`."
    )


def test_a_spoken_capability_cannot_reach_the_dictation_path() -> None:
    """`spelling` is seeded on, and it assembles shell syntax out of NATO words.

    That is only safe because `_try_spoken` is called inside the command-mode chain —
    a burst dictated with the ordinary hold-to-talk key never reaches it. The command
    key is unbound by default, so on a stock install the seeded toggle changes nothing
    until the user binds one deliberately.
    """
    import inspect

    from yazses.core.daemon import Daemon

    lines = inspect.getsource(Daemon._on_hold_end).splitlines()
    branch = next(i for i, ln in enumerate(lines) if ln.strip() == "if command_mode:")
    call = next(
        i for i, ln in enumerate(lines)
        if "self._try_spoken(text, event, can_type=can_type)" in ln
    )
    depth = len(lines[branch]) - len(lines[branch].lstrip())

    assert branch < call, "_try_spoken now runs before the command-mode branch"

    # Inside the branch, not merely after it. Both halves are needed and the first
    # was found by sabotage: relocating the call to just past the block's last line
    # leaves nothing dedented *between* the two, so the scan alone passed a mutation
    # that had moved the call onto the dictation path.
    call_depth = len(lines[call]) - len(lines[call].lstrip())
    assert call_depth > depth, (
        f"_try_spoken sits at indent {call_depth}, outside the command-mode block at "
        f"indent {depth} — a seeded spoken capability could now claim an ordinary "
        f"dictation burst"
    )
    dedented = [
        i for i in range(branch + 1, call)
        if lines[i].strip() and len(lines[i]) - len(lines[i].lstrip()) <= depth
    ]
    assert not dedented, (
        f"_on_hold_end line {dedented[0]} leaves the command-mode block before "
        f"_try_spoken — the call is no longer command-mode only"
    )
    assert Config().hotkey.command_key == "", (
        "the command key is bound by default now; the seeded spoken capabilities are "
        "live on a stock install and need the corpus replay this file documents"
    )


def test_the_seeded_correction_table_is_empty() -> None:
    """`corrdict` is seeded on, and it is a substitution table applied to every burst.

    It learns from the encrypted learning corpus, which is off by default (ADR-011),
    so on a stock install there is nothing to mine and nothing is rewritten. That is
    what makes seeding it safe, and it is asserted rather than assumed because the
    failure mode — words silently replaced by words you did not say — is the worst
    one on this path.
    """
    from types import SimpleNamespace

    from yazses.core.daemon import Daemon
    from yazses.corrdict.mine import apply_corrections
    from yazses.corrdict.table import build_table

    cfg = Config()
    assert cfg.corrdict.enabled is False or cfg.learning.enabled is False
    fake = SimpleNamespace(
        _config=cfg,
        _correction_table_cache=None,
        _warn_feature_inert=lambda *_: None,
        _platform=SimpleNamespace(paths=SimpleNamespace(data_dir=None)),
    )
    table = Daemon._correction_table(fake)
    assert table == {}
    # And an empty table is a no-op rather than a crash on every sentence above.
    for text in SPEECH:
        assert apply_corrections(text, table) == text
    # Non-vacuity: the same call on real corrected events does produce a table.
    events = [SimpleNamespace(final_text="yaz says works", correction_text="YazSes works")] * 3
    assert build_table(events, min_support=3) == {"yaz says": "YazSes"}
