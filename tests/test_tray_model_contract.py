"""The tray's poll loop must construct a TrayModel that actually exists.

`tray/app.py::run()` builds a TrayModel from the daemon's `status` reply inside
a long-running loop that no test drives, so a keyword that TrayModel does not
accept is invisible: the suite stays green and the tray dies with a TypeError on
its first poll, in a process with no console to report it.

That shipped once — a half-applied change added `input_device=` to the call
without adding the field to the dataclass. Checking the call site statically
costs nothing and closes the gap that let it through.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

from yazses.platform.base import TrayModel

_APP = Path(__file__).resolve().parents[1] / "src" / "yazses" / "tray" / "app.py"


def _traymodel_keywords() -> set[str]:
    """Every keyword passed to a TrayModel(...) call in tray/app.py."""
    tree = ast.parse(_APP.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name != "TrayModel":
            continue
        found.update(kw.arg for kw in node.keywords if kw.arg is not None)
    return found


def test_the_tray_constructs_a_traymodel_at_all():
    """Guards the guard: if the call is renamed or removed, the check below
    would pass vacuously."""
    assert _traymodel_keywords(), "no TrayModel(...) call found in tray/app.py"


def test_every_keyword_the_tray_passes_is_a_real_field():
    fields = {f.name for f in dataclasses.fields(TrayModel)}
    unknown = _traymodel_keywords() - fields
    assert not unknown, (
        f"tray/app.py passes {sorted(unknown)} to TrayModel, which has no such "
        f"field — the tray would raise TypeError on its first poll. "
        f"Known fields: {sorted(fields)}"
    )


def test_the_keywords_actually_construct():
    """The static check proves the names exist; this proves the call works."""
    TrayModel(**{k: getattr(TrayModel(), k) for k in _traymodel_keywords()})
