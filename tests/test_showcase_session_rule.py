"""The SHOWCASE linter must not demand a Linux display server from Windows or macOS.

`check-compatibility.py` requires every setup report to name X11 or Wayland, because on
Linux a report that omits the session cannot be acted on. That rule was applied to every
entry unconditionally -- and X11 and Wayland are Linux/BSD display servers that Windows
and macOS do not have.

So the first Windows entry and the first macOS entry this project ever received were both
rejected as malformed, on a project whose scarcest evidence is Windows and macOS testing.
The linter was refusing exactly the reports it most needed.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def cc():
    spec = importlib.util.spec_from_file_location(
        "check_compatibility", ROOT / "scripts" / "check-compatibility.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _body(os_line: str) -> str:
    return (
        f"- **OS / desktop:** {os_line}\n"
        "- **Mic:** built-in\n"
        "- **Apps you dictate into:** terminal\n"
        "- **How you use YazSes:** dictating notes.\n"
    )


def _session_problems(cc, os_line: str) -> list[str]:
    return [p for p in cc.check_entry("@someone", _body(os_line)) if "X11 or Wayland" in p]


@pytest.mark.parametrize(
    "os_line",
    [
        "Windows 11 Home",
        "Windows 10",
        "macOS (Apple silicon)",
        "macOS 26.5.1 (Build 25F80)",
        "Mac OS X",
        "OSX",
    ],
)
def test_windows_and_macos_are_not_asked_for_a_display_server(cc, os_line):
    """These platforms have no X11 or Wayland, so the question does not apply."""
    assert _session_problems(cc, os_line) == [], os_line


@pytest.mark.parametrize(
    "os_line",
    ["Ubuntu 24.04 (GNOME)", "Fedora + KDE", "Arch Linux", "FreeBSD 14"],
)
def test_linux_and_bsd_must_still_name_the_session(cc, os_line):
    """The rule is narrowed, not removed -- on Linux it is still load-bearing."""
    assert _session_problems(cc, os_line), os_line


@pytest.mark.parametrize("os_line", ["Ubuntu 24.04 (GNOME, X11)", "Fedora + KDE Wayland"])
def test_a_linux_entry_that_names_its_session_passes(cc, os_line):
    assert _session_problems(cc, os_line) == [], os_line


def test_the_shipped_showcase_passes_its_own_linter(cc):
    """The file in the repo must satisfy the rule the script enforces."""
    text = (ROOT / "SHOWCASE.md").read_text(encoding="utf-8")
    found = [p for h, b in cc.entries(text) for p in cc.check_entry(h, b)]
    assert found == [], found
