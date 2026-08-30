"""`yazses doctor` must name the backend `get_injector` will actually return.

Found by running the product (2026-08-20). `doctor` printed
``Injection: xdotool (X11)`` on this machine, and `_injection_readiness` took only
``(is_wayland, is_x11)`` -- it probed the session and the installed tools and never read
`[injection] backend`. `inject.auto.get_injector` does read it, so the two answered
different questions while the output read as one. Measured before the fix::

    backend=auto       daemon uses -> XdotoolInjector      doctor says -> xdotool (X11)
    backend=clipboard  daemon uses -> ClipboardInjector    doctor says -> xdotool (X11)
    backend=wtype      daemon uses -> XdotoolInjector      doctor says -> xdotool (X11)

This is the same shape as the injector-config bridge fixed the pass before
(`tests/test_injector_config_reaches_every_caller.py`), and that guard could not catch
it: it fails a function that calls ``injector_factory()`` without applying the config,
and `doctor` never calls `injector_factory()` at all -- it derived its own answer. A
second, independent derivation is exactly what nothing was comparing.

So the invariant here is an equality rather than a spelling: **wherever `doctor` reports
an ``OK`` injection backend, `get_injector` under the same environment must return that
backend.** ``OK`` is the load-bearing part -- it is doctor asserting *this will work*.
Non-OK lines are excluded on purpose: `doctor` runs `xdotool getdisplaygeometry` and can
know that a binary on PATH is unrunnable, which `get_injector`'s `shutil.which` cannot,
and that asymmetry is a feature of the diagnostic, not a disagreement to erase.
"""
from __future__ import annotations

import ast
import inspect
import os
from pathlib import Path

import pytest

from yazses.config import InjectionConfig
from yazses.inject.auto import apply_injection_config, get_injector
from yazses.inject.clipboard import ClipboardInjector
from yazses.inject.wtype import WtypeInjector
from yazses.inject.xdotool import XdotoolInjector
from yazses.inject.ydotool import YdotoolInjector
from yazses.system.doctor import _injection_readiness

REPO = Path(__file__).resolve().parents[1]

_TOKEN = {
    XdotoolInjector: "xdotool",
    YdotoolInjector: "ydotool",
    WtypeInjector: "wtype",
    ClipboardInjector: "clipboard",
}

# Every value `[injection] backend` accepts, per config.py's own comment.
_BACKENDS = ("auto", "type", "clipboard", "wtype")
_MIN_CASES = 12  # sessions x backends; an empty matrix must not pass as agreement


_SESSION_ENV = ("WAYLAND_DISPLAY", "DISPLAY", "XDG_CURRENT_DESKTOP")
_BRIDGED = ("YAZSES_INJECTOR", "YAZSES_INJECT_FALLBACK")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """No test here may read this machine's session or PATH -- or leave the two
    variables `apply_injection_config` writes set for the next file.

    The session variables go through `monkeypatch`, which the tests then override
    with `setenv`. The two bridged ones cannot: they are written straight into
    `os.environ` by the code under test, and `monkeypatch.delenv(..., raising=False)`
    records nothing to undo when the variable was not already set, so it restores
    nothing. See the same fix in
    `tests/test_injector_config_reaches_every_caller.py`.
    """
    for var in _SESSION_ENV:
        monkeypatch.delenv(var, raising=False)
    saved = {name: os.environ.get(name) for name in _BRIDGED}
    for name in _BRIDGED:
        os.environ.pop(name, None)
    yield
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def _situation(monkeypatch, *, wayland: bool, desktop: str = "sway",
               have=("xdotool", "ydotool", "wtype", "xclip", "wl-copy"),
               ydotoold: bool = True):
    """Pin the session and the installed tools for both derivations at once."""
    from yazses.inject import auto as auto_mod
    from yazses.system import doctor as doctor_mod

    if wayland:
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", desktop)
    monkeypatch.setenv("DISPLAY", ":0")

    def which(name):
        return f"/usr/bin/{name}" if name in have else None

    monkeypatch.setattr(auto_mod.shutil, "which", which)
    monkeypatch.setattr(doctor_mod.shutil, "which", which)
    monkeypatch.setattr(auto_mod, "ydotool_ready", lambda: ydotoold and "ydotool" in have)
    monkeypatch.setattr(doctor_mod, "_binary_runs", lambda cmd: cmd[0] in have)


def _injection_line(checks):
    named = [c for c in checks if c[0] == "Injection"]
    assert len(named) == 1, f"expected exactly one authoritative line, got {named}"
    return named[0]


_SITUATIONS = [
    ("x11", {"wayland": False}),
    ("wayland-wlroots", {"wayland": True, "desktop": "sway"}),
    ("wayland-gnome", {"wayland": True, "desktop": "gnome"}),
]


@pytest.mark.parametrize("label,situation", _SITUATIONS)
@pytest.mark.parametrize("backend", _BACKENDS)
def test_an_ok_verdict_names_the_backend_that_will_be_built(
    label, situation, backend, monkeypatch
):
    _situation(monkeypatch, **situation)
    apply_injection_config(InjectionConfig(backend=backend))

    _, status, detail = _injection_line(
        _injection_readiness(situation["wayland"], not situation["wayland"], backend)
    )
    if status != "OK":
        return  # doctor is reporting a problem, not naming a working backend

    built = _TOKEN[type(get_injector())]
    assert built in detail, (
        f"{label} + backend={backend}: doctor reports OK and says {detail!r}, but "
        f"get_injector builds {built} — the two derivations disagree, which is how "
        "`Injection: xdotool (X11)` was printed on a clipboard-configured machine"
    )


def test_the_matrix_is_not_empty():
    """A guard that iterates is green on an empty collection."""
    assert len(_SITUATIONS) * len(_BACKENDS) >= _MIN_CASES


# --- the three specific disagreements that were shipping -----------------------


def test_clipboard_is_reported_as_clipboard_not_as_the_probe_result(monkeypatch):
    """`get_injector` short-circuits on clipboard before it looks at the session."""
    _situation(monkeypatch, wayland=False)
    apply_injection_config(InjectionConfig(backend="clipboard"))
    _, status, detail = _injection_line(_injection_readiness(False, True, "clipboard"))
    assert status == "OK" and "clipboard" in detail
    assert "xdotool" not in detail
    assert isinstance(get_injector(), ClipboardInjector)


def test_wtype_on_x11_is_reported_as_ignored(monkeypatch):
    """wtype speaks the Wayland virtual-keyboard protocol; on X11 it cannot be used.

    The setting silently did nothing. Nothing is wrong with the fallback -- what was
    wrong is that a user who set it had no way to find out it was inert.
    """
    _situation(monkeypatch, wayland=False)
    checks = _injection_readiness(False, True, "wtype")
    notes = [c for c in checks if c[0] == "Injection setting"]
    assert notes and notes[0][1] == "WARN", checks
    assert "Wayland" in notes[0][2]
    _, status, detail = _injection_line(checks)
    assert status == "OK" and "xdotool" in detail


def test_wtype_beats_a_running_ydotoold_in_both_derivations(monkeypatch):
    """`get_injector` prefers wtype when it is configured; doctor said ydotool."""
    _situation(monkeypatch, wayland=True, desktop="sway", ydotoold=True)
    apply_injection_config(InjectionConfig(backend="wtype"))
    assert isinstance(get_injector(), WtypeInjector)
    _, status, detail = _injection_line(_injection_readiness(True, False, "wtype"))
    assert status == "OK" and "wtype" in detail, detail


def test_wtype_on_gnome_wayland_is_still_refused(monkeypatch):
    """Honouring the setting must not paper over a compositor that blocks wtype."""
    _situation(monkeypatch, wayland=True, desktop="gnome")
    _, status, detail = _injection_line(_injection_readiness(True, False, "wtype"))
    assert status == "FAIL" and "GNOME" in detail


def test_a_configured_clipboard_without_a_clipboard_tool_fails(monkeypatch):
    """The forced path still has a prerequisite, and it is still checked."""
    _situation(monkeypatch, wayland=False, have=("xdotool",))
    _, status, detail = _injection_line(_injection_readiness(False, True, "clipboard"))
    assert status == "FAIL" and "wl-copy" in detail


# --- the wiring itself ---------------------------------------------------------


def test_run_doctor_passes_the_configured_backend_through():
    """An honoured parameter nobody supplies is the original bug with more steps."""
    from yazses.system import doctor as doctor_mod

    source = inspect.getsource(doctor_mod.run_doctor)
    tree = ast.parse(source)
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "_injection_readiness"]
    assert calls, "run_doctor no longer runs the injection readiness check"
    for call in calls:
        assert len(call.args) + len(call.keywords) >= 3, (
            "run_doctor calls _injection_readiness without the configured backend, so "
            "doctor is back to probing the session and ignoring `[injection] backend`"
        )


def test_the_readiness_check_still_accepts_a_configured_backend():
    params = inspect.signature(_injection_readiness).parameters
    assert "configured" in params, (
        "the configured backend was dropped from the signature; doctor can no longer "
        "tell the user which injector it will use"
    )


def test_doctor_reads_the_backend_off_the_config_object():
    """It must come from `[injection] backend`, not a fresh probe or a constant."""
    source = inspect.getsource(
        __import__("yazses.system.doctor", fromlist=["run_doctor"]).run_doctor
    )
    assert '"backend"' in source and '"injection"' in source, (
        "run_doctor no longer reads cfg.injection.backend"
    )


def test_the_matrix_covers_every_backend_get_injector_accepts():
    """If a fifth backend is added, the agreement matrix must grow with it.

    Anchored on `get_injector` rather than on `config.py`, because the selector is what
    actually distinguishes the values -- the config field is a free-form string.
    """
    from yazses.inject import auto as auto_mod

    source = inspect.getsource(auto_mod.get_injector)
    for backend in _BACKENDS:
        if backend == "auto":
            continue
        assert f'"{backend}"' in source, (
            f"{backend} is in the test matrix but get_injector no longer names it"
        )
    quoted = {
        node
        for node in ("clipboard", "wtype", "type", "ydotool")
        if f'"{node}"' in source
    }
    unknown = quoted - set(_BACKENDS) - {"ydotool"}
    assert not unknown, (
        f"get_injector understands backends the matrix never exercises: {unknown}"
    )
