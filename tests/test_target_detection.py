"""Text-target detection: editable-role classification, xdotool heuristic, precedence."""
from yazses.inject.target import (
    TargetDetector,
    is_editable_role,
    xdotool_target_ok,
)


def test_editable_by_state():
    # STATE_EDITABLE alone means it takes text, whatever the role.
    assert is_editable_role("panel", True) is True
    assert is_editable_role("", True) is True


def test_editable_by_role():
    for role in ["text", "entry", "terminal", "password text", "document frame"]:
        assert is_editable_role(role, False) is True, role


def test_non_editable_roles():
    for role in ["push button", "label", "menu item", "check box", ""]:
        assert is_editable_role(role, False) is False, role


class _Proc:
    def __init__(self, rc=0, out=""):
        self.returncode = rc
        self.stdout = out


def test_xdotool_none_off_x11():
    # Wayland or no DISPLAY → unknown (None), never a false alarm.
    assert xdotool_target_ok(env={"WAYLAND_DISPLAY": "wayland-0"}) is None
    assert xdotool_target_ok(env={}) is None


def test_xdotool_no_window_is_false(monkeypatch):
    import yazses.inject.target as t

    monkeypatch.setattr(t.shutil, "which", lambda _: "/usr/bin/xdotool")
    # Non-zero return (no focused window) → definite "no target".
    r = xdotool_target_ok(runner=lambda *a, **k: _Proc(rc=1), env={"DISPLAY": ":0"})
    assert r is False
    # Empty window name → no target.
    r2 = xdotool_target_ok(runner=lambda *a, **k: _Proc(rc=0, out="  \n"), env={"DISPLAY": ":0"})
    assert r2 is False


def test_xdotool_window_focused_is_unknown(monkeypatch):
    import yazses.inject.target as t

    monkeypatch.setattr(t.shutil, "which", lambda _: "/usr/bin/xdotool")
    # A normal window is focused, but we can't tell if a field has the caret → None.
    r = xdotool_target_ok(runner=lambda *a, **k: _Proc(rc=0, out="Firefox"), env={"DISPLAY": ":0"})
    assert r is None


class _FakeAtspi:
    def __init__(self, val):
        self._val = val

    def has_text_target(self):
        return self._val


def test_detector_prefers_atspi_when_definite():
    # AT-SPI says False → use it, don't consult xdotool.
    d = TargetDetector(atspi=_FakeAtspi(False), xdotool_fn=lambda: None)
    assert d.resolve() is False
    d2 = TargetDetector(atspi=_FakeAtspi(True), xdotool_fn=lambda: False)
    assert d2.resolve() is True


def test_detector_falls_back_when_atspi_unknown():
    # AT-SPI None (no event yet) → fall back to xdotool.
    d = TargetDetector(atspi=_FakeAtspi(None), xdotool_fn=lambda: False)
    assert d.resolve() is False
    d2 = TargetDetector(atspi=None, xdotool_fn=lambda: None)
    assert d2.resolve() is None
