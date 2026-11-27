"""Clipboard tools inside a strict snap must find the host's Wayland socket.

snapd gives the snap a private ``XDG_RUNTIME_DIR`` (``/run/user/<uid>/snap.<name>``)
but passes ``WAYLAND_DISPLAY=wayland-0`` through unchanged, so ``wl-copy`` looks for
the socket in a directory that never holds it and fails with "Failed to connect to a
Wayland server". The host socket sits one level up. Only the clipboard commands are
pointed there: the daemon's own environment is inherited by the Qt tray, which would
change platform plugin if ``WAYLAND_DISPLAY`` started resolving.
"""
from __future__ import annotations

import subprocess

import pytest

from yazses.system.wayland_env import wayland_tool_env


@pytest.fixture
def snap_session(tmp_path):
    host = tmp_path / "1000"
    private = host / "snap.yazses"
    private.mkdir(parents=True)
    (host / "wayland-0").touch()
    env = {
        "SNAP": "/snap/yazses/1",
        "XDG_RUNTIME_DIR": str(private),
        "WAYLAND_DISPLAY": "wayland-0",
    }
    return env, host


def test_a_snap_is_pointed_at_the_host_socket(snap_session):
    env, host = snap_session
    got = wayland_tool_env(env)
    assert got is not None
    assert got["WAYLAND_DISPLAY"] == str(host / "wayland-0")


def test_the_rest_of_the_environment_is_kept_and_the_input_is_not_mutated(snap_session):
    env, _host = snap_session
    got = wayland_tool_env(env)
    assert got is not None
    assert got["XDG_RUNTIME_DIR"] == env["XDG_RUNTIME_DIR"]
    assert env["WAYLAND_DISPLAY"] == "wayland-0"


def test_a_socket_the_snap_already_sees_is_left_alone(snap_session):
    env, _host = snap_session
    (_host / "snap.yazses" / "wayland-0").touch()
    assert wayland_tool_env(env) is None


def test_an_absolute_socket_path_is_left_alone(snap_session):
    env, host = snap_session
    env["WAYLAND_DISPLAY"] = str(host / "wayland-0")
    assert wayland_tool_env(env) is None


def test_outside_a_snap_nothing_changes(snap_session):
    env, _host = snap_session
    del env["SNAP"]
    assert wayland_tool_env(env) is None


def test_a_private_runtime_dir_is_required(tmp_path):
    """``SNAP`` is inherited by anything launched from a snapped terminal."""
    runtime = tmp_path / "1000"
    runtime.mkdir()
    (tmp_path / "wayland-0").touch()
    env = {"SNAP": "/snap/code/1", "XDG_RUNTIME_DIR": str(runtime),
           "WAYLAND_DISPLAY": "wayland-0"}
    assert wayland_tool_env(env) is None


def test_no_host_socket_means_no_change(snap_session):
    env, host = snap_session
    (host / "wayland-0").unlink()
    assert wayland_tool_env(env) is None


@pytest.mark.parametrize("missing", ["XDG_RUNTIME_DIR", "WAYLAND_DISPLAY"])
def test_a_missing_variable_means_no_change(snap_session, missing):
    env, _host = snap_session
    del env[missing]
    assert wayland_tool_env(env) is None


# -- every clipboard command gets it ------------------------------------------


@pytest.fixture
def in_snap(snap_session, monkeypatch):
    env, host = snap_session
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return str(host / "wayland-0")


def _recorder(calls):
    def run(cmd, *args, **kwargs):
        calls.append((list(cmd), kwargs))
        return subprocess.CompletedProcess(cmd, 0, stdout=b"x", stderr=b"")

    return run


def test_set_clipboard_uses_the_host_socket(in_snap):
    from yazses.system.clipboard import set_clipboard

    calls: list = []
    assert set_clipboard("hi", runner=_recorder(calls), candidates=[["wl-copy", "--"]])
    assert calls[0][1]["env"]["WAYLAND_DISPLAY"] == in_snap


def test_get_clipboard_uses_the_host_socket(in_snap):
    from yazses.system.clipboard import get_clipboard

    calls: list = []
    get_clipboard(runner=_recorder(calls), candidates=[["wl-paste", "--no-newline"]])
    assert calls[0][1]["env"]["WAYLAND_DISPLAY"] == in_snap


def test_the_injection_fallback_copies_through_the_host_socket(in_snap, monkeypatch):
    from yazses.inject import clipboard

    calls: list = []
    monkeypatch.setattr(clipboard.subprocess, "run", _recorder(calls))
    monkeypatch.setattr(clipboard, "_paste_wayland", lambda: None)
    monkeypatch.setattr(clipboard, "_CLIPBOARD_SETTLE_S", 0)
    clipboard.ClipboardInjector().inject("hi")
    assert calls[0][0][0] == "wl-copy"
    assert calls[0][1]["env"]["WAYLAND_DISPLAY"] == in_snap


@pytest.mark.parametrize("reader", ["selection_text", "clipboard_text"])
def test_context_reading_uses_the_host_socket(in_snap, monkeypatch, reader):
    from yazses.system import context_read

    calls: list = []
    monkeypatch.setattr(
        context_read.shutil, "which",
        lambda tool: "/usr/bin/wl-paste" if tool == "wl-paste" else None,
    )
    monkeypatch.setattr(context_read.subprocess, "run", _recorder(calls))
    getattr(context_read, reader)()
    assert calls[0][1]["env"]["WAYLAND_DISPLAY"] == in_snap


# -- copied but not pasted ------------------------------------------------------


def test_copied_without_a_paste_tool_says_the_words_are_on_the_clipboard(monkeypatch):
    from yazses.inject import clipboard
    from yazses.system.diagnosis import INJECT, diagnose

    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(clipboard.subprocess, "run", _recorder([]))
    monkeypatch.setattr(clipboard.shutil, "which", lambda tool: None)
    monkeypatch.setattr(clipboard, "_CLIPBOARD_SETTLE_S", 0)

    with pytest.raises(clipboard.PasteUnavailable) as caught:
        clipboard.ClipboardInjector().inject("hi")

    found = diagnose(caught.value, where=INJECT)
    assert found.slug == "inject-copied-not-pasted"
    assert "clipboard" in found.what.lower()
    assert "Ctrl+V" in found.fix
