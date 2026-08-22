"""The IPC status payload is polled, so anything it recomputes is paid forever.

`_handle_status` is not a one-shot: the voice-activity overlay asks 4x a second
while idle and 20x while recording, and the tray 1x and 6.7x. It also builds the
payload while holding ``self._lock`` -- the mutex ``_on_hold_start`` takes when
the hotkey goes down. So a field that costs milliseconds to produce is not a
small waste; it is a per-second waste on the daemon's own lock.

One field did. ``"version": _running_version()`` called
``importlib.metadata.version("yazses")`` on every poll, and that call walks
``sys.path`` for a ``.dist-info`` rather than reading a cached string: **2.1 ms**
measured on this machine. With the overlay on that is ~30 s of CPU an hour, in a
process whose whole job while idle is to wait for a key. Measured on Mohsen's
laptop 2026-08-20: an 11-hour daemon session reported 1h 6min of CPU.

The repository already knew the cost -- ``tests/test_cli_startup_cost.py`` guards
against *importing* ``importlib.metadata`` for exactly this reason. The two facts
sat one file apart and nothing compared them.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

DAEMON = pathlib.Path(__file__).resolve().parent.parent / "src/yazses/core/daemon.py"


@pytest.fixture()
def running_version():
    from yazses.core.daemon import _running_version

    # getattr, not a direct call: when the memoisation is removed this fixture
    # must let the tests below fail with their own message instead of erroring
    # out before they run -- an erroring guard is a guard nobody reads.
    clear = getattr(_running_version, "cache_clear", lambda: None)
    clear()
    yield _running_version
    clear()


def test_the_version_lookup_happens_once_however_often_it_is_asked(monkeypatch, running_version):
    """The whole point: 200 polls, one filesystem walk."""
    import importlib.metadata

    calls: list[str] = []
    real = importlib.metadata.version

    def counting(name: str) -> str:
        calls.append(name)
        return real(name)

    monkeypatch.setattr(importlib.metadata, "version", counting)
    seen = {running_version() for _ in range(200)}

    assert len(calls) == 1, f"{len(calls)} metadata lookups for 200 status polls"
    assert len(seen) == 1, f"the cached lookup must be stable, got {seen}"


def test_it_still_reports_the_real_installed_version(running_version):
    from importlib.metadata import version

    assert running_version() == version("yazses")


def test_a_failed_lookup_is_still_the_empty_string_and_still_never_raises(monkeypatch, running_version):
    """The daemon must not die because it cannot name itself.

    Caching the failure is deliberate. The lookup fails when there is no
    ``.dist-info`` to find -- a PyInstaller bundle -- which is a property of how
    the process was built, not a transient. Retrying it 4x a second would pay the
    full ``sys.path`` walk *and* the exception, forever, to keep getting "".
    """
    import importlib.metadata

    def boom(_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError("yazses")

    monkeypatch.setattr(importlib.metadata, "version", boom)
    assert running_version() == ""
    assert running_version() == ""


def test_the_cache_is_declared_on_the_function_itself(running_version):
    """Not on a caller. A second caller must not be able to reintroduce the cost."""
    assert hasattr(running_version, "cache_clear"), (
        "_running_version must be memoised -- it is read on every IPC status poll"
    )


def _function(name: str) -> ast.FunctionDef:
    tree = ast.parse(DAEMON.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is gone from daemon.py -- update this guard")


def test_the_status_payload_still_reports_a_version_field():
    """Non-vacuity for the guard below: it must have something to inspect."""
    node = _function("_handle_status")
    keys = [
        k.value
        for sub in ast.walk(node)
        if isinstance(sub, ast.Dict)
        for k in sub.keys
        if isinstance(k, ast.Constant) and isinstance(k.value, str)
    ]
    assert "version" in keys, "the status payload no longer carries a version"


def test_the_status_handler_does_no_package_metadata_lookup_of_its_own():
    """The next field to want a version must go through the cached helper.

    A direct ``version("yazses")`` inlined here would restore the 2.1 ms poll cost
    with the memoisation still sitting one function away, looking correct.
    """
    node = _function("_handle_status")
    offenders = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.ImportFrom) and (sub.module or "").startswith("importlib"):
            offenders.append(f"line {sub.lineno}: from {sub.module} import ...")
        if isinstance(sub, ast.Import):
            offenders.extend(
                f"line {sub.lineno}: import {a.name}"
                for a in sub.names
                if a.name.startswith("importlib")
            )
        if isinstance(sub, ast.Call):
            func = sub.func
            if isinstance(func, ast.Name) and func.id == "version":
                offenders.append(f"line {sub.lineno}: version(...)")
            if isinstance(func, ast.Attribute) and func.attr == "version":
                offenders.append(f"line {sub.lineno}: ....version(...)")
    assert not offenders, (
        "_handle_status must not look up package metadata itself; call the cached "
        f"_running_version() instead. Found: {offenders}"
    )


def test_the_handler_builds_the_payload_under_the_lock_the_hotkey_needs():
    """Pins the reason the cost mattered, so a reader cannot take it for cosmetics.

    If this ever stops being true the docstrings above overstate the case and
    should be corrected -- which is why it is asserted rather than narrated.
    """
    node = _function("_handle_status")
    holds_lock = any(
        isinstance(sub, ast.Attribute) and sub.attr == "_lock"
        for item in node.body
        if isinstance(item, ast.With)
        for sub in ast.walk(item)
    )
    assert holds_lock, "_handle_status no longer builds the payload under self._lock"

    start = _function("_on_hold_start")
    takes_lock = any(
        isinstance(sub, ast.Attribute) and sub.attr == "_lock" for sub in ast.walk(start)
    )
    assert takes_lock, "_on_hold_start no longer takes self._lock"


# --- the how-to page states these rates as numbers; the code owns them --------
#
# `docs/how-to/cpu-and-battery.md` is where a user goes to decide what to switch
# off on battery, so every number on it is load-bearing. It described **two**
# pollers when there are three, and the one it left out is the fastest *and* on by
# default. Writing this guard caught a second error in the same paragraph, in the
# draft: it called the overlay opt-in when `OverlayConfig.enabled` is `True`.

DOC = pathlib.Path(__file__).resolve().parent.parent / "docs/how-to/cpu-and-battery.md"


def _hz(interval_s: float) -> float:
    return 1.0 / interval_s


def test_the_page_states_the_idle_poll_rates_the_code_actually_uses():
    from yazses.config import AudioConfig
    from yazses.overlay import poller
    from yazses.tray import app as tray_app

    text = DOC.read_text(encoding="utf-8")
    expected = {
        "device monitor": (_hz(AudioConfig().device_poll_interval_s), "0.33 Hz"),
        "tray": (_hz(tray_app._POLL_INTERVAL_S), "1 Hz"),
        "overlay": (_hz(poller._SLOW_INTERVAL_S), "4 Hz"),
    }
    for who, (rate, printed) in expected.items():
        stated = float(printed.split()[0])
        assert abs(stated - rate) < 0.05, f"{who}: the page says {printed}, the code polls at {rate:.2f} Hz"
        assert printed in text, f"{who}: the page no longer states {printed}"


def test_the_page_states_the_recording_poll_rates_the_code_actually_uses():
    from yazses.overlay import poller
    from yazses.tray import app as tray_app

    text = DOC.read_text(encoding="utf-8")
    for rate, printed in (
        (_hz(tray_app._FAST_POLL_INTERVAL_S), "6.7 Hz"),
        (_hz(poller._FAST_INTERVAL_S), "20 Hz"),
    ):
        stated = float(printed.split()[0])
        assert abs(stated - rate) < 0.1, f"the page says {printed}, the code polls at {rate:.2f} Hz"
        assert printed in text, f"the page no longer states {printed}"


@pytest.mark.parametrize(
    "section,attr,key",
    [("overlay", "enabled", "`[overlay] enabled` (default `true`)"),
     ("tray", "enabled", "`[tray] enabled` (default `true`)")],
)
def test_the_page_states_the_right_default_for_each_poller(section, attr, key):
    """Calling a default-on poller opt-in is the difference between a page that
    saves battery and a page that tells you the drain is not there."""
    from yazses.config import OverlayConfig, TrayConfig

    live = {"overlay": OverlayConfig(), "tray": TrayConfig()}[section]
    on = getattr(live, attr)
    assert on is True, f"[{section}] {attr} now defaults to {on} -- the page says true"
    assert key in DOC.read_text(encoding="utf-8"), f"the page no longer states the [{section}] default"


def test_the_page_names_a_command_that_can_actually_turn_each_poller_off():
    from yazses.config import load_config
    from yazses.system.features import find_feature

    cfg = load_config()
    text = DOC.read_text(encoding="utf-8")
    for slug in ("tray", "overlay"):
        feature = find_feature(cfg, slug)
        assert feature is not None and feature.wired and feature.toggleable, (
            f"the page hands out `yazses features disable {slug}`"
        )
        # \b, not `in`: "yazses features disable overlays" *contains* the correct
        # command as a prefix, so a substring check passes on a slug that does not
        # exist. It did, on the first run of this guard.
        assert re.search(rf"yazses features disable {slug}\b", text), (
            f"the page no longer names `yazses features disable {slug}`"
        )
