"""The Command Safety Gate wired into the daemon (ADR-v2-065, issue #164).

The pure classifier and the hold/release gate are covered in
`test_cmdsafety_spokenregex.py`. What is tested here is the promise the feature
makes to a user who turns it on: **a dictated `rm -rf` does not reach the shell**,
and the word that releases it does not get typed instead of running it.

The failure modes worth naming, because each one is a way a safety feature becomes
worse than not having it:

* Typing the word "confirm" into the terminal instead of running the held command.
* Treating "cancel the meeting" as a control word and never typing it.
* Leaving the daemon modal, so a user whose "confirm" was mis-heard finds dictation
  apparently dead with no way out.
* Changing behaviour for the 100% of installs that never enable it.
"""

from __future__ import annotations

from dataclasses import replace

from yazses.cmdsafety.spoken import match_control, normalise_utterance
from yazses.config import CmdsafetyConfig, Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform

DANGEROUS = "rm -rf /home/mohsen"


def _daemon(mocker, **cmdsafety):
    cfg = replace(Config(), cmdsafety=CmdsafetyConfig(enabled=True, **cmdsafety))
    d = Daemon(config=cfg, platform=get_platform())
    d._notify_cmdsafety = mocker.MagicMock()
    return d


# ---- the promise: a dangerous command does not type ------------------------


def test_a_dangerous_command_is_held_rather_than_typed(mocker):
    d = _daemon(mocker)
    event: dict = {}
    assert d._cmdsafety_gate(DANGEROUS, event) is None
    assert event["cmdsafety_action"] == "held"
    assert event["cmdsafety_reason"] == "recursive/forced delete"
    assert d._cmdsafety.pending == DANGEROUS


def test_an_ordinary_command_passes_straight_through(mocker):
    d = _daemon(mocker)
    event: dict = {}
    assert d._cmdsafety_gate("git status", event) == "git status"
    assert "cmdsafety_action" not in event
    assert d._cmdsafety.pending is None


def test_confirm_runs_the_held_command_and_does_not_type_the_word(mocker):
    """The bug this guards: injecting "confirm" into the shell instead of the command."""
    d = _daemon(mocker)
    d._cmdsafety_gate(DANGEROUS, {})
    event: dict = {}
    assert d._cmdsafety_gate("confirm", event) == DANGEROUS
    assert event["cmdsafety_action"] == "confirm"
    assert d._cmdsafety.pending is None


def test_cancel_discards_the_held_command_and_types_nothing(mocker):
    d = _daemon(mocker)
    d._cmdsafety_gate(DANGEROUS, {})
    event: dict = {}
    assert d._cmdsafety_gate("cancel", event) is None
    assert event["cmdsafety_action"] == "cancel"
    assert d._cmdsafety.pending is None


def test_an_unrelated_utterance_drops_the_hold_and_is_typed_normally(mocker):
    """No modal trap: a mis-heard confirm must not leave dictation apparently dead."""
    d = _daemon(mocker)
    d._cmdsafety_gate(DANGEROUS, {})
    event: dict = {}
    assert d._cmdsafety_gate("hello there", event) == "hello there"
    assert event["cmdsafety_action"] == "implicit_cancel"
    assert d._cmdsafety.pending is None, "the dangerous command must never survive"


def test_a_second_dangerous_command_is_itself_held(mocker):
    """Dropping the first hold must not let the second one through unguarded."""
    d = _daemon(mocker)
    d._cmdsafety_gate("mkfs /dev/sda1", {})
    event: dict = {}
    assert d._cmdsafety_gate(DANGEROUS, event) is None
    assert event["cmdsafety_action"] == "held"
    assert d._cmdsafety.pending == DANGEROUS


# ---- prose must not be eaten by an ordinary English word --------------------


def test_control_words_only_match_a_whole_utterance():
    """`re.search` here would swallow real dictation -- see #164's anchoring note."""
    for prose in (
        "cancel the meeting",
        "I can confirm that the build passed",
        "confirm the booking with them",
        "run it past the reviewer first",
    ):
        assert match_control(prose) is None, prose


def test_control_words_survive_punctuation_and_case():
    """Voice punctuation and ITN run before this, so "Confirm." is what arrives."""
    for spoken in ("Confirm.", " confirm ", "CONFIRM!", "confirm"):
        assert match_control(spoken) == "confirm", spoken
    assert match_control("Cancel.") == "cancel"


def test_configured_phrases_replace_the_defaults(mocker):
    d = _daemon(mocker, confirm_words=["do it now"])
    d._cmdsafety_gate(DANGEROUS, {})
    assert d._cmdsafety_gate("do it now", {}) == DANGEROUS


def test_emptying_the_confirm_words_falls_back_rather_than_bricking(mocker):
    """An empty list must not leave a held command with no way to release it."""
    d = _daemon(mocker, confirm_words=[])
    d._cmdsafety_gate(DANGEROUS, {})
    assert d._cmdsafety_gate("confirm", {}) == DANGEROUS


def test_a_bare_string_is_one_phrase_not_a_bag_of_letters():
    """`confirm_words = "confirm"` is the natural TOML to write; iterating it by
    character would make the release word the letter "c"."""
    assert match_control("confirm", confirm_words="confirm") == "confirm"
    assert match_control("c", confirm_words="confirm") is None


def test_normalise_is_unicode_safe():
    assert normalise_utterance("Ｃｏｎｆｉｒｍ") == "confirm"
    assert normalise_utterance("") == ""


# ---- the gate is actually on the dictation path ----------------------------


def test_the_gate_is_called_from_the_dictation_path_before_staging():
    """Every other test here calls `_cmdsafety_gate` directly, which proves the gate
    works and not that anything reaches it. `test_feature_wiring_honesty` proves the
    *package* is imported, which is also not the same thing -- an import satisfies it
    even if the call site is dead.

    So read the call sites out of `_on_hold_end` itself. The order is load-bearing and
    was a deliberate decision: staged dictation must not consume the confirm word as
    ordinary text before the gate can see it, so the gate has to run first.
    """
    import ast
    import inspect
    import textwrap

    from yazses.core.daemon import Daemon

    tree = ast.parse(textwrap.dedent(inspect.getsource(Daemon._on_hold_end)))
    calls = [
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"_cmdsafety_gate", "_stage_or_commit"}
    ]
    assert "_cmdsafety_gate" in calls, "the safety gate is never reached from _on_hold_end"
    assert calls.index("_cmdsafety_gate") < calls.index("_stage_or_commit"), (
        "the gate must run before staged dictation, or the staged buffer swallows "
        "the confirm word as ordinary text and the held command can never be released"
    )


# ---- off by default --------------------------------------------------------


def test_the_gate_is_off_by_default_and_constructed_inert():
    cfg = Config()
    assert cfg.cmdsafety.enabled is False
    d = Daemon(config=cfg, platform=get_platform())
    assert d._cmdsafety.pending is None
