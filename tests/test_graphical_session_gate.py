"""A desktop is not detected by an X11 environment variable on Windows or macOS.

Three separate gates decided "is there a graphical session?" with the same two
lines -- `DISPLAY` or `WAYLAND_DISPLAY`:

- `settingsui/launch.py::has_display`     -> the Settings window refuses to open
- `core/daemon.py::should_launch_overlay` -> the voice-activity overlay is not spawned
- `tray/launch.py::should_launch_tray`    -> the daemon does not auto-spawn the tray

Those variables are X11 and Wayland concepts. **Windows and macOS never set either
one**, so all three answered "headless" on every Windows and macOS install there has
ever been. Reported first-hand from a Windows machine, 2026-08-27: clicking
*Settings…* in the tray opened nothing, and dictation produced no sonar overlay --
correct transcription, no visible sign anything was happening.

The failure is invisible in exactly the way that keeps it alive. `has_display`
returning False makes Settings call `_fatal`, which prints to a console a windowed
binary does not have; `should_launch_overlay` returning False is indistinguishable
from an overlay that is switched off. Neither raises, so nothing is logged as wrong.

The predicate now lives in one place and takes the platform as an argument, because
the honest answer differs per platform: on Windows and macOS an interactive process
*has* a desktop by construction and there is no variable that says so, while on
Linux/BSD the variables are the only evidence there is.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from yazses.system.graphical import has_graphical_session

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "yazses"
SHARED = SRC / "system" / "graphical.py"


# --- the predicate itself ---------------------------------------------------

@pytest.mark.parametrize("platform", ["win32", "cygwin", "darwin"])
def test_windows_and_macos_have_a_desktop_without_any_variable(platform: str) -> None:
    """The whole bug: an empty environment is a normal desktop session there."""
    assert has_graphical_session({}, platform=platform) is True


@pytest.mark.parametrize("platform", ["linux", "freebsd14", "openbsd7"])
def test_x11_and_wayland_still_decide_it_on_unix(platform: str) -> None:
    assert has_graphical_session({"DISPLAY": ":0"}, platform=platform) is True
    assert has_graphical_session({"WAYLAND_DISPLAY": "wayland-0"}, platform=platform) is True
    assert has_graphical_session({}, platform=platform) is False
    assert has_graphical_session({"DISPLAY": "", "WAYLAND_DISPLAY": ""}, platform=platform) is False


def test_a_headless_linux_box_is_still_headless() -> None:
    """The behaviour the original two lines were written for, kept exactly."""
    ssh = {"TERM": "xterm", "SSH_CONNECTION": "10.0.0.1 22 10.0.0.2 22"}
    assert has_graphical_session(ssh, platform="linux") is False


def test_an_explicit_qt_platform_wins_everywhere() -> None:
    """`QT_QPA_PLATFORM=offscreen` is how the headless smoke tests drive the window."""
    for platform in ("linux", "win32", "darwin"):
        assert has_graphical_session({"QT_QPA_PLATFORM": "offscreen"}, platform=platform) is True


# --- the three gates that must agree with it --------------------------------

def test_the_settings_window_opens_on_a_bare_windows_environment() -> None:
    from yazses.settingsui.launch import has_display

    assert has_display({}, platform="win32") is True
    assert has_display({}, platform="darwin") is True
    assert has_display({}, platform="linux") is False


def test_the_overlay_is_spawned_on_a_bare_windows_environment() -> None:
    from yazses.config import Config, OverlayConfig
    from yazses.core.daemon import should_launch_overlay

    on = Config(overlay=OverlayConfig(enabled=True))
    off = Config(overlay=OverlayConfig(enabled=False))
    assert should_launch_overlay(on, {}, platform="win32") is True
    assert should_launch_overlay(on, {}, platform="darwin") is True
    assert should_launch_overlay(on, {}, platform="linux") is False
    # The switch still wins over the platform.
    assert should_launch_overlay(off, {}, platform="win32") is False


def test_the_tray_is_spawned_on_a_bare_windows_environment() -> None:
    from yazses.config import Config, TrayConfig
    from yazses.tray.launch import should_launch_tray

    on = Config(tray=TrayConfig(enabled=True))
    off = Config(tray=TrayConfig(enabled=False))
    assert should_launch_tray(on, {}, platform="win32") is True
    assert should_launch_tray(on, {}, platform="darwin") is True
    assert should_launch_tray(on, {}, platform="linux") is False
    assert should_launch_tray(off, {}, platform="win32") is False


# --- nothing may re-derive the predicate ------------------------------------

def _reads_display_var(node: ast.AST) -> str | None:
    """`env.get("DISPLAY")` -> "DISPLAY"; anything else -> None."""
    if not isinstance(node, ast.Call):
        return None
    if not (isinstance(node.func, ast.Attribute) and node.func.attr == "get"):
        return None
    if not node.args or not isinstance(node.args[0], ast.Constant):
        return None
    value = node.args[0].value
    return value if value in {"DISPLAY", "WAYLAND_DISPLAY"} else None


def rederives_the_predicate(source: str) -> bool:
    """Whether *source* decides "is there a desktop?" from the two X11 variables.

    Matched precisely, because the polarity is what separates the bug from a correct
    use. `inject/target.py` asks a genuinely different question --

        if not env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"):   # not plain X11

    -- which is "is this a *plain X11* session?", the guard xdotool actually needs.
    An earlier regex here flagged it, and refusing what the code is right to do is
    how a guard gets deleted. So: both operands must be bare reads, no `not`.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)):
            continue
        seen = {_reads_display_var(v) for v in node.values}
        if seen == {"DISPLAY", "WAYLAND_DISPLAY"}:
            return True
    return False


def test_no_module_outside_the_shared_one_rederives_the_predicate() -> None:
    """Three copies is how this stayed wrong on two platforms for the whole project.

    Deriving a rule in one place and testing it there does nothing if the callers
    each keep their own copy; that is the same lesson as the icon guard reading its
    size list out of `build-deb.sh`.
    """
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        if path == SHARED:
            continue
        if rederives_the_predicate(path.read_text(encoding="utf-8")):
            offenders.append(path.relative_to(SRC).as_posix())
    assert not offenders, (
        f"these modules decide 'is there a desktop?' themselves instead of calling "
        f"yazses.system.graphical.has_graphical_session: {offenders}. On Windows and "
        f"macOS their answer is always wrong."
    )


def test_the_sweep_can_actually_find_the_pattern() -> None:
    """Anti-vacuity: a check that matches nothing would make the guard above free."""
    assert rederives_the_predicate(
        'return bool(env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))'
    )
    assert not rederives_the_predicate("return bool(env.get('TERM'))")


def test_the_sweep_permits_the_plain_x11_question() -> None:
    """The opposite polarity is a different, correct question -- it must not trip."""
    assert not rederives_the_predicate(
        'if not env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"):\n    return None'
    )


def test_the_shared_module_takes_the_platform_as_an_argument() -> None:
    """It must be injectable, or none of the cases above can be tested off-platform."""
    tree = ast.parse(SHARED.read_text(encoding="utf-8"), filename=str(SHARED))
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "has_graphical_session"
    )
    names = [a.arg for a in fn.args.args + fn.args.kwonlyargs]
    assert "platform" in names, f"has_graphical_session takes {names}"
