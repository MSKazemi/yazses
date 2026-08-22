"""Every directory YazSes writes to must be named where the docs enumerate them.

Found by running the product (2026-08-20). ``yazses`` writes under **five** roots --
`Paths` in `platform/base.py` declares them -- and two user-facing pages claim to say
where things live. Both named two of the five:

* `docs/uninstall.md` step 6 printed ``data: removed`` after checking
  ``~/.config/yazses`` and ``~/.local/share/yazses`` only. On this machine that left
  **3.6 MB in ~/.cache/yazses** and **1.5 MB of daemon logs in ~/.local/state/yazses/log**
  behind, on a page whose own description promises *"complete, honest"* removal. The
  cache is the worse half: `commands/model_manager.py` puts a **2.2 GB** GGUF there.
* `docs/privacy-statement.md` said *"Everything YazSes persists lives in one directory"*.
  It does not, and the log directory it omitted is exactly the one that holds every
  transcript once `log_level = "DEBUG"` is set -- which that same page warns about.

Two more facts were one file apart from their own correction. `platform/windows/paths.py`
opens by warning that the layout is Local, *"despite the ``%APPDATA%`` shorthand often
used for it"* -- and then six surfaces used that shorthand, including a comment twenty
lines below the warning. A Windows user following the README created
``%APPDATA%\\yazses\\config.toml``, which YazSes never reads. And the privacy statement
said the Whisper weights download to the data directory; all six on this machine were in
the Hugging Face cache, where `docs/uninstall.md` had always correctly said they were.

So this file gates the *enumerations* rather than re-checking one path: a new root in
`Paths`, or a doc that names the roaming variable, fails the build.
"""
from __future__ import annotations

import dataclasses
import inspect
import shutil
import subprocess
from pathlib import Path

import pytest

from yazses.platform.base import Paths

REPO = Path(__file__).resolve().parents[1]
UNINSTALL = REPO / "docs" / "uninstall.md"

# The roots as of this test. This set is deliberately written down *and* checked for
# completeness against the dataclass below: naming them is what lets the rest of the
# file say something about each one, and the completeness check is what stops the set
# from silently falling behind the code -- a hand-written set is otherwise the defect.
_KNOWN_ROOTS = frozenset({"config_dir", "state_dir", "cache_dir", "log_dir", "data_dir"})

# Linux spellings, which is what `docs/uninstall.md` gives as its primary commands.
# `state_dir` is absent on purpose: on Linux it resolves to the runtime dir (a tmpfs
# under /run/user), which the OS clears at logout. That exemption is asserted below
# rather than assumed.
_LINUX_PATHS = {
    "config_dir": "~/.config/yazses",
    "data_dir": "~/.local/share/yazses",
    "cache_dir": "~/.cache/yazses",
    "log_dir": "~/.local/state/yazses",
}
_MACOS_PATHS = {
    "config_dir": "~/Library/Application Support/yazses",
    "data_dir": "~/Library/Application Support/yazses",
    "cache_dir": "~/Library/Caches/yazses",
    "log_dir": "~/Library/Logs/yazses",
}

_MIN_ROOTS = 4          # an empty derivation must not pass as "all documented"
_MIN_BACKENDS = 2       # linux + macos both implement autostart


# --- the roots are complete ---------------------------------------------------


def test_the_known_roots_still_match_the_paths_dataclass():
    """A sixth root must not be able to appear without this file being revisited."""
    actual = {f.name for f in dataclasses.fields(Paths)}
    assert actual == _KNOWN_ROOTS, (
        "`Paths` gained or lost a directory root. Decide whether the new one holds "
        "anything a user would want to delete, then add it to _KNOWN_ROOTS and to "
        "docs/uninstall.md -- the page enumerates these and cannot notice an omission "
        f"on its own. Added: {actual - _KNOWN_ROOTS}; removed: {_KNOWN_ROOTS - actual}"
    )


def test_the_only_undocumented_root_is_the_volatile_one():
    """`state_dir` may be skipped only because the OS clears it, not by preference."""
    undocumented = _KNOWN_ROOTS - set(_LINUX_PATHS)
    assert undocumented == {"state_dir"}, undocumented

    from yazses.platform.linux import paths as linux_paths

    source = inspect.getsource(linux_paths.build_paths)
    assert "user_runtime_dir" in source, (
        "state_dir is exempt from the uninstall page because it is the runtime tmpfs. "
        "It no longer is, so it now holds files that survive a reboot and the page "
        "must name it."
    )


# --- the uninstall page names every root --------------------------------------


def _removal_section() -> str:
    """Just the *"Remove your data"* step.

    Scoped rather than searching the whole page, because the verification step at the
    end names the same directories: a `rm -rf` line could be dropped from the
    instructions while the checker still mentioned the path, and a whole-file search
    would call that documented. The mutation harness found exactly that.
    """
    text = UNINSTALL.read_text(encoding="utf-8")
    _, _, rest = text.partition("## 3. Remove your data")
    assert rest, "the uninstall page lost its data-removal step"
    section, _, _ = rest.partition("\n## ")
    return section


@pytest.mark.parametrize("root", sorted(_LINUX_PATHS))
def test_uninstall_names_every_linux_root(root):
    assert _LINUX_PATHS[root] in _removal_section(), (
        f"the 'Remove your data' step never removes {_LINUX_PATHS[root]} ({root}), so a "
        "user who follows it to the letter is left with files YazSes wrote"
    )


@pytest.mark.parametrize("root", sorted(_MACOS_PATHS))
def test_uninstall_names_every_macos_root(root):
    section = _removal_section()
    # The page escapes the space for the shell; compare against both spellings.
    wanted = _MACOS_PATHS[root]
    assert wanted in section or wanted.replace(" ", "\\ ") in section, (
        f"the 'Remove your data' step never removes {wanted} ({root}) for macOS"
    )


def test_the_root_lists_are_not_empty():
    """A guard that iterates is green on an empty collection."""
    assert len(_LINUX_PATHS) >= _MIN_ROOTS
    assert len(_MACOS_PATHS) >= _MIN_ROOTS


def test_the_final_check_covers_every_root_it_told_you_to_remove():
    """Step 6 is the step that prints `data: removed`; it must not print it early."""
    text = UNINSTALL.read_text(encoding="utf-8")
    check = text.split("## 6. Check it is gone", 1)
    assert len(check) == 2, "the uninstall page lost its verification step"
    for root, path in sorted(_LINUX_PATHS.items()):
        assert path in check[1], (
            f"the 'Check it is gone' step never looks at {path} ({root}), so it can "
            "report success while that directory is still populated"
        )


# --- Windows: Local, not Roaming ----------------------------------------------


def test_windows_paths_are_local_not_roaming():
    """The premise of the rule below, read from the code rather than assumed."""
    import ast

    from yazses.platform.windows import paths as win_paths

    # Read the constructor call, not the text: the module's own comments discuss
    # roaming at length precisely because it is the trap, so a substring search finds
    # the warning and calls it a violation.
    tree = ast.parse(inspect.getsource(win_paths.build_paths))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "PlatformDirs"]
    assert calls, "windows/paths.py no longer builds its layout with PlatformDirs"
    for call in calls:
        for kw in call.keywords:
            assert kw.arg != "roaming" or not getattr(kw.value, "value", False), (
                "windows/paths.py now asks platformdirs for a roaming directory, so "
                "%APPDATA% may well be right and the documentation rule below is stale"
            )


def test_no_surface_sends_a_windows_user_to_the_roaming_directory():
    r"""``%APPDATA%\yazses`` is a directory YazSes never reads.

    platformdirs resolves ``CSIDL_LOCAL_APPDATA`` unless ``roaming=True``, which
    `build_paths` does not pass. A user who creates ``%APPDATA%\yazses\config.toml``
    because the README said so gets no error and no effect. Six surfaces said it,
    including one generator whose sibling `gen-example-config.py` had it right.

    The PowerShell form is left alone on purpose: `docs/windows-install.md` removes
    ``$env:APPDATA\yazses`` *and* ``$env:LOCALAPPDATA\yazses`` when uninstalling, which
    is a harmless belt-and-braces cleanup rather than an instruction to put a file there.
    """
    bad = "%APPDATA%\\yazses"
    offenders = []
    # rglob, not glob: the first version of this scan looked at docs/*.md only and
    # passed while docs/how-to/ and two translated index pages still said %APPDATA%.
    for path in [*(REPO / "docs").rglob("*.md"), *REPO.glob("scripts/*.py"),
                 *(REPO / "src").rglob("*.py"), REPO / "README.md",
                 REPO / "man" / "yazses.1"]:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if bad in text:
            offenders.append(path.relative_to(REPO).as_posix())
    assert not offenders, (
        f"these name a directory YazSes never reads: {offenders}. Use %LOCALAPPDATA%."
    )


def test_the_roaming_scan_actually_reads_files():
    """Prove the sweep above has files to sweep, so it cannot pass by finding nothing."""
    scanned = [*(REPO / "docs").rglob("*.md"), *(REPO / "src").rglob("*.py")]
    assert len(scanned) > 400, len(scanned)


# --- uninstall_autostart removes what install_autostart wrote -----------------


def _lifecycle_modules():
    from yazses.platform.linux import lifecycle as linux_lifecycle
    from yazses.platform.macos import lifecycle as macos_lifecycle

    return {"linux": linux_lifecycle.LinuxLifecycle,
            "macos": macos_lifecycle.MacosLifecycle}


def test_every_backend_that_writes_an_autostart_file_also_removes_it():
    """macOS deleted its plist; Linux left its unit file behind for ever.

    Same Protocol method, two meanings -- so the documented uninstall ended with a file
    YazSes had written still on disk, and `systemctl --user list-unit-files` still
    listing a program that was gone.
    """
    backends = _lifecycle_modules()
    assert len(backends) >= _MIN_BACKENDS, backends
    for name, cls in sorted(backends.items()):
        install = inspect.getsource(cls.install_autostart)
        if "write_text" not in install:
            continue
        uninstall = inspect.getsource(cls.uninstall_autostart)
        assert "unlink" in uninstall, (
            f"{name}: install_autostart writes a file that uninstall_autostart never "
            "removes, so uninstalling leaves it behind"
        )


def test_linux_uninstall_autostart_deletes_the_unit_file(tmp_path, monkeypatch):
    """The behaviour itself, driven entirely off tmp_path -- never the real ~/.config."""
    from yazses.platform.linux import lifecycle as mod

    unit = tmp_path / "yazses.service"
    unit.write_text("[Unit]\n", encoding="utf-8")

    class _Fake(mod.LinuxLifecycle):
        def __init__(self) -> None:  # no Paths needed for this method
            pass

        @property
        def _service_file(self) -> Path:
            return unit

    calls: list[list[str]] = []
    monkeypatch.setattr(mod.shutil, "which", lambda _: "/usr/bin/systemctl")
    monkeypatch.setattr(mod.subprocess, "run",
                        lambda argv, **kw: calls.append(list(argv)))

    _Fake().uninstall_autostart()

    assert not unit.exists(), "the unit file survived uninstall_autostart"
    assert ["systemctl", "--user", "disable", "--now", "yazses.service"] in calls
    assert ["systemctl", "--user", "daemon-reload"] in calls, (
        "systemd keeps a removed unit cached until it is told to reload"
    )


def test_uninstall_autostart_is_quiet_when_there_is_nothing_to_remove(tmp_path, monkeypatch):
    """No unit file means no daemon-reload -- an absent file is not an error."""
    from yazses.platform.linux import lifecycle as mod

    unit = tmp_path / "absent.service"

    class _Fake(mod.LinuxLifecycle):
        def __init__(self) -> None:
            pass

        @property
        def _service_file(self) -> Path:
            return unit

    calls: list[list[str]] = []
    monkeypatch.setattr(mod.shutil, "which", lambda _: "/usr/bin/systemctl")
    monkeypatch.setattr(mod.subprocess, "run",
                        lambda argv, **kw: calls.append(list(argv)))

    _Fake().uninstall_autostart()

    assert ["systemctl", "--user", "daemon-reload"] not in calls


def test_the_two_definitions_of_the_unit_path_agree():
    """`autostart.service_path()` and `LinuxLifecycle._service_file` are the same file.

    They are written out separately, so nothing but this compares them; a divergence
    would mean install wrote one path and uninstall removed another.
    """
    from yazses.platform.linux import autostart, lifecycle

    a = inspect.getsource(autostart.service_path)
    b = inspect.getsource(lifecycle.LinuxLifecycle._service_file.fget)
    for part in ('".config"', '"systemd"', '"user"'):
        assert part in a and part in b, (part, a, b)
    assert "yazses.service" in b and "SERVICE_NAME" in a


# --- the cache root is real, not theoretical ----------------------------------


def test_something_actually_downloads_into_the_cache_root():
    """If nothing wrote there, naming it on the uninstall page would be noise."""
    from yazses.commands import model_manager
    from yazses.gaze import download as gaze_download

    assert "user_cache_dir" in inspect.getsource(model_manager)
    assert "user_cache_dir" in inspect.getsource(gaze_download.model_dir)
    biggest = max(m.size_mb for m in model_manager.REGISTRY.values())
    assert biggest > 1000, (
        "the uninstall page calls this cache large enough to matter; if the registry no "
        f"longer holds a multi-GB model ({biggest} MB), soften the wording"
    )


def test_the_log_root_is_where_the_daemon_log_goes():
    """The claim that makes the log directory worth naming: it holds daemon.log."""
    from yazses.core import daemon as daemon_mod

    source = inspect.getsource(daemon_mod)
    assert 'log_dir / "daemon.log"' in source, (
        "the daemon no longer writes daemon.log under paths.log_dir, so the uninstall "
        "page's log step needs rechecking"
    )


def test_shutil_and_subprocess_are_imported_where_the_test_patches_them():
    """Guards the monkeypatch targets above against an import-style change."""
    from yazses.platform.linux import lifecycle as mod

    assert mod.shutil is shutil and mod.subprocess is subprocess
