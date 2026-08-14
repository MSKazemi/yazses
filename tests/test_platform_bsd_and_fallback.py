"""BSD backend selection, and what happens on an OS with no backend at all.

Two separate goals:

1. **BSD is wired up.** FreeBSD/OpenBSD/NetBSD/DragonFly get a real `Platform`
   built from the Linux components, because on a BSD desktop those components
   are genuinely the same code path (XDG paths via platformdirs, evdev, X11/
   Wayland injection tools from ports, Unix-socket IPC). The one real difference
   is autostart: BSDs have no systemd `--user`.

2. **An unknown OS degrades instead of crashing.** Roughly half of YazSes —
   transcribing a file, the text commands — never touches the platform layer, so
   a user on Solaris or Haiku should be told what *does* work rather than handed
   a traceback.

Everything here simulates `sys.platform`; no BSD is required to run it.
"""
from __future__ import annotations

import sys

import pytest

from yazses.platform.base import Paths, UnsupportedPlatformError
from yazses.platform.bsd import BSD_PREFIXES, BsdLifecycle, is_bsd
from yazses.platform.factory import get_platform, reset_platform_cache

# Real `sys.platform` values, version suffix included — that suffix is the whole
# reason detection has to be a prefix match.
BSD_PLATFORMS = ["freebsd14", "freebsd13", "openbsd7", "netbsd10", "dragonfly6"]
UNSUPPORTED = ["sunos5", "haiku1", "aix7", "emscripten", "cygwin"]


@pytest.fixture
def as_platform(monkeypatch):
    """Run the body as though `sys.platform` were something else."""

    def _set(name: str):
        monkeypatch.setattr(sys, "platform", name)
        reset_platform_cache()

    yield _set
    reset_platform_cache()


@pytest.mark.parametrize("name", BSD_PLATFORMS)
def test_bsd_is_detected_despite_the_version_suffix(name: str) -> None:
    """`sys.platform` is "freebsd14", never "freebsd" — an equality check would
    silently never fire and every BSD would fall through to unsupported."""
    assert is_bsd(name) is True


@pytest.mark.parametrize("name", UNSUPPORTED + ["linux", "darwin", "win32"])
def test_non_bsd_is_not_claimed_as_bsd(name: str) -> None:
    assert is_bsd(name) is False


def test_every_declared_prefix_is_actually_detected() -> None:
    """The prefix tuple is the single source of truth; nothing may sit in it
    that detection does not honour."""
    for prefix in BSD_PREFIXES:
        assert is_bsd(prefix) is True
        assert is_bsd(prefix + "99") is True


@pytest.mark.parametrize("name", BSD_PLATFORMS)
def test_bsd_builds_a_real_platform(name: str, as_platform) -> None:
    as_platform(name)
    platform = get_platform()
    # Named for the actual system, not a generic "bsd" — doctor output and bug
    # reports should say which one.
    assert platform.name == name
    assert platform.default_hotkey
    assert platform.paths.config_dir
    for factory in (
        platform.hotkey_factory,
        platform.injector_factory,
        platform.ipc_server_factory,
        platform.ipc_client_factory,
    ):
        assert callable(factory)


@pytest.mark.parametrize("name", BSD_PLATFORMS)
def test_bsd_is_flagged_experimental(name: str, as_platform) -> None:
    """It is wired up, not proven. `doctor` reads this to warn, so losing the
    flag would silently upgrade a guess into a claim."""
    as_platform(name)
    platform = get_platform()
    assert platform.extras.get("experimental") is True
    assert platform.extras.get("family") == "bsd"


def test_bsd_uses_the_same_paths_as_linux(as_platform) -> None:
    """platformdirs already returns the XDG locations BSDs use; the Linux module
    name is historical, nothing in it is Linux-specific.

    Asserted as an *equality against the Linux backend* rather than by looking
    for `.config` in the string. `platformdirs` resolves against the real host,
    not the patched `sys.platform`, so a literal-path assertion tests the
    machine the suite happens to run on: it read `.config` on Linux and macOS
    and `C:\\Users\\...\\AppData\\Local` on the Windows job, which is what turned
    `main` red. Same shape as the earlier POSIX-path assertion that broke the
    Windows job before.

    The equality is also the stronger claim. What matters is not that the string
    contains `.config` — it is that BSD gets *the Linux paths*, which is the
    entire reason the BSD backend reuses that module.
    """
    as_platform("freebsd14")
    bsd_paths = get_platform().paths

    as_platform("linux")
    linux_paths = get_platform().paths

    assert bsd_paths == linux_paths, "BSD must reuse the Linux path layout verbatim"
    assert bsd_paths.config_dir.name == "yazses"


def test_bsd_autostart_refuses_instead_of_writing_a_dead_systemd_unit(tmp_path) -> None:
    """The inherited Linux implementation would write into
    ~/.config/systemd/user/, report success, and produce no autostart at all —
    nothing on a BSD reads that directory."""
    paths = Paths(
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
        cache_dir=tmp_path / "cache",
        log_dir=tmp_path / "log",
        data_dir=tmp_path / "data",
    )
    lifecycle = BsdLifecycle(paths=paths)
    with pytest.raises(RuntimeError) as excinfo:
        lifecycle.install_autostart()
    message = str(excinfo.value)
    assert "rc.d" in message, "the refusal must name the BSD mechanism, not just say no"
    assert "yazses start" in message, "and must say what still works"
    assert not (tmp_path / "config" / "systemd").exists(), "no dead unit file may be written"


def test_bsd_autostart_removal_is_a_noop(tmp_path) -> None:
    """`yazses autostart disable` must not fail on a machine that never had it."""
    paths = Paths(
        config_dir=tmp_path / "c", state_dir=tmp_path / "s", cache_dir=tmp_path / "ca",
        log_dir=tmp_path / "l", data_dir=tmp_path / "d",
    )
    assert BsdLifecycle(paths=paths).uninstall_autostart() is None


def test_bsd_inherits_the_posix_lifecycle() -> None:
    """Only autostart is overridden; PID/spawn/stop are plain POSIX and must not
    be reimplemented."""
    from yazses.platform.linux.lifecycle import LinuxLifecycle

    assert issubclass(BsdLifecycle, LinuxLifecycle)
    # Filter every dunder rather than an allow-list of the ones that existed when
    # this was written: Python 3.13 added `__firstlineno__` and
    # `__static_attributes__` to every class body, so a named exclusion set turns
    # into a failure on the next interpreter release. CI pins 3.11/3.12, so that
    # break would first appear for a user, not here.
    overridden = {name for name in BsdLifecycle.__dict__
                  if not (name.startswith("__") and name.endswith("__"))}
    assert overridden == {"install_autostart", "uninstall_autostart"}, (
        f"BsdLifecycle overrides {sorted(overridden)} — anything beyond autostart "
        f"is POSIX and should be inherited, not forked"
    )


@pytest.mark.parametrize("name", UNSUPPORTED)
def test_unsupported_os_raises_an_actionable_error(name: str, as_platform) -> None:
    as_platform(name)
    with pytest.raises(UnsupportedPlatformError) as excinfo:
        get_platform()
    message = str(excinfo.value)
    assert name in message, "the message must name the platform it saw"
    # It must say what still works — a bare "unsupported" hides that half the
    # tool runs fine here.
    assert "transcribe" in message
    assert "issues" in message, "and where to ask for the platform"


def test_unsupported_message_lists_the_supported_set(as_platform) -> None:
    as_platform("sunos5")
    with pytest.raises(UnsupportedPlatformError) as excinfo:
        get_platform()
    message = str(excinfo.value).lower()
    for expected in ("linux", "macos", "windows", "freebsd"):
        assert expected in message


def test_get_paths_works_without_any_backend(as_platform) -> None:
    """Paths are not a backend. Resolving a config directory must not require an
    OS integration layer — that coupling is what made `transcribe` raise the very
    error claiming `transcribe` worked."""
    from yazses.platform.factory import get_paths

    as_platform("sunos5")
    paths = get_paths()
    assert paths.config_file.name == "config.toml"
    assert paths.data_dir


def _claimed_commands() -> list[str]:
    """The command names the unsupported-OS message advertises.

    Parsed from the very constant the message prints, so the test cannot drift
    from the promise. Adding a command to that list without making it work is a
    failure here rather than a lie on someone's terminal.
    """
    from yazses.platform.factory import OS_INDEPENDENT_COMMANDS

    names: list[str] = []
    for line in OS_INDEPENDENT_COMMANDS:
        # "yazses reflow / table / ..." and "yazses transcribe <file>  ..."
        head = line.split("yazses", 1)[1].strip()
        for part in head.replace("/", " ").split():
            token = part.strip()
            if token.startswith("<") or token.startswith("-") or not token.isalpha():
                continue
            names.append(token)
            if "<" in head and part == head.split()[0]:
                break
    # Drop prose that follows the command words on the transcribe line.
    return names


@pytest.mark.parametrize("command", sorted(set(_claimed_commands())))
def test_claimed_command_never_raises_unsupported_platform(command, as_platform, tmp_path) -> None:
    """Every command the message names must actually run with no backend.

    The bug this pins: the error told the user `yazses transcribe` still worked
    here, and `transcribe` called `get_platform()` — so it raised that exact
    error. A promise printed to users with nothing checking it is just a lie with
    good intentions.

    The audio file must **exist**. Typer validates the path argument before the
    command body runs, so a deliberately-missing file exits at argument parsing
    and never reaches the platform lookup — the first version of this test did
    that and passed against the broken code. An empty file gets past validation,
    runs the body, and fails later at audio decoding, which is a different error
    entirely and exactly what we want to distinguish.
    """
    from typer.testing import CliRunner

    from yazses.cli import app

    as_platform("sunos5")
    if command == "transcribe":
        sample = tmp_path / "empty.wav"
        sample.write_bytes(b"")
        args = [command, str(sample)]
    else:
        args = [command, "x"]
    result = CliRunner().invoke(app, args, env={"COLUMNS": "200"})
    assert not isinstance(result.exception, UnsupportedPlatformError), (
        f"`yazses {command}` is advertised as working without an OS backend, but it "
        f"raised UnsupportedPlatformError"
    )
    combined = (result.output or "") + str(result.exception or "")
    assert "no hold-to-talk backend" not in combined, (
        f"`yazses {command}` surfaced the unsupported-platform message it is listed in"
    )


def test_cli_entry_point_converts_the_error_to_a_message(as_platform, capsys) -> None:
    """`yazses.cli:main` exists to keep a traceback off the screen. Click's
    standalone mode only converts its own exception types, so without this the
    user sees a stack trace where a sentence belongs."""
    from yazses.cli import main

    as_platform("haiku1")
    sys.argv = ["yazses", "doctor"]
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "haiku1" in err
    assert "transcribe" in err
    assert "Traceback" not in err


def test_python_xlib_is_installable_on_bsd() -> None:
    """python-xlib is the *only* hotkey backend a BSD can get — evdev is a C
    extension against <linux/input.h> and does not build there. If this marker
    reverts to Linux-only, `pip install yazses` on FreeBSD silently produces an
    install with no way to read the hotkey at all."""
    from pathlib import Path

    text = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if ln.strip().startswith("'python-xlib"))
    for system in ("FreeBSD", "OpenBSD", "NetBSD", "DragonFly"):
        assert f'platform_system == "{system}"' in line, f"{system} cannot install python-xlib"
    # platform_system, not sys_platform: sys_platform carries the major version on
    # a BSD ("freebsd14"), and PEP 508 has no prefix operator, so a sys_platform
    # list would silently stop matching at the next FreeBSD release.
    assert 'sys_platform == "freebsd' not in line, (
        "match python-xlib on platform_system (unversioned) — a sys_platform value "
        "like 'freebsd14' breaks on the next major release"
    )


def test_evdev_stays_linux_only() -> None:
    """The mirror image: claiming evdev on BSD would make `pip install` fail
    outright there, turning a degraded install into no install."""
    from pathlib import Path

    text = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if ln.strip().startswith("'evdev"))
    assert line.count("sys_platform") == 1 and 'sys_platform == "linux"' in line
    assert "BSD" not in line


def test_bsd_prefers_the_x11_grab_backend(monkeypatch) -> None:
    """On BSD the X11 path is tried FIRST, the reverse of Linux, because evdev is
    typically absent there."""
    import yazses.platform.bsd as bsd

    monkeypatch.setenv("DISPLAY", ":0")
    calls: list[str] = []

    class _Grab:
        def __init__(self, **kwargs):
            calls.append("x11")

    monkeypatch.setattr(
        "yazses.platform.linux.hotkey_xgrab.X11GrabHotkey", _Grab, raising=False
    )
    bsd._make_hotkey("right_alt", 100, lambda *_a: None, lambda *_a: None)
    assert calls == ["x11"], "with DISPLAY set, BSD must not reach for evdev first"


def test_entry_point_in_pyproject_points_at_the_wrapper() -> None:
    """If this reverts to `cli:app`, the graceful message silently stops
    happening and the traceback comes back."""
    from pathlib import Path

    text = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    assert 'yazses = "yazses.cli:main"' in text, (
        "the console script must point at cli:main, the wrapper that converts "
        "UnsupportedPlatformError into a readable message"
    )
