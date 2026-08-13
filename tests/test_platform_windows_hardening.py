"""Regression tests for the Windows solidity fixes.

Everything here runs on any OS: the Win32 calls sit behind lazy imports or an
injected probe, and the logic under test is deliberately pure. Each test names
the failure it locks out — these all describe behaviour that shipped broken.
"""

from __future__ import annotations

import os
import threading
import time

import pytest

from yazses.platform.base import Paths
from yazses.platform.windows.injector import _MOD_VK, _VK_NAMED, resolve_key_combo
from yazses.platform.windows.lifecycle import WindowsLifecycle, is_yazses_image

# ---- Key-sequence resolution -------------------------------------------
#
# The dispatcher emits X11-style capitalised names. The old table was keyed
# capitalised but looked up lower-cased, so every named key missed and fell
# back to `vk=0` — a keystroke Windows accepts and ignores.


@pytest.mark.parametrize(
    ("combo", "expected_vk"),
    [
        ("Return", 0x0D),
        ("Tab", 0x09),
        ("Escape", 0x1B),
        ("BackSpace", 0x08),
        ("Left", 0x25),
        ("Up", 0x26),
        ("Right", 0x27),
        ("Down", 0x28),
        ("Home", 0x24),
        ("End", 0x23),
        ("Page_Up", 0x21),
        ("Page_Down", 0x22),
    ],
)
def test_capitalised_key_names_resolve(combo, expected_vk):
    """Every named key the dispatcher sends must resolve to a real VK."""
    resolved = resolve_key_combo(combo)
    assert resolved is not None, f"{combo!r} did not resolve -- would inject vk=0"
    mods, vk = resolved
    assert (mods, vk) == ([], expected_vk)


def test_modifier_combo_resolves_in_order():
    mods, vk = resolve_key_combo("ctrl+shift+End")
    assert mods == [_MOD_VK["ctrl"], _MOD_VK["shift"]]
    assert vk == 0x23


def test_ctrl_backspace_resolves():
    """`delete_words` sends ctrl+BackSpace; it used to become ctrl+vk0."""
    mods, vk = resolve_key_combo("ctrl+BackSpace")
    assert mods == [_MOD_VK["ctrl"]]
    assert vk == 0x08


def test_letter_and_digit_keys_still_resolve():
    assert resolve_key_combo("ctrl+z") == ([_MOD_VK["ctrl"]], 0x5A)
    assert resolve_key_combo("7") == ([], 0x37)


def test_unknown_key_returns_none_rather_than_vk_zero():
    """The caller must be able to tell 'unsupported' from 'sent'."""
    assert resolve_key_combo("Nonexistent_Key") is None
    assert resolve_key_combo("") is None


def test_unknown_modifier_returns_none():
    assert resolve_key_combo("hyper+a") is None


def test_duplicate_modifier_is_not_pressed_twice():
    mods, _ = resolve_key_combo("ctrl+control+a")
    assert mods == [_MOD_VK["ctrl"]]


def test_every_dispatcher_key_token_resolves():
    """Contract test: the dispatcher's whole key vocabulary must be injectable.

    This is the check that would have caught the original bug — it walks the
    real command tables instead of a hand-copied list, so a new binding that
    Windows can't express fails here rather than silently doing nothing.
    """
    from yazses.commands import dispatch

    tokens: set[str] = set()
    for value in vars(dispatch).values():
        if isinstance(value, dict):
            for combos in value.values():
                if isinstance(combos, list):
                    tokens.update(c for c in combos if isinstance(c, str))

    assert tokens, "found no key tables in commands.dispatch -- test is not looking at anything"
    unresolved = sorted(t for t in tokens if resolve_key_combo(t) is None)
    assert not unresolved, f"not injectable on Windows: {unresolved}"


def test_named_table_is_lowercase_only():
    """Guards the invariant the lookup depends on."""
    assert all(k == k.lower() for k in _VK_NAMED)
    assert all(k == k.lower() for k in _MOD_VK)


# ---- Liveness probe ------------------------------------------------------


def _paths(tmp_path) -> Paths:
    return Paths(
        config_dir=tmp_path,
        state_dir=tmp_path,
        cache_dir=tmp_path,
        log_dir=tmp_path,
        data_dir=tmp_path,
    )


def test_is_running_never_calls_os_kill(tmp_path, monkeypatch):
    """os.kill(pid, 0) TERMINATES the process on Windows (bpo-14480).

    `yazses status`, `doctor` and the tray's poll loop all reach is_running(),
    so using it as a liveness probe killed the daemon it was reporting on.
    """
    def _boom(*args, **kwargs):
        raise AssertionError("os.kill must never be used as a liveness probe on Windows")

    monkeypatch.setattr(os, "kill", _boom)

    paths = _paths(tmp_path)
    paths.pid_file.write_text("4321")
    lifecycle = WindowsLifecycle(paths, alive_probe=lambda pid: False)
    assert lifecycle.is_running() is False


def test_is_running_false_when_probe_says_dead(tmp_path):
    paths = _paths(tmp_path)
    paths.pid_file.write_text("4321")
    lifecycle = WindowsLifecycle(paths, alive_probe=lambda pid: False)
    assert lifecycle.is_running() is False


def test_is_running_consults_the_recorded_pid(tmp_path):
    paths = _paths(tmp_path)
    paths.pid_file.write_text("4321")
    seen: list[int] = []
    WindowsLifecycle(paths, alive_probe=lambda pid: seen.append(pid) or False).is_running()
    assert seen == [4321]


def test_is_running_false_without_pid_file(tmp_path):
    lifecycle = WindowsLifecycle(_paths(tmp_path), alive_probe=lambda pid: True)
    assert lifecycle.is_running() is False


# ---- Recycled-PID guard --------------------------------------------------


def test_tasklist_image_match_accepts_our_processes():
    assert is_yazses_image('"yazses-daemon.exe","4321","Console","1","55,000 K"')
    assert is_yazses_image('"YazSes.exe","4321","Console","1","55,000 K"')
    assert is_yazses_image('"python.exe","4321","Console","1","55,000 K"')


def test_tasklist_image_match_rejects_unrelated_process():
    """The old check matched 'python' anywhere in the row, including titles."""
    assert not is_yazses_image('"notepad.exe","4321","Console","1","5,000 K"')
    assert not is_yazses_image('"chrome.exe","4321","Console","1","python tutorial"')
    assert not is_yazses_image("")
    assert not is_yazses_image("INFO: No tasks are running which match the criteria.")


# ---- Autostart command line ---------------------------------------------


def test_frozen_autostart_is_quoted_and_starts_the_tray(tmp_path, monkeypatch):
    """A username with a space must not break autostart, and --tray is required.

    installer.iss writes `"{app}\\YazSes.exe" --tray`; toggling autostart
    in-app must not overwrite that with something weaker.
    """
    import sys

    exe = tmp_path / "John Smith" / "YazSes.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))

    command = WindowsLifecycle(_paths(tmp_path))._tray_executable()

    assert command.startswith('"')
    assert command.endswith("--tray")
    assert f'"{exe}"' in command


def test_non_frozen_tray_script_path_is_quoted(tmp_path, monkeypatch):
    import sys

    scripts = tmp_path / "Program Files" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "yazses-tray.exe").write_text("")
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(sys, "executable", str(scripts / "python.exe"))

    command = WindowsLifecycle(_paths(tmp_path))._tray_executable()
    assert command == f'"{scripts / "yazses-tray.exe"}"'


# ---- Hold-to-talk timing -------------------------------------------------
#
# Windows delivers no typematic repeat for modifier keys, so a threshold that
# is only re-checked on the next key event never elapses for right_ctrl (the
# default). These tests hold the key without sending any further events.


def _hotkey(key_id="right_ctrl", threshold_ms=40):
    from yazses.platform.windows.hotkey import WindowsHotkey

    started: list[int] = []
    ended: list[int] = []
    hk = WindowsHotkey(
        key_id=key_id,
        threshold_ms=threshold_ms,
        on_hold_start=started.append,
        on_hold_end=lambda: ended.append(1),
    )
    return hk, started, ended


def test_hold_fires_without_any_further_key_events():
    """The regression: one keydown, no repeats, must still start recording.

    Uses `space` because the timer is what character keys need — they type
    before we can tell a tap from a hold, so the threshold has to be waited out
    without depending on the machine's typematic delay. Modifiers deliberately
    do not wait; see test_modifier_starts_immediately_no_onset_clipping.
    """
    hk, started, _ = _hotkey(key_id="space")
    hk._press()
    assert started == [], "must not fire before the threshold"
    time.sleep(0.15)
    assert started == [1], "hold never fired -- threshold depends on key repeat"


def test_release_before_threshold_does_not_fire():
    hk, started, ended = _hotkey(key_id="space", threshold_ms=1000)
    hk._press()
    hk._release()
    time.sleep(0.05)
    assert started == []
    assert ended == [], "no hold started, so no hold should end"


def test_modifier_starts_immediately_no_onset_clipping():
    """A modifier types nothing, so there is no tap to disambiguate and nothing
    to wait for. Waiting would discard the first words of every dictation — the
    pre-speech padding is a silence lead-in, not buffered audio, so speech
    before the hold starts is simply gone. Matches evdev_hold.py on Linux, so
    the two platforms feel the same."""
    hk, started, _ = _hotkey(key_id="right_ctrl", threshold_ms=1000)
    hk._press()
    assert started == [0], "modifier must record from the instant it goes down"


def test_modifier_release_ends_the_hold_even_below_the_threshold():
    hk, started, ended = _hotkey(key_id="right_ctrl", threshold_ms=1000)
    hk._press()
    hk._release()
    assert started == [0] and ended == [1]


def test_modifier_repeat_does_not_restart_recording():
    hk, started, _ = _hotkey(key_id="right_ctrl")
    hk._press()
    for _ in range(5):  # typematic repeat while held
        hk._press()
    assert started == [0], "auto-repeat must not re-fire hold-start"


def test_release_after_threshold_ends_the_hold():
    hk, started, ended = _hotkey()
    hk._press()
    time.sleep(0.15)
    hk._release()
    assert started == [0]
    assert ended == [1]


def test_repeat_keydowns_do_not_rearm_the_timer():
    """Typematic repeats must not restart the countdown or double-fire."""
    hk, started, _ = _hotkey()
    hk._press()
    for _ in range(5):
        time.sleep(0.02)
        hk._press()
    time.sleep(0.1)
    assert started == [0], f"expected exactly one hold start, got {started}"


def test_space_counts_leaked_characters_across_repeats():
    """A held space leaks one character per repeat; all must be backspaced."""
    hk, started, _ = _hotkey(key_id="space")
    hk._press()
    for _ in range(3):
        hk._press()
    time.sleep(0.15)
    assert started == [4], "leaked-character count must include repeats"


def test_modifier_key_reports_no_leaked_characters():
    hk, started, _ = _hotkey(key_id="right_ctrl")
    hk._press()
    hk._press()
    time.sleep(0.15)
    assert started == [0]


# ---- Elevation / UIPI honesty -------------------------------------------
#
# "Keyboard capture: ok" is about installing the hook and says nothing about
# elevated windows, which UIPI excludes either way. doctor read as "input works
# everywhere" while dictation into an admin window silently went nowhere.


def test_elevation_detail_names_the_consequence_in_each_state():
    from yazses.platform.windows.permissions import elevation_detail

    not_elevated = elevation_detail(False)
    assert "administrator" in not_elevated.lower()
    assert "block" in not_elevated.lower()

    elevated = elevation_detail(True)
    assert "administrator" in elevated.lower()

    unknown = elevation_detail(None)
    assert "could not determine" in unknown.lower()

    # Three genuinely different messages, not one string with a flag in it.
    assert len({not_elevated, elevated, unknown}) == 3


def test_is_elevated_returns_none_off_windows():
    """Must degrade to 'unknown', never raise, on a non-Windows host."""
    from yazses.platform.windows.permissions import is_elevated

    assert is_elevated() is None


def test_doctor_elevation_check_is_windows_only():
    from yazses.system.doctor import _elevation_check

    assert _elevation_check("linux") is None
    assert _elevation_check("darwin") is None


def test_doctor_elevation_check_is_informational_not_a_failure():
    """Running unelevated is correct and more secure -- it must not read FAIL."""
    from yazses.system.doctor import _elevation_check

    check = _elevation_check("windows")
    assert check is not None
    name, status, detail = check
    assert name == "Elevated windows"
    assert status == "OK"
    assert detail


def test_how_to_grant_mentions_the_elevated_window_trap():
    from yazses.platform.windows.permissions import WindowsPermissions

    assert "elevated" in WindowsPermissions().how_to_grant().lower()


# ---- Windows packaging manifests ----------------------------------------
#
# scoop/chocolatey/winget pin a version AND a SHA256 by hand. Nothing in the
# release pipeline touches them, so they silently fall a release behind — and a
# manifest carrying the previous release's checksum fails on submission or, if
# it were published, hands users a file whose hash does not match.


def _repo_root():
    from pathlib import Path

    return Path(__file__).resolve().parent.parent


def _released_version() -> str:
    """The newest published version, from the git tags.

    Deliberately *not* ``pyproject.toml``. A manifest pins a SHA256 of a built
    artefact, which cannot exist until the tag is pushed and CI has published
    the release — so requiring the manifests to match the in-development
    version would turn `main` red on every release commit, for a gap nobody can
    close. The invariant that actually holds is "manifests describe the latest
    release".
    """
    import subprocess

    try:
        out = subprocess.run(
            ["git", "tag", "--list", "v[0-9]*", "--sort=-v:refname"],
            cwd=_repo_root(), capture_output=True, text=True, check=False, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover
        pytest.skip("git unavailable")
    tags = [t.strip().lstrip("v") for t in out.stdout.splitlines() if t.strip()]
    # Ignore pre-releases; manifests only ever describe stable releases.
    stable = [t for t in tags if "-" not in t]
    if not stable:  # pragma: no cover - shallow clone with no tags
        pytest.skip("no release tags available (shallow clone?)")
    return stable[0]


def test_scoop_manifest_tracks_the_released_version():
    import json

    manifest = json.loads((_repo_root() / "packaging/scoop/yazses.json").read_text())
    version = _released_version()
    assert manifest["version"] == version
    assert version in manifest["architecture"]["64bit"]["url"]


def test_chocolatey_nuspec_tracks_the_released_version():
    nuspec = (_repo_root() / "packaging/chocolatey/yazses.nuspec").read_text()
    assert f"<version>{_released_version()}</version>" in nuspec


def test_chocolatey_install_script_points_at_this_release():
    script = (_repo_root() / "packaging/chocolatey/tools/chocolateyinstall.ps1").read_text()
    assert _released_version() in script


def test_winget_manifests_exist_for_this_version():
    root = _repo_root() / "packaging/winget/manifests/m/MSKazemi/YazSes" / _released_version()
    assert root.is_dir(), f"no winget manifest folder for {_released_version()}"
    names = {p.name for p in root.glob("*.yaml")}
    assert names == {
        "MSKazemi.YazSes.installer.yaml",
        "MSKazemi.YazSes.locale.en-US.yaml",
        "MSKazemi.YazSes.yaml",
    }


def test_scoop_and_chocolatey_agree_on_the_checksum():
    """Two channels, one artefact — a mismatch means one was hand-edited."""
    import json
    import re

    scoop = json.loads((_repo_root() / "packaging/scoop/yazses.json").read_text())
    choco = (_repo_root() / "packaging/chocolatey/tools/chocolateyinstall.ps1").read_text()
    match = re.search(r"checksum64\s*=\s*'([0-9a-fA-F]{64})'", choco)
    assert match, "no checksum64 found in chocolateyinstall.ps1"
    assert scoop["architecture"]["64bit"]["hash"].lower() == match.group(1).lower()


def test_no_placeholder_checksums_in_windows_packaging():
    """packaging/README.md's own rule: never commit a placeholder checksum."""
    import re

    for rel in (
        "packaging/scoop/yazses.json",
        "packaging/chocolatey/tools/chocolateyinstall.ps1",
    ):
        text = (_repo_root() / rel).read_text()
        assert not re.search(r"PLACEHOLDER|SKIP|TODO", text, re.IGNORECASE), rel


def test_stop_cancels_a_pending_hold_timer():
    # `space` so a timer is actually pending — a modifier fires on key-down and
    # arms none.
    hk, started, _ = _hotkey(key_id="space", threshold_ms=1000)
    hk._press()
    hk.stop()
    time.sleep(0.05)
    assert started == []
    assert not any(
        t.name.startswith("Thread-") and t.is_alive() and isinstance(t, threading.Timer)
        for t in threading.enumerate()
    )
