"""Offline Command Mode — rewrite the selection by voice (#99).

Fake clipboard, fake model, fake injector: no desktop, no GGUF, no network.

The acceptance criterion that gets the most tests is the one that matters most —
**a failed or unsafe rewrite never destroys the selection.** A rewrite replaces
text the user already wrote, so getting it wrong is not a worse suggestion, it is
lost writing.
"""

from __future__ import annotations

import pytest

from yazses.commands.rewrite import check_rewrite, parse_rewrite
from yazses.rewrite.engine import rewrite_selection

SELECTION = "The quick brown fox jumps over the lazy dog, and then it runs away fast."


def _run(said, model=None, selection=SELECTION, fallback="", injector=None):
    intent = parse_rewrite(said)
    assert intent is not None, f"{said!r} should parse"
    typed, saved = [], []
    outcome = rewrite_selection(
        intent,
        read_selection=lambda: selection,
        # Inside the "shorter" band (65% of the selection). The first version of
        # this fixture returned 24%, and the guard correctly rejected it — which
        # is the guard working, not a bug.
        rewrite=model or (lambda instruction, text: "The fox jumped the dog and ran off."),
        inject=injector or typed.append,
        save_original=lambda t: saved.append(t) or True,
        fallback_text=fallback,
    )
    return outcome, typed, saved


# ---- the grammar -----------------------------------------------------------


@pytest.mark.parametrize(("said", "action"), [
    ("make this shorter", "shorter"),
    ("make it much shorter", "shorter"),
    ("rewrite this longer", "longer"),
    ("make this more detailed", "longer"),
    ("fix the grammar", "grammar"),
    ("correct the spelling", "grammar"),
    ("fix typos", "grammar"),
    ("turn this into bullet points", "bullets"),
    ("make this into a bulleted list", "bullets"),
    ("make this more formal", "formal"),
    ("make it casual", "casual"),
])
def test_the_spoken_forms_people_use_are_recognised(said, action):
    assert parse_rewrite(said).action == action


def test_a_free_form_instruction_is_carried_through():
    intent = parse_rewrite("rewrite this as a polite refusal")
    assert intent.action == "custom"
    assert "polite refusal" in intent.instruction


@pytest.mark.parametrize("said", [
    "I need to make this shorter before the meeting",
    "she said we should fix the grammar in chapter two",
    "make this shorter than that one and then send it",
    "",
    "hello there",
])
def test_ordinary_speech_is_dictated_not_executed(said):
    """Anchored at both ends — the failure this project has had three times."""
    assert parse_rewrite(said) is None


def test_trailing_punctuation_does_not_defeat_the_match():
    assert parse_rewrite("make this shorter.") is not None


# ---- the guards ------------------------------------------------------------


def test_a_longer_result_is_refused_for_shorter():
    intent = parse_rewrite("make this shorter")
    assert check_rewrite("short text", "a very much longer text " * 10, intent)


def test_a_gutted_result_is_refused_for_grammar():
    """Halving the text is deletion, not correction."""
    intent = parse_rewrite("fix the grammar")
    assert check_rewrite(SELECTION, "The fox.", intent)


def test_a_chat_preamble_is_refused():
    """"Sure, here is a shorter version:" means it answered instead of working."""
    intent = parse_rewrite("make this shorter")
    assert check_rewrite(SELECTION, "Sure, here is a shorter version: the fox ran.", intent)


def test_empty_and_unchanged_results_are_refused():
    intent = parse_rewrite("make this shorter")
    assert check_rewrite(SELECTION, "", intent)
    assert check_rewrite(SELECTION, SELECTION, intent)


def test_a_plausible_rewrite_is_accepted():
    intent = parse_rewrite("make this shorter")
    assert check_rewrite(SELECTION, "The fox jumped the dog and ran off.", intent) is None


def test_each_action_carries_its_own_band():
    """"summarise" and "fix typos" are not the same operation."""
    assert parse_rewrite("make this shorter").max_ratio < 1.0
    assert parse_rewrite("rewrite this longer").min_ratio > 1.0


# ---- the selection is never destroyed --------------------------------------


def test_a_refused_rewrite_types_nothing():
    outcome, typed, _ = _run("make this shorter", model=lambda i, t: "x")
    assert not outcome.ok
    assert typed == [], "a refusal must not touch the document"


def test_a_model_error_types_nothing():
    def boom(instruction, text):
        raise RuntimeError("llama exploded")

    outcome, typed, _ = _run("make this shorter", model=boom)
    assert not outcome.ok and typed == []
    assert "failed" in outcome.reason


def test_a_model_timeout_types_nothing():
    def stall(instruction, text):
        raise TimeoutError

    outcome, typed, _ = _run("make this shorter", model=stall)
    assert not outcome.ok and typed == []
    assert "timed out" in outcome.reason


def test_the_original_is_saved_before_the_risky_step():
    """The undo path must exist before the rewrite, not after it."""
    _, _, saved = _run("make this shorter")
    assert saved == [SELECTION]


def test_the_original_is_saved_even_when_the_rewrite_is_refused():
    _, _, saved = _run("make this shorter", model=lambda i, t: "")
    assert saved == [SELECTION], "the undo path must survive a refusal"


def test_an_injection_failure_is_reported_rather_than_swallowed():
    def bad_injector(text):
        raise RuntimeError("no window")

    outcome, _, _ = _run("make this shorter", injector=bad_injector)
    assert not outcome.ok and "could not type" in outcome.reason


# ---- selection sources -----------------------------------------------------


def test_nothing_selected_falls_back_to_the_last_dictation():
    """The same affordance Punch-In gives, so the command still means something."""
    outcome, typed, _ = _run("make this shorter", selection="", fallback=SELECTION)
    assert outcome.ok and typed


def test_nothing_selected_and_nothing_dictated_is_a_clean_no_op():
    outcome, typed, _ = _run("make this shorter", selection="", fallback="")
    assert not outcome.ok and typed == []
    assert "nothing is selected" in outcome.reason


def test_a_clipboard_that_raises_is_treated_as_no_selection():
    intent = parse_rewrite("make this shorter")

    def broken():
        raise OSError("no display")

    outcome = rewrite_selection(
        intent, read_selection=broken, rewrite=lambda i, t: "x",
        inject=lambda t: pytest.fail("must not type"), fallback_text="",
    )
    assert not outcome.ok


# ---- what the user is told -------------------------------------------------


def test_success_reports_the_action_and_the_latency():
    outcome, _, _ = _run("make this shorter")
    assert "shorter" in outcome.message and "ms" in outcome.message


def test_a_refusal_says_the_text_was_left_alone():
    outcome, _, _ = _run("make this shorter", model=lambda i, t: "")
    assert "unchanged" in outcome.message


# ---- the clipboard read path ------------------------------------------------


def test_read_selection_prefers_primary_then_clipboard(monkeypatch):
    """PRIMARY must be tried before CLIPBOARD — highlighting is the gesture.

    The tool lookup is stubbed rather than inherited from the host. `read_selection`
    builds its candidate commands with `shutil.which`, so on a machine without
    xclip/xsel/wl-paste it produces *no* commands at all, the injected runner is
    never called, and this test cannot see the ordering it exists to check. That is
    not hypothetical: it passed on developer machines and failed on all six CI jobs,
    because GitHub's runners ship none of those tools.

    WAYLAND_DISPLAY is cleared for the same reason — otherwise the assertion would
    exercise whichever of the two branches the host happens to be in.
    """
    from yazses.system import clipboard

    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(clipboard.shutil, "which", lambda tool: f"/usr/bin/{tool}")

    calls = []

    class _R:
        stdout = b""

    def runner(cmd, **kw):
        calls.append(cmd)
        return _R()

    clipboard.read_selection(runner=runner)

    assert calls, "no clipboard command was attempted at all"
    joined = " ".join(" ".join(c) for c in calls)
    assert "primary" in joined, "PRIMARY must be tried — highlighting is the gesture"

    # Ordering is the actual invariant: PRIMARY has to be asked before CLIPBOARD,
    # not merely somewhere in the list.
    first_primary = next(i for i, c in enumerate(calls) if "primary" in " ".join(c))
    clipboards = [i for i, c in enumerate(calls) if "clipboard" in " ".join(c)]
    assert clipboards, "CLIPBOARD must still be tried as the fallback"
    assert first_primary < clipboards[0], (
        f"CLIPBOARD was tried before PRIMARY: {calls}"
    )


def test_get_clipboard_never_raises_on_a_broken_tool():
    from yazses.system.clipboard import get_clipboard

    def runner(cmd, **kw):
        raise OSError("no such tool")

    assert get_clipboard(runner=runner) == ""
