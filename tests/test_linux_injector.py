"""`LinuxInjector` — the clipboard fallback, and the setting that controls it."""

from __future__ import annotations

import pytest

from yazses.platform.linux.injector import LinuxInjector


class _Boom:
    """A primary injector that always fails, so the fallback decision is visible."""

    def inject(self, text):
        raise RuntimeError("primary failed")

    def inject_backspaces(self, count):
        raise RuntimeError("primary failed")

# ---- [injection] fallback_to_clipboard was documented and read by nothing -----


def test_the_fallback_can_be_turned_off(monkeypatch):
    """`[injection] fallback_to_clipboard` appears in 17 places across the docs and
    the example configs people copy, defaults to true, and nothing read it — the
    fallback was constructed unconditionally, so turning it off did nothing.

    It is a real remedy rather than a preference: `xdotool.py` records that a
    timeout can fire *after* part of the text is typed, the clipboard paste then
    types it a second time, and the streaming commit deletes a span computed from
    the first copy. Someone who has met that wants the primary to fail loudly.
    """
    monkeypatch.setattr("yazses.platform.linux.injector.get_injector", lambda: _Boom())

    off = LinuxInjector(fallback_to_clipboard=False)
    assert off._fallback is None
    with pytest.raises(RuntimeError):
        off.inject("hello")  # must surface, not silently paste


def test_the_fallback_is_on_by_default(monkeypatch):
    """The documented default is true, and this must not change behaviour for
    anyone who never set it."""
    monkeypatch.setattr("yazses.platform.linux.injector.get_injector", lambda: _Boom())
    monkeypatch.delenv("YAZSES_INJECT_FALLBACK", raising=False)
    assert LinuxInjector()._fallback is not None


def test_the_env_bridge_is_read(monkeypatch):
    """The daemon passes the config through this env var, exactly as it already
    does for `[injection] backend` — chosen so no platform factory signature moves."""
    monkeypatch.setattr("yazses.platform.linux.injector.get_injector", lambda: _Boom())
    for value in ("0", "false", "NO", "off"):
        monkeypatch.setenv("YAZSES_INJECT_FALLBACK", value)
        assert LinuxInjector()._fallback is None, value
    for value in ("1", "true", "anything-else"):
        monkeypatch.setenv("YAZSES_INJECT_FALLBACK", value)
        assert LinuxInjector()._fallback is not None, value


def test_the_daemon_bridges_the_setting():
    """The wiring itself: an honoured flag nobody sets is the original bug again.

    The export moved out of `Daemon._build_pipeline` and into
    `inject.auto.apply_injection_config`, because the three CLI commands that build an
    injector had to apply the same bridge and were not applying any. So this now checks
    the two halves it became: the daemon calls the bridge, and the bridge exports the
    variable. Checking only the first would pass on a bridge that exports nothing.
    """
    import inspect
    import os

    from yazses.config import InjectionConfig
    from yazses.core.daemon import Daemon
    from yazses.inject.auto import apply_injection_config

    source = inspect.getsource(Daemon._build_pipeline)
    assert "apply_injection_config" in source, (
        "the daemon never applies the bridge, so LinuxInjector still cannot see it"
    )
    before = os.environ.get("YAZSES_INJECT_FALLBACK")
    try:
        apply_injection_config(InjectionConfig(fallback_to_clipboard=False))
        assert os.environ["YAZSES_INJECT_FALLBACK"] == "0"
    finally:
        if before is None:
            os.environ.pop("YAZSES_INJECT_FALLBACK", None)
        else:
            os.environ["YAZSES_INJECT_FALLBACK"] = before
