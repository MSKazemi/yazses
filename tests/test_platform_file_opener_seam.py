"""`get_file_opener()` is where `yazses fileopen` learns how to open a file on this OS.

`fileopen/launcher.py` used to branch on `sys.platform` itself, which AGENTS.md rule 6
reserves for the platform seam. The behaviour it must keep is pinned in
`test_fileopen_launcher_bsd.py` (the BSDs and Linux use `xdg-open`, macOS `open`, any
other OS is refused by name); this file pins the seam that now carries it: the
`FileOpener` Protocol in `platform/base.py`, one implementation per OS family, the
dispatch in `platform/factory.py`, and a source-level guard that the launcher stays off
`sys.platform`.
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from yazses.fileopen.launcher import launch_file
from yazses.platform import FileOpener, get_file_opener
from yazses.platform.linux.fileopen import LinuxFileOpener
from yazses.platform.macos.fileopen import MacosFileOpener
from yazses.platform.windows.fileopen import WindowsFileOpener

LAUNCHER = Path(__file__).resolve().parent.parent / "src" / "yazses" / "fileopen" / "launcher.py"


@pytest.mark.parametrize("impl", [LinuxFileOpener, MacosFileOpener, WindowsFileOpener])
def test_every_backend_satisfies_the_protocol(impl) -> None:
    assert isinstance(impl(), FileOpener)


@pytest.mark.parametrize(
    ("platform_name", "expected"),
    [
        ("linux", LinuxFileOpener),
        ("freebsd14", LinuxFileOpener),
        ("openbsd7", LinuxFileOpener),
        ("darwin", MacosFileOpener),
        ("win32", WindowsFileOpener),
    ],
)
def test_the_factory_dispatches_on_the_platform(platform_name, expected) -> None:
    with patch.object(sys, "platform", platform_name):
        assert type(get_file_opener()) is expected


def test_an_os_with_no_backend_is_refused_by_name() -> None:
    with patch.object(sys, "platform", "aix7"), pytest.raises(NotImplementedError, match="aix7"):
        get_file_opener()


@pytest.mark.parametrize(("impl", "argv0"), [(LinuxFileOpener, "xdg-open"), (MacosFileOpener, "open")])
def test_the_posix_openers_run_the_os_command(impl, argv0) -> None:
    with patch("subprocess.run") as run:
        impl().open("/tmp/notes.md")
    run.assert_called_once_with([argv0, "/tmp/notes.md"], check=True)


def test_the_windows_opener_uses_the_shell_open_verb(monkeypatch) -> None:
    """`os.startfile` exists only on Windows, so it is replaced, not merely patched."""
    calls: list[str] = []
    monkeypatch.setattr(os, "startfile", calls.append, raising=False)
    WindowsFileOpener().open(r"C:\Users\ada\notes.md")
    assert calls == [r"C:\Users\ada\notes.md"]


def test_launch_file_on_windows_reaches_startfile_with_a_string(monkeypatch) -> None:
    """The launcher's Windows path had no test before it moved behind the seam."""
    calls: list[str] = []
    monkeypatch.setattr(os, "startfile", calls.append, raising=False)
    with patch.object(sys, "platform", "win32"), patch("subprocess.run") as run:
        launch_file(Path("notes.md"))
    assert calls == [str(Path("notes.md"))]
    run.assert_not_called()


def test_the_launcher_no_longer_reads_sys_platform() -> None:
    """Looks for the attribute, not the text, so the docstring may still name it."""
    tree = ast.parse(LAUNCHER.read_text(encoding="utf-8"))
    reads = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr == "platform"
        and isinstance(node.value, ast.Name)
        and node.value.id == "sys"
    ]
    assert reads == [], f"fileopen/launcher.py reads sys.platform at line(s) {reads}"
