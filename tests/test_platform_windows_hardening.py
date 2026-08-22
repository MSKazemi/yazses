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
    _wait_for(lambda: started == [0])
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

    **The tag alone does not measure that, and v2.18.1 proved it.** Using the
    newest tag moved the impossible gap rather than closing it: the moment a tag
    is pushed, the newest tag *is* the release being made, whose assets do not
    exist yet — and `release.yml` runs this suite at that tag, with the PyPI and
    `.deb` publish behind it. v2.18.1 was the first release cut after these
    tests landed, and it deadlocked exactly there: the GitHub release published
    its `.exe` and `.dmg`, and PyPI never got the version at all.

    So when we are running *inside* the release of tag X, the latest **released**
    version is the newest stable tag **before** X. `GITHUB_REF_TYPE`/
    `GITHUB_REF_NAME` say which tag is in flight; both are set by Actions on a
    tag push and absent everywhere else.

    This does not weaken the gate. On `main` — no tag ref — the behaviour is
    unchanged: manifests must match the newest tag, so `main` still goes red
    after a release until they are refreshed, which is the pressure that keeps
    them honest.
    """
    import os
    import subprocess

    # `out` is bound before the try so the read below is unconditionally safe.
    # pytest.skip() does raise, but nothing in the signature says so, and a
    # reader (or a static analyser) has to take the fall-through on trust.
    out: subprocess.CompletedProcess[str] | None = None
    try:
        out = subprocess.run(
            ["git", "tag", "--list", "v[0-9]*", "--sort=-v:refname"],
            cwd=_repo_root(), capture_output=True, text=True, check=False, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover
        pass
    if out is None:  # pragma: no cover - git missing from the image
        pytest.skip("git unavailable")
    tags = [t.strip().lstrip("v") for t in out.stdout.splitlines() if t.strip()]
    # Ignore pre-releases; manifests only ever describe stable releases.
    stable = [t for t in tags if "-" not in t]
    # Drop the tag currently being released — its assets do not exist yet.
    if os.environ.get("GITHUB_REF_TYPE") == "tag":
        in_flight = os.environ.get("GITHUB_REF_NAME", "").lstrip("v")
        stable = [t for t in stable if t != in_flight]
    if not stable:  # pragma: no cover - shallow clone, or the very first release
        pytest.skip("no published release tag available (shallow clone, or first release?)")
    return stable[0]


def test_scoop_manifest_tracks_the_released_version():
    import json

    manifest = json.loads((_repo_root() / "packaging/scoop/yazses.json").read_text(encoding="utf-8"))
    version = _released_version()
    assert manifest["version"] == version
    assert version in manifest["architecture"]["64bit"]["url"]


def test_chocolatey_nuspec_tracks_the_released_version():
    nuspec = (_repo_root() / "packaging/chocolatey/yazses.nuspec").read_text(encoding="utf-8")
    assert f"<version>{_released_version()}</version>" in nuspec


def test_chocolatey_install_script_points_at_this_release():
    script = (_repo_root() / "packaging/chocolatey/tools/chocolateyinstall.ps1").read_text(encoding="utf-8")
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


def test_released_version_ignores_the_tag_being_released(monkeypatch):
    """The v2.18.1 deadlock, pinned.

    Cutting a release runs this suite at the new tag, before its assets exist.
    If `_released_version()` returned that tag, the manifest tests could never
    pass during a release — and the job that publishes to PyPI sits behind
    them. v2.18.1 hit exactly this: the `.exe` and `.dmg` published, PyPI did
    not get the version at all.
    """
    newest = _released_version()          # no tag ref set: the newest stable tag

    monkeypatch.setenv("GITHUB_REF_TYPE", "tag")
    monkeypatch.setenv("GITHUB_REF_NAME", f"v{newest}")
    during_release = _released_version()

    assert during_release != newest, (
        "the tag being released is still reported as the latest release, so the "
        "manifest tests can never pass during a release"
    )


def test_released_version_is_unchanged_outside_a_release(monkeypatch):
    """On `main` the gate must keep biting, or stale manifests ship unnoticed."""
    monkeypatch.delenv("GITHUB_REF_TYPE", raising=False)
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)
    baseline = _released_version()

    # A branch push sets ref_type=branch; the manifests must still match the newest tag.
    monkeypatch.setenv("GITHUB_REF_TYPE", "branch")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    assert _released_version() == baseline


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
