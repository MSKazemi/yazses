"""The two architecture pages must not contradict the code on facts the code decides.

Each assertion below pins a statement that was wrong in `docs/architecture.md` or
`design/architecture.md` and is derived from (or checked against) the source, so the
page cannot drift back without a red test:

* No Windows service exists: Windows lifecycle is a detached process plus an
  ``HKCU\\Run`` autostart entry (``platform/windows/lifecycle.py``), so neither page may
  name the Service Control Manager.
* Windows does have a ``PermissionsBackend`` (``platform/windows/permissions.py``
  probes the microphone privacy switch), so the platform table may not say ``(n/a)``.
* Every ``Protocol`` in ``platform/base.py`` is named in the public page, derived with
  ``ast`` so a new Protocol is caught too.
* The daemon *does* enter ERROR (``core/daemon.py::_await_shutdown_in_error``), so the
  public page may not say ERROR "is not a daemon state at all".
* The STT factory refuses an unsupported language instead of falling back
  (``stt/factory.py`` module docstring, #515), so the page may not promise that
  dictation "always comes up".
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "architecture.md"
DESIGN = ROOT / "design" / "architecture.md"
SRC = ROOT / "src" / "yazses"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _protocols() -> list[str]:
    tree = ast.parse(_read(SRC / "platform" / "base.py"))
    names = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and any(
            (isinstance(b, ast.Name) and b.id == "Protocol") for b in node.bases
        ):
            names.append(node.name)
    return names


def test_the_code_has_no_windows_service() -> None:
    """The premise the next test relies on: if this ever fails, a service was added and
    the pages may name it again."""
    windows = SRC / "platform" / "windows"
    text = "\n".join(_read(p) for p in sorted(windows.rglob("*.py")))
    assert "HKCU" in _read(windows / "lifecycle.py")
    assert not re.search(r"win32service|CreateServiceW|OpenSCManager", text)


def test_no_page_names_a_windows_service_controller() -> None:
    for page in (DOCS, DESIGN):
        text = _read(page)
        for phrase in ("Service Control Manager", "service controller", "/ SCM)"):
            assert phrase not in text, f"{page.relative_to(ROOT)} still says {phrase!r}"


def test_windows_permissions_backend_is_not_documented_as_absent() -> None:
    assert (SRC / "platform" / "windows" / "permissions.py").is_file()
    row = next(
        ln for ln in _read(DOCS).splitlines() if ln.startswith("| `PermissionsBackend`")
    )
    assert "(n/a)" not in row, row


def test_every_platform_protocol_is_named_in_the_public_page() -> None:
    protocols = _protocols()
    assert len(protocols) >= 7, f"the ast probe found only {protocols}"
    text = _read(DOCS)
    missing = [name for name in protocols if f"`{name}`" not in text]
    assert not missing, f"docs/architecture.md does not name {missing}"


def test_the_public_page_admits_the_daemon_enters_error() -> None:
    daemon = _read(SRC / "core" / "daemon.py")
    assert "self._state.state = TrayState.ERROR" in daemon
    assert "ERROR** is not a daemon state" not in _read(DOCS)


def test_the_public_page_does_not_promise_dictation_always_comes_up() -> None:
    factory = _read(SRC / "stt" / "factory.py")
    assert "LanguageUnsupportedError" in factory
    text = _read(DOCS)
    assert "dictation always comes up" not in text
    assert "LanguageUnsupportedError" in text
