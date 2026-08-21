"""How YazSes starts another part of itself, across the three worlds it ships in.

Six call sites -- the daemon launching the tray and the overlay, the tray's Settings
button, the Settings window's Restart, and two lifecycle backends starting the daemon
-- each answered "what command runs this component?" with
``[sys.executable, "-m", "yazses.x"]``.

That is right for a pip/pipx/uv install and **silently wrong inside the shipped
macOS/Windows bundles**, which is the shape this repository keeps rediscovering. In a
PyInstaller bundle ``sys.executable`` is the app, not an interpreter; the bundle
dispatches on argv and an unrecognised first argument falls through to the CLI, which
exits 2; and a windowed binary has no console to print that to. The tray never
appears, Apply→Restart never restarts, and nothing reports a failure.

None of that can be exercised here -- there is no bundle, no Windows, no macOS -- so
every input is injected and the decision is tested rather than the spawn.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yazses.system.relaunch import MODES, Mode, command_for

NOTHING_ON_PATH = lambda _name: None  # noqa: E731 - a stub, not a definition
NOTHING_EXISTS = lambda _path: False  # noqa: E731
EVERYTHING_EXISTS = lambda _path: True  # noqa: E731


# --- the frozen bundles -------------------------------------------------------


def test_a_frozen_bundle_is_asked_by_its_mode_flag_not_by_dash_m() -> None:
    """The whole defect in one assertion.

    ``YazSesApp.exe -m yazses.tray.app`` reaches Typer as the flag ``-m``, exits 2,
    and prints nothing because the binary is windowed. ``--tray`` is a branch the
    bundle actually has.
    """
    exe = Path(r"C:\Program Files\YazSes\YazSesApp.exe")
    cmd = command_for(
        Mode.TRAY, frozen=True, executable=exe, which=NOTHING_ON_PATH,
        windows=True, exists=NOTHING_EXISTS,
    )
    assert cmd == [str(exe), "--tray"]
    assert "-m" not in cmd


def test_the_macos_app_ships_one_binary_so_no_sibling_is_named() -> None:
    """The bug this found, and the reason the sibling is *tested* not assumed.

    `packaging/macos/yazses.spec` builds exactly one `EXE(...)`. The previous
    resolver returned `Contents/MacOS/yazses-cli` on any non-Windows frozen build --
    a path that does not exist in the .app -- so the tray's Settings… button was
    broken on macOS, and the test asserting it locked the wrong answer in.
    """
    exe = Path("/Applications/YazSes.app/Contents/MacOS/YazSes")
    cmd = command_for(
        Mode.SETTINGS, frozen=True, executable=exe, which=NOTHING_ON_PATH,
        windows=False, exists=NOTHING_EXISTS,
    )
    assert cmd == [str(exe), "--settings"]


def test_windows_routes_console_work_through_the_console_binary() -> None:
    """A GUI-subsystem binary has no stdout, so `yazses doctor` on it prints nothing.
    The Windows bundle ships `yazses-cli.exe` beside it for exactly this."""
    exe = Path(r"C:\Program Files\YazSes\YazSesApp.exe")
    cmd = command_for(
        Mode.CLI, "doctor", frozen=True, executable=exe, which=NOTHING_ON_PATH,
        windows=True, exists=EVERYTHING_EXISTS,
    )
    assert cmd == [str(exe.with_name("yazses-cli.exe")), "doctor"]


def test_a_gui_mode_stays_on_the_windowed_binary_even_where_a_console_one_exists() -> None:
    """Settings is a window. Launching it from the console binary would open a
    stray console window behind it for the life of the process."""
    exe = Path(r"C:\Program Files\YazSes\YazSesApp.exe")
    cmd = command_for(
        Mode.SETTINGS, frozen=True, executable=exe, which=NOTHING_ON_PATH,
        windows=True, exists=EVERYTHING_EXISTS,
    )
    assert cmd == [str(exe), "--settings"]


def test_a_frozen_bundle_never_prefers_path() -> None:
    """A machine can carry both the installer's app and a stray old `pip install`.
    Preferring PATH runs the other version against this one's config."""
    exe = Path(r"C:\Program Files\YazSes\YazSesApp.exe")
    cmd = command_for(
        Mode.CLI, "status", frozen=True, executable=exe,
        which=lambda _n: r"C:\Python311\Scripts\yazses.exe",
        windows=True, exists=NOTHING_EXISTS,
    )
    assert cmd == [str(exe), "--cli", "status"]


# --- ordinary installs --------------------------------------------------------


def test_a_console_script_on_path_wins_for_a_normal_install() -> None:
    cmd = command_for(
        Mode.TRAY, frozen=False, executable=Path("/venv/bin/python"),
        which=lambda n: f"/usr/local/bin/{n}",
    )
    assert cmd == ["/usr/local/bin/yazses-tray"]


def test_settings_uses_its_own_gui_script() -> None:
    """`yazses-settings` is declared in `[project.gui-scripts]`, so on Windows it is
    launched by `pythonw.exe` and opens no console behind the window. Routing through
    `yazses settings` would also work and would flash one."""
    cmd = command_for(
        Mode.SETTINGS, frozen=False, executable=Path("/venv/bin/python"),
        which=lambda n: f"/usr/local/bin/{n}",
    )
    assert cmd == ["/usr/local/bin/yazses-settings"]


def test_a_venv_whose_bin_is_not_exported_still_works() -> None:
    exe = Path("/venv/bin/python")
    cmd = command_for(Mode.DAEMON, frozen=False, executable=exe, which=NOTHING_ON_PATH)
    assert cmd == [str(exe), "-m", "yazses.main"]


def test_arguments_pass_through_in_every_world() -> None:
    exe = Path("/venv/bin/python")
    assert command_for(
        Mode.CLI, "restart", frozen=False, executable=exe, which=NOTHING_ON_PATH
    ) == [str(exe), "-m", "yazses.cli", "restart"]


def test_an_unknown_mode_is_refused_rather_than_guessed() -> None:
    with pytest.raises(ValueError, match="unknown launch mode"):
        command_for("telepathy")


# --- the table and the dispatcher must agree ----------------------------------


def test_every_mode_flag_is_a_branch_the_bundle_actually_has() -> None:
    """The failure mode is silent, so the table cannot be allowed to drift from
    `__main__.py`. `--overlay` did not exist there: the daemon's overlay launch had
    no argv a bundle would accept, which is why the overlay was unreachable from a
    .app or .exe by construction."""
    source = (Path(__file__).resolve().parent.parent / "src/yazses/__main__.py").read_text(
        encoding="utf-8"
    )
    for mode, (flag, _script, _module) in MODES.items():
        assert f'== "{flag}"' in source or f'mode = "{flag}"' in source, (
            f"mode {mode!r} resolves to {flag!r}, and __main__.py has no branch for "
            f"it. A bundle handed that flag falls through to the CLI, exits 2, and "
            f"has no console to say so."
        )


@pytest.mark.parametrize("mode", sorted(MODES))
def test_every_mode_is_importable(mode: str) -> None:
    """The `-m` fallback names a module; a typo there fails only on the machine that
    takes the fallback, which is the least-tested path of the three."""
    import importlib.util

    _flag, _script, module = MODES[mode]
    assert importlib.util.find_spec(module) is not None, f"{module} does not exist"


def test_every_console_script_is_declared_in_pyproject() -> None:
    """The PATH branch names a console script. If pyproject stops shipping one, this
    resolver would hand back a command nothing can run."""
    import tomllib

    root = Path(__file__).resolve().parent.parent
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    declared = set(data["project"].get("scripts", {})) | set(
        data["project"].get("gui-scripts", {})
    )
    assert declared, "no console scripts parsed — this guard would be vacuous"
    for mode, (_flag, script, _module) in MODES.items():
        assert script in declared, f"mode {mode!r} uses console script {script!r}, undeclared"


def test_a_sibling_console_script_beats_one_on_path() -> None:
    """The multi-install case, which is this machine's ordinary state.

    A pipx copy, a `uv tool` copy and a checkout's venv coexist here. PATH answers
    with whichever came first, so a daemon running out of one install could launch
    the tray out of another — two processes disagreeing about config, version and
    socket, with nothing to indicate why.
    """
    exe = Path("/home/u/.local/pipx/venvs/yazses/bin/python")
    cmd = command_for(
        Mode.TRAY, frozen=False, executable=exe,
        which=lambda _n: "/usr/local/bin/yazses-tray",   # a different install
        windows=False, exists=EVERYTHING_EXISTS,
    )
    assert cmd == [str(exe.with_name("yazses-tray"))]


def test_the_sibling_lookup_uses_the_windows_extension() -> None:
    """`Path.exists` on `...\\Scripts\\yazses-tray` is False for a real
    `yazses-tray.exe`, so the check would silently never fire on Windows."""
    exe = Path(r"C:\venv\Scripts\python.exe")
    cmd = command_for(
        Mode.TRAY, frozen=False, executable=exe, which=lambda _n: None,
        windows=True, exists=lambda p: p.name == "yazses-tray.exe",
    )
    assert cmd == [str(exe.with_name("yazses-tray.exe"))]


def test_the_settings_sibling_is_the_gui_script() -> None:
    exe = Path("/venv/bin/python")
    cmd = command_for(
        Mode.SETTINGS, frozen=False, executable=exe, which=lambda _n: None,
        windows=False, exists=EVERYTHING_EXISTS,
    )
    assert cmd == [str(exe.with_name("yazses-settings"))]


def test_every_fallback_module_can_actually_be_run_with_dash_m() -> None:
    """The fallback was decorative for two of the five.

    `python -m yazses.cli --version` printed nothing and exited 0: the module had no
    `if __name__ == "__main__"` block, so it was imported and discarded. That is the
    documented last-resort launch path — what `tray/launch.py` and the Settings
    window's Restart reach for when no console script exists — and it did nothing, on
    exactly the installs with no other way to report it.

    Checked statically rather than by running them: three of the five open windows or
    take over the microphone.
    """
    root = Path(__file__).resolve().parent.parent / "src"
    for mode, (_flag, _script, module) in MODES.items():
        source = (root / Path(*module.split("."))).with_suffix(".py").read_text(
            encoding="utf-8"
        )
        assert '__name__ == "__main__"' in source, (
            f"mode {mode!r} falls back to `-m {module}`, and that module has no "
            f"__main__ block — running it imports the module and exits 0, doing "
            f"nothing and reporting success."
        )


def test_the_cli_fallback_really_produces_output() -> None:
    """One end-to-end confirmation, on the one mode that is safe to execute: it
    neither opens a window nor claims the microphone."""
    import subprocess
    import sys as _sys

    proc = subprocess.run(
        [_sys.executable, "-m", "yazses.cli", "--version"],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert "yazses" in proc.stdout.lower(), f"no version printed: {proc.stdout!r}"
