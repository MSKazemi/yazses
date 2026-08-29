"""The layout half of windowctl: planner, backend, and the daemon wiring (#164).

`parse_wm_command` shipped in ADR-v2-070 and nothing imported it for a release, so
`yazses features enable windowctl` succeeded and "move window left half" did
nothing. These tests cover the three places that could re-break: the arithmetic, the
xdotool argv it produces, and the fact that a failure is *reported* rather than
reported as success — a silent no-op is indistinguishable from a misrecognition, and
that is precisely what made the original defect so hard to notice.

Everything here runs without a display: the planner is pure, and the backend takes an
injected runner.
"""
from __future__ import annotations

import pytest

from yazses.windowctl.actions import Screen, UnsupportedAction, plan, snap_rect
from yazses.windowctl.commands import WmAction, parse_wm_command
from yazses.windowctl.focus import XdotoolWindows, parse_focus_command

SCREEN = Screen(width=1920, height=1080)


# ── the arithmetic ───────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "target,expected",
    [
        ("left",         (0, 0, 960, 1080)),
        ("right",        (960, 0, 960, 1080)),
        ("top",          (0, 0, 1920, 540)),
        ("bottom",       (0, 540, 1920, 540)),
        ("top-left",     (0, 0, 960, 540)),
        ("bottom-right", (960, 540, 960, 540)),
    ],
)
def test_snap_rectangles(target: str, expected: tuple[int, int, int, int]) -> None:
    assert snap_rect(target, SCREEN) == expected


def test_two_halves_leave_no_gap_on_an_odd_width_screen() -> None:
    """Truncating instead of rounding leaves a one-pixel seam that reads as a bug."""
    odd = Screen(width=1921, height=1080)
    lx, _, lw, _ = snap_rect("left", odd)
    rx, _, rw, _ = snap_rect("right", odd)
    assert lx + lw == rx, "a gap opened between the two halves"
    assert rx + rw >= odd.width, "the right half does not reach the screen edge"


def test_an_unknown_snap_target_raises_rather_than_returning_nothing() -> None:
    with pytest.raises(UnsupportedAction):
        snap_rect("diagonal", SCREEN)


# ── the plan ─────────────────────────────────────────────────────────────────

def test_a_snap_unmaximizes_before_it_moves() -> None:
    """A maximized window accepts windowmove and ignores it — success, no movement."""
    steps = plan(WmAction("snap", "left"), "42", screen=SCREEN)
    assert "windowstate" in steps[0]
    assert "--remove" in steps[0]
    kinds = [s[1] for s in steps]
    assert kinds.index("windowstate") < kinds.index("windowmove")


def test_spoken_workspace_numbers_are_one_based() -> None:
    """"Workspace 3" means the third one; xdotool counts from 0.

    Asserted on the *translated* value on purpose: a test that checks the number it
    passed in cannot see an off-by-one, which is how this class of bug survives.
    """
    assert plan(WmAction("workspace", 3), "42") == [["xdotool", "set_desktop", "2"]]
    assert plan(WmAction("workspace", 1), "42") == [["xdotool", "set_desktop", "0"]]


def test_workspace_zero_is_refused_rather_than_wrapped() -> None:
    with pytest.raises(UnsupportedAction):
        plan(WmAction("workspace", 0), "42")


def test_relative_workspace_needs_to_know_where_it_is() -> None:
    assert plan(WmAction("workspace_rel", 1), "42", current_desktop=2) == [
        ["xdotool", "set_desktop", "3"]
    ]
    assert plan(WmAction("workspace_rel", -1), "42", current_desktop=0) == [
        ["xdotool", "set_desktop", "0"]
    ], "stepping back from the first workspace must clamp, not go negative"
    with pytest.raises(UnsupportedAction):
        plan(WmAction("workspace_rel", 1), "42")


def test_geometry_actions_refuse_to_guess_a_screen_size() -> None:
    """A guessed screen puts the window somewhere arbitrary, and reports success."""
    for kind in ("snap", "center"):
        with pytest.raises(UnsupportedAction):
            plan(WmAction(kind, "left"), "42")


def test_close_asks_politely_so_unsaved_work_can_still_prompt() -> None:
    """A misheard 'close the window' must not be able to destroy work."""
    steps = plan(WmAction("close"), "42")
    assert steps == [["xdotool", "windowclose", "42"]]
    assert "windowkill" not in str(steps)


def test_an_unknown_kind_raises_instead_of_silently_succeeding() -> None:
    with pytest.raises(UnsupportedAction):
        plan(WmAction("teleport"), "42")


# ── the backend ──────────────────────────────────────────────────────────────

class _Runner:
    """A fake xdotool. Records argv; answers the probes; can be told to fail."""

    def __init__(self, fail_on: str | None = None) -> None:
        self.calls: list[list[str]] = []
        self.fail_on = fail_on

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(argv)
        if self.fail_on and self.fail_on in argv:
            raise RuntimeError("xdotool failed")
        if argv[1:2] == ["getactivewindow"]:
            return "77\n"
        if argv[1:2] == ["getdisplaygeometry"]:
            return "1920 1080\n"
        if argv[1:2] == ["get_desktop"]:
            return "1\n"
        return ""


def test_a_maximize_reaches_xdotool() -> None:
    runner = _Runner()
    assert XdotoolWindows(runner).perform(WmAction("maximize")) is True
    assert ["xdotool", "getactivewindow"] in runner.calls
    assert any("windowstate" in c and "--add" in c for c in runner.calls)


def test_a_snap_asks_for_the_screen_and_uses_it() -> None:
    runner = _Runner()
    assert XdotoolWindows(runner).perform(WmAction("snap", "right")) is True
    assert ["xdotool", "getdisplaygeometry"] in runner.calls
    assert ["xdotool", "windowmove", "77", "960", "0"] in runner.calls
    assert ["xdotool", "windowsize", "77", "960", "1080"] in runner.calls


def test_switching_workspace_does_not_require_a_focused_window() -> None:
    """Switching workspaces with nothing focused is perfectly ordinary."""
    runner = _Runner()
    assert XdotoolWindows(runner).perform(WmAction("workspace", 2)) is True
    assert ["xdotool", "getactivewindow"] not in runner.calls
    assert ["xdotool", "set_desktop", "1"] in runner.calls


def test_relative_workspace_reads_the_current_one() -> None:
    runner = _Runner()
    assert XdotoolWindows(runner).perform(WmAction("workspace_rel", 1)) is True
    assert ["xdotool", "set_desktop", "2"] in runner.calls


def test_a_failing_step_is_reported_as_failure_not_swallowed() -> None:
    """The whole point. A no-op that returns True is the original defect."""
    runner = _Runner(fail_on="windowsize")
    assert XdotoolWindows(runner).perform(WmAction("snap", "left")) is False


def test_no_active_window_is_a_failure_not_a_pretend_success() -> None:
    class _NoWindow(_Runner):
        def __call__(self, argv: list[str]) -> str:
            super().__call__(argv)
            if argv[1:2] == ["getactivewindow"]:
                return ""
            return ""

    assert XdotoolWindows(_NoWindow()).perform(WmAction("maximize")) is False


def test_an_unsupported_action_is_a_failure_not_an_exception() -> None:
    """This runs inside a hold-release; an exception there surfaces nowhere."""
    assert XdotoolWindows(_Runner()).perform(WmAction("teleport")) is False


# ── the two grammars must not fight ──────────────────────────────────────────

@pytest.mark.parametrize(
    "phrase",
    [
        "maximize", "minimise", "full screen", "center",
        "move window left half", "snap right", "tile left",
        "close the window", "next workspace", "previous workspace", "workspace 3",
    ],
)
def test_every_layout_phrase_is_claimed_by_the_layout_grammar(phrase: str) -> None:
    assert parse_wm_command(phrase) is not None


@pytest.mark.parametrize(
    "phrase", ["focus the browser", "switch to my editor", "activate the terminal"]
)
def test_focus_phrases_are_not_stolen_by_the_layout_grammar(phrase: str) -> None:
    assert parse_wm_command(phrase) is None
    assert parse_focus_command(phrase) is not None


def test_the_one_phrase_both_grammars_claim_goes_to_the_layout_one() -> None:
    """"go to workspace 3" parses as *focusing a window titled "workspace 3"*.

    The focus grammar accepts "go to ...", so both match. A window actually titled
    "workspace 3" is far less likely than the workspace intent, which is why
    `core/daemon.py` runs `_try_window_action` first. If that order is ever
    reversed, this is the phrase that breaks.
    """
    assert parse_focus_command("go to workspace 3") == "workspace 3"
    assert parse_wm_command("go to workspace 3") == WmAction("workspace", 3)
