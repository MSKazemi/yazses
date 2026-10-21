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
    paths.pid_file.write_text("4321", encoding="utf-8")
    lifecycle = WindowsLifecycle(paths, alive_probe=lambda pid: False)
    assert lifecycle.is_running() is False


def test_is_running_false_when_probe_says_dead(tmp_path):
    paths = _paths(tmp_path)
    paths.pid_file.write_text("4321", encoding="utf-8")
    lifecycle = WindowsLifecycle(paths, alive_probe=lambda pid: False)
    assert lifecycle.is_running() is False


def test_is_running_consults_the_recorded_pid(tmp_path):
    paths = _paths(tmp_path)
    paths.pid_file.write_text("4321", encoding="utf-8")
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


@pytest.mark.parametrize(
    "image",
    ["python3.11.exe", "python3.exe", "pythonw3.12.exe", "PYTHON3.13.EXE", "pythonw.exe"],
)
def test_tasklist_image_match_accepts_versioned_interpreters(image):
    """The Microsoft Store interpreter runs as python3.11.exe, even when started as
    python.exe. Seen on Windows 11: `tasklist` named a live daemon that way, so
    `status` said "not running", `stop` found nothing, and the tray kept starting
    another one."""
    assert is_yazses_image(f'"{image}","14204","Console","1","18,392 K"')


@pytest.mark.parametrize(
    "image", ["pythonista.exe", "python-installer.exe", "mypython.exe", "python3.11.exe.bak"]
)
def test_tasklist_image_match_still_rejects_lookalikes(image):
    assert not is_yazses_image(f'"{image}","4321","Console","1","5,000 K"')


# ---- Autostart command line ---------------------------------------------


def test_frozen_autostart_is_quoted_and_starts_the_tray(tmp_path, monkeypatch):
    """A username with a space must not break autostart, and --tray is required.

    installer.iss writes `"{app}\\YazSes.exe" --tray`; toggling autostart
    in-app must not overwrite that with something weaker.
    """
    import sys

    exe = tmp_path / "John Smith" / "YazSes.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("", encoding="utf-8")
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
    (scripts / "yazses-tray.exe").write_text("", encoding="utf-8")
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


def _wait_for(predicate, timeout=2.0, interval=0.005):
    """Poll until ``predicate()`` is true, or give up after ``timeout``.

    These tests assert on a callback fired by a background timer thread, and a
    fixed ``time.sleep`` encodes an assumption about scheduler latency that a
    loaded CI runner breaks. ``test_space_counts_leaked_characters_across_repeats``
    failed exactly this way on macOS 3.12 while passing on every other job and
    locally: the 40 ms threshold had not been serviced within the 150 ms the
    test waited. Nothing was wrong with the code under test.

    Polling is both faster on an idle machine and correct on a busy one, and
    the generous timeout is never reached when the behaviour is right.

    **Negative assertions still use a fixed sleep, deliberately.** "Nothing
    fired" has no state to poll for — you can only wait a while and look — so
    those are left alone.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


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
    _wait_for(lambda: started == [1])
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
    # Far inside the 1 s threshold: only a start that skipped the wait passes.
    assert _wait_for(lambda: started == [0], timeout=0.5), (
        "modifier must record from the instant it goes down"
    )


def test_modifier_release_ends_the_hold_even_below_the_threshold():
    hk, started, ended = _hotkey(key_id="right_ctrl", threshold_ms=1000)
    hk._press()
    hk._release()
    _wait_for(lambda: ended == [1])
    assert started == [0] and ended == [1]


def test_modifier_repeat_does_not_restart_recording():
    hk, started, _ = _hotkey(key_id="right_ctrl")
    hk._press()
    for _ in range(5):  # typematic repeat while held
        hk._press()
    _wait_for(lambda: started == [0])
    time.sleep(0.05)  # settle: a wrongly re-fired start would land here
    assert started == [0], "auto-repeat must not re-fire hold-start"


def test_release_after_threshold_ends_the_hold():
    hk, started, ended = _hotkey()
    hk._press()
    _wait_for(lambda: started == [0])
    hk._release()
    _wait_for(lambda: ended == [1])
    assert started == [0]
    assert ended == [1]


# ---- The hook thread never runs the daemon's callbacks ---------------------
#
# Windows waits on a low-level hook for every keystroke in every application.
# on_hold_end transcribes for seconds; run on the hook thread, it froze the
# whole keyboard that long (measured: ten keys typed during a 4 s transcription
# arrived 3.5 s late). _press/_release are what the hook calls, so they must
# return at once however long the callbacks take.


def _blocking_hotkey(key_id="right_ctrl"):
    from yazses.platform.windows.hotkey import WindowsHotkey

    gate = threading.Event()
    calls: list[str] = []

    def on_start(leaked: int) -> None:
        calls.append("start")
        gate.wait(5)

    def on_end() -> None:
        calls.append("end")
        gate.wait(5)

    hk = WindowsHotkey(key_id=key_id, threshold_ms=40, on_hold_start=on_start, on_hold_end=on_end)
    return hk, gate, calls


def _returns_within(fn, seconds: float) -> bool:
    t0 = time.monotonic()
    fn()
    return time.monotonic() - t0 < seconds


def test_a_slow_hold_end_does_not_block_the_release():
    from yazses.platform.windows.hotkey import WindowsHotkey

    transcribing = threading.Event()
    done = threading.Event()

    def transcribe() -> None:
        transcribing.set()
        done.wait(5)

    hk = WindowsHotkey("right_ctrl", 40, on_hold_start=lambda n: None, on_hold_end=transcribe)
    try:
        hk._press()
        assert _returns_within(hk._release, 0.5), "release waited for the transcription"
        assert transcribing.wait(2), "the transcription never ran"
    finally:
        done.set()
        hk._teardown()


def test_a_slow_hold_start_does_not_block_the_press():
    hk, gate, calls = _blocking_hotkey()
    try:
        assert _returns_within(hk._press, 0.5), "press waited for on_hold_start"
    finally:
        gate.set()
        hk._teardown()


def test_keys_pressed_during_a_transcription_are_still_seen_in_order():
    """A second dictation started while the first one is still transcribing is
    queued behind it, never run alongside it or dropped."""
    hk, gate, calls = _blocking_hotkey()
    try:
        hk._press()
        hk._release()
        hk._press()  # while the first start is still blocked
        hk._release()
        time.sleep(0.05)
        assert calls == ["start"], "a callback ran alongside one still in progress"
        gate.set()
        assert _wait_for(lambda: calls == ["start", "end", "start", "end"])
    finally:
        gate.set()
        hk._teardown()


def test_a_threshold_start_is_never_overtaken_by_its_release():
    """For `space` the start fires from the threshold timer. If the release
    lands while that start is still running, the end must wait for it."""
    hk, gate, calls = _blocking_hotkey(key_id="space")
    try:
        hk._press()
        assert _wait_for(lambda: calls == ["start"])
        hk._release()
        time.sleep(0.05)
        assert calls == ["start"], "the end ran before the start had finished"
        gate.set()
        assert _wait_for(lambda: calls == ["start", "end"])
    finally:
        gate.set()
        hk._teardown()


def test_a_raising_callback_does_not_stop_later_ones():
    from yazses.platform.windows.hotkey import WindowsHotkey

    ended: list[int] = []

    def boom(leaked: int) -> None:
        raise RuntimeError("microphone vanished")

    hk = WindowsHotkey("right_ctrl", 40, on_hold_start=boom, on_hold_end=lambda: ended.append(1))
    try:
        for _ in range(2):
            hk._press()
            hk._release()
        assert _wait_for(lambda: ended == [1, 1])
    finally:
        hk._teardown()


def test_teardown_stops_the_callback_thread_after_queued_work():
    hk, gate, calls = _blocking_hotkey()
    hk._press()
    hk._release()
    assert _wait_for(lambda: calls == ["start"])
    worker = hk._callbacks._thread
    assert worker is not None
    hk._teardown()
    gate.set()
    worker.join(2)
    assert not worker.is_alive()
    assert calls == ["start", "end"], "a release seen before stop() lost its transcription"


def test_repeat_keydowns_do_not_rearm_the_timer():
    """Typematic repeats must not restart the countdown or double-fire."""
    hk, started, _ = _hotkey()
    hk._press()
    for _ in range(5):
        time.sleep(0.02)
        hk._press()
    _wait_for(lambda: len(started) >= 1)
    time.sleep(0.05)  # settle: a second, wrongly re-armed fire would land here
    assert started == [0], f"expected exactly one hold start, got {started}"


def test_space_counts_leaked_characters_across_repeats():
    """A held space leaks one character per repeat; all must be backspaced."""
    hk, started, _ = _hotkey(key_id="space")
    hk._press()
    for _ in range(3):
        hk._press()
    _wait_for(lambda: started == [4])
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


def test_is_elevated_degrades_to_unknown_and_never_raises():
    """Must answer on Windows and degrade to 'unknown' elsewhere, never raise.

    Asserting `is None` unconditionally passes only off Windows — which is where
    this suite usually runs, so it looked fine and failed the moment the Windows
    matrix ran it. The contract is per-platform, so the test has to be too.
    """
    import sys

    from yazses.platform.windows.permissions import is_elevated

    result = is_elevated()
    if sys.platform == "win32":
        # A real answer, or None if the token probe itself failed.
        assert result is None or isinstance(result, bool)
    else:
        assert result is None, "must not claim to know elevation off Windows"


def test_doctor_elevation_check_is_windows_only():
    from yazses.system.doctor import _elevation_check

    assert _elevation_check("linux") is None
    assert _elevation_check("darwin") is None


def test_doctor_elevation_check_is_informational_not_a_failure():
    """Running unelevated is correct and more secure -- it must not read FAIL."""
    from yazses.platform.base import WINDOWS_PLATFORM_NAME
    from yazses.system.doctor import _elevation_check

    # Not the literal "windows": that is a name no backend declares, and passing
    # it here is what kept this test green while the row was unreachable on the
    # real OS. See tests/test_doctor_platform_names.py.
    check = _elevation_check(WINDOWS_PLATFORM_NAME)
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
# scoop/chocolatey/winget pin a version AND a SHA256. A manifest carrying the
# previous release's checksum fails on submission or, if it were published,
# hands users a file whose hash does not match. `scripts/refresh-package-
# manifests.py` rewrites them from the real release assets after each tag.
#
# What they are measured against is the tree, never the git tags (#602) — see
# `tests/release_window.py` for why, and for the replay of `main` that shows it.


def _repo_root():
    from pathlib import Path

    return Path(__file__).resolve().parent.parent


def _released_version(root=None) -> str:
    """The release the committed manifests describe, as the tree records it.

    `packaging/released-assets.json` is written by the same
    `refresh-package-manifests.py` run that rewrites every checksum, from the
    same `gh release view` call, so it is the tree's own record of "the newest
    release whose assets were really read". It changes only when a refresh
    lands — which is exactly when the manifests change.

    **Deliberately not the git tags.** This used to return the newest tag (and,
    after v2.18.1 deadlocked its own release, the newest tag *before* the one in
    `GITHUB_REF_NAME`). Tags are global state that moves underneath a commit:
    the moment `v2.43.0` was pushed, every pull request and every commit on
    `main` went red until the refresh commit landed hours later (#602), for a
    change none of them made. A guard that one push can turn red on a tree it
    never touched is not measuring the tree.

    **Deliberately not `pyproject.toml` either.** The checksums cannot exist
    until after the tag, so "manifests == project version" fails on every
    release commit. Staleness is bounded instead by
    `test_released_version_is_within_one_release_of_the_project`.
    """
    import json

    base = _repo_root() if root is None else root
    data = json.loads((base / "packaging/released-assets.json").read_text(encoding="utf-8"))
    return str(data["version"])


def _project_version(root) -> str:
    import tomllib

    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def _release_window_problems(root) -> list[str]:
    """Why the recorded release is outside the one-release window, if it is."""
    from tests.release_window import release_window

    project = _project_version(root)
    released = _released_version(root)
    allowed = release_window(project, (root / "CHANGELOG.md").read_text(encoding="utf-8"))
    if released in allowed:
        return []
    return [
        f"packaging/ describes release {released}, but this tree is at {project} and "
        f"may only lag it by one release ({sorted(allowed)}). A post-tag refresh was "
        f"skipped: run scripts/refresh-package-manifests.py --version <the last "
        f"published release>."
    ]


def _scoop_problems(root, version: str) -> list[str]:
    import json

    manifest = json.loads((root / "packaging/scoop/yazses.json").read_text(encoding="utf-8"))
    problems = []
    if manifest["version"] != version:
        problems.append(f"scoop version {manifest['version']} != {version}")
    if version not in manifest["architecture"]["64bit"]["url"]:
        problems.append(f"scoop 64bit url does not name {version}")
    return problems


def _nuspec_problems(root, version: str) -> list[str]:
    nuspec = (root / "packaging/chocolatey/yazses.nuspec").read_text(encoding="utf-8")
    return [] if f"<version>{version}</version>" in nuspec else [f"nuspec is not {version}"]


def _choco_script_problems(root, version: str) -> list[str]:
    script = (root / "packaging/chocolatey/tools/chocolateyinstall.ps1").read_text(encoding="utf-8")
    return [] if version in script else [f"chocolateyinstall.ps1 does not name {version}"]


def _winget_problems(root, version: str) -> list[str]:
    folder = root / "packaging/winget/manifests/m/MSKazemi/YazSes" / version
    if not folder.is_dir():
        return [f"no winget manifest folder for {version}"]
    names = {p.name for p in folder.glob("*.yaml")}
    expected = {
        "MSKazemi.YazSes.installer.yaml",
        "MSKazemi.YazSes.locale.en-US.yaml",
        "MSKazemi.YazSes.yaml",
    }
    return [] if names == expected else [f"winget {version} has {sorted(names)}"]


def _windows_manifest_problems(root) -> list[str]:
    """Every check below, on any tree — the repository or a fabricated one."""
    version = _released_version(root)
    return (
        _release_window_problems(root)
        + _scoop_problems(root, version)
        + _nuspec_problems(root, version)
        + _choco_script_problems(root, version)
        + _winget_problems(root, version)
    )


def test_released_version_is_within_one_release_of_the_project():
    """The staleness bound that the tag comparison used to provide.

    A skipped refresh is red from the next release commit on — and `release.yml`
    runs this suite at the tag, so that release cannot publish to PyPI on top of
    manifests two releases old. Between releases, a refresh that is late but not
    skipped is the scheduled lane's to report: `channel-drift.yml` compares the
    Scoop bucket served from `main` (and every external channel) with the newest
    release daily, after a 24-hour grace, without blocking anyone's PR.
    """
    assert _release_window_problems(_repo_root()) == []


def test_scoop_manifest_tracks_the_released_version():
    assert _scoop_problems(_repo_root(), _released_version()) == []


def test_chocolatey_nuspec_tracks_the_released_version():
    assert _nuspec_problems(_repo_root(), _released_version()) == []


def test_chocolatey_install_script_points_at_this_release():
    assert _choco_script_problems(_repo_root(), _released_version()) == []


def test_winget_manifests_exist_for_this_version():
    assert _winget_problems(_repo_root(), _released_version()) == []


def test_scoop_and_chocolatey_agree_on_the_checksum():
    """Two channels, one artefact — a mismatch means one was hand-edited."""
    import json
    import re

    scoop = json.loads((_repo_root() / "packaging/scoop/yazses.json").read_text(encoding="utf-8"))
    choco = (_repo_root() / "packaging/chocolatey/tools/chocolateyinstall.ps1").read_text(encoding="utf-8")
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
        text = (_repo_root() / rel).read_text(encoding="utf-8")
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


def _fake_release_tree(root, *, project: str, released: str, history: list[str]):
    """A minimal tree holding just what the Windows manifest checks read.

    `history` is the CHANGELOG's released versions, newest first. The manifests
    are rendered for `released`, the way one refresh run writes them together.
    """
    import json

    (root / "pyproject.toml").write_text(
        f'[project]\nname = "yazses"\nversion = "{project}"\n', encoding="utf-8"
    )
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n"
        + "".join(f"## [{v}] - 2026-10-17\n\n- notes\n\n" for v in history),
        encoding="utf-8",
    )
    pkg = root / "packaging"
    (pkg / "scoop").mkdir(parents=True)
    (pkg / "chocolatey" / "tools").mkdir(parents=True)
    url = f"https://github.com/MSKazemi/yazses/releases/download/v{released}/YazSes-{released}-windows-x64.exe"
    (pkg / "released-assets.json").write_text(
        json.dumps({"version": released, "assets": [f"YazSes-{released}-windows-x64.exe"]}),
        encoding="utf-8",
    )
    (pkg / "scoop" / "yazses.json").write_text(
        json.dumps({"version": released, "architecture": {"64bit": {"url": url}}}),
        encoding="utf-8",
    )
    (pkg / "chocolatey" / "yazses.nuspec").write_text(
        f"<package><metadata><version>{released}</version></metadata></package>\n",
        encoding="utf-8",
    )
    (pkg / "chocolatey" / "tools" / "chocolateyinstall.ps1").write_text(
        f"url64bit = '{url}'\n", encoding="utf-8"
    )
    winget = pkg / "winget/manifests/m/MSKazemi/YazSes" / released
    winget.mkdir(parents=True)
    for name in (
        "MSKazemi.YazSes.installer.yaml",
        "MSKazemi.YazSes.locale.en-US.yaml",
        "MSKazemi.YazSes.yaml",
    ):
        (winget / name).write_text(f"PackageVersion: {released}\n", encoding="utf-8")


def _tags_say(monkeypatch, newest: str) -> None:
    """Make the environment look exactly like #602: a newer tag exists, on a branch run.

    `git tag` would answer `newest` first, and Actions says this is a branch (or
    pull-request) build. Neither may move the verdict.
    """
    import subprocess

    real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        if list(cmd[:2]) == ["git", "tag"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=f"v{newest}\n", stderr="")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("GITHUB_REF_TYPE", "branch")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")


def test_the_bump_window_does_not_turn_unrelated_trees_red(tmp_path, monkeypatch):
    """#602, simulated: `v2.43.0` is tagged, its assets are not yet refreshed in.

    This is the tree every PR based on `d9576a52` carried on 2026-10-17: project
    2.43.0, every manifest still at 2.42.0, and the newest tag already v2.43.0.
    The old tag-based reference failed all four manifest tests on it; a correct
    tree in that state must be green, or the guard punishes PRs for a release.
    """
    _tags_say(monkeypatch, newest="2.43.0")
    _fake_release_tree(tmp_path, project="2.43.0", released="2.42.0",
                       history=["2.43.0", "2.42.0", "2.41.0"])
    assert _windows_manifest_problems(tmp_path) == []


def test_the_refreshed_tree_is_green(tmp_path):
    """The other side of the window: the refresh commit has landed."""
    _fake_release_tree(tmp_path, project="2.43.0", released="2.43.0",
                       history=["2.43.0", "2.42.0"])
    assert _windows_manifest_problems(tmp_path) == []


def test_a_skipped_refresh_is_red_at_the_next_release(tmp_path):
    """The release-time guarantee the tag comparison gave, kept.

    v2.43.0's refresh never happened, and the v2.43.1 release commit is cut on
    top. The window moved to {2.43.1, 2.43.0}; manifests at 2.42.0 fall outside
    it, so `release.yml` — which runs this suite at the tag — stops before PyPI.
    """
    _fake_release_tree(tmp_path, project="2.43.1", released="2.42.0",
                       history=["2.43.1", "2.43.0", "2.42.0"])
    problems = _windows_manifest_problems(tmp_path)
    assert len(problems) == 1 and "skipped" in problems[0], problems


def test_a_manifest_that_drifts_from_the_recorded_release_is_red(tmp_path):
    """Inside the window, the manifests must still match each other's release."""
    _fake_release_tree(tmp_path, project="2.43.0", released="2.43.0",
                       history=["2.43.0", "2.42.0"])
    nuspec = tmp_path / "packaging/chocolatey/yazses.nuspec"
    nuspec.write_text(nuspec.read_text(encoding="utf-8").replace("2.43.0", "2.42.0"),
                      encoding="utf-8")
    assert _windows_manifest_problems(tmp_path) == ["nuspec is not 2.43.0"]


def test_the_released_version_reads_no_tags_and_no_environment(monkeypatch):
    """One commit, one verdict: the reference must not depend on when it runs.

    Pinned because "read the newest tag" is the obvious-looking way back to
    #602. Any call to subprocess fails this test, and the Actions ref variables
    — which the tag-based version branched on — are set to a tag and must not
    move the answer.
    """
    import subprocess

    baseline = _released_version()

    def no_subprocess(*args, **kwargs):
        raise AssertionError(f"the manifest reference shelled out: {args!r}")

    monkeypatch.setattr(subprocess, "run", no_subprocess)
    monkeypatch.setenv("GITHUB_REF_TYPE", "tag")
    monkeypatch.setenv("GITHUB_REF_NAME", "v99.0.0")
    assert _released_version() == baseline
    assert _release_window_problems(_repo_root()) == []


def test_scoop_bucket_copy_matches_the_packaging_manifest():
    """`scoop bucket add yazses https://github.com/MSKazemi/yazses` reads
    bucket/yazses.json. It is a copy of packaging/scoop/yazses.json, and a copy
    that drifts is worse than no bucket at all: Scoop would serve a version
    whose checksum no longer matches the asset, failing on every user's machine
    at once. Scoop Extras requires 100 stars / 50 forks, so this self-hosted
    bucket is the only Scoop route the project controls.
    """
    import json

    root = _repo_root()
    packaged = json.loads((root / "packaging" / "scoop" / "yazses.json").read_text(encoding="utf-8"))
    served = json.loads((root / "bucket" / "yazses.json").read_text(encoding="utf-8"))
    assert served == packaged, (
        "bucket/yazses.json drifted from packaging/scoop/yazses.json — copy it over"
    )


def test_scoop_manifest_shims_the_cli():
    """Without a `bin` entry Scoop installs the tray and shortcuts but no
    command, and every diagnostic (doctor, verify, status, report) lives in the
    CLI. The shim must point at the console binary, not the windowed one, which
    has no stdout to print to."""
    import json

    m = json.loads((_repo_root() / "packaging" / "scoop" / "yazses.json").read_text(encoding="utf-8"))
    assert "bin" in m, "Scoop users would have no `yazses` command at all"
    flat = [x for entry in m["bin"] for x in (entry if isinstance(entry, list) else [entry])]
    assert "yazses-cli.exe" in flat
    assert "YazSes.exe" not in flat, "the windowed binary cannot print to a console"
