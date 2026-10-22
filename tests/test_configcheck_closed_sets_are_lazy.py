"""`configcheck._ENUMS` holds the same sets as before, without importing a feature at start.

`[facegesture] gesture` is validated against `facegesture.detector.GESTURES`, read from
the definition rather than restated. That used to happen at import: `configcheck`
imported `yazses.facegesture` at module scope, and since `yazses.config` imports
`configcheck`, every daemon start and most CLI commands paid for a feature that is off by
default. The set is now a function the table calls on the first lookup of that key
(`configcheck._ClosedSets`). This file proves both halves of that trade: nothing is
imported until the value is read, and every way of reading the table sees exactly the
tuples an eager dict would have held.
"""
from __future__ import annotations

import json
import subprocess
import sys

from yazses import configcheck
from yazses.config import FacegestureConfig
from yazses.configcheck import _ENUMS, ConfigProblem, _ClosedSets, build_section, enum_values
from yazses.facegesture.detector import GESTURES, gesture_names


def _fresh(code: str) -> dict:
    """Run *code* in a new interpreter; it must print one JSON object last."""
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8",
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_importing_configcheck_does_not_import_the_feature() -> None:
    got = _fresh(
        "import json, sys\n"
        "from yazses.configcheck import _ENUMS\n"
        "before = 'yazses.facegesture' in sys.modules\n"
        "# Reading the keys -- membership, length, iteration -- must not resolve a value.\n"
        "keys = ('facegesture.gesture' in _ENUMS, len(_ENUMS) > 0, list(_ENUMS))\n"
        "after_keys = 'yazses.facegesture' in sys.modules\n"
        "from yazses.configcheck import enum_values\n"
        "value = enum_values('facegesture', 'gesture')\n"
        "print(json.dumps({'before': before, 'after_keys': after_keys,\n"
        "                  'after_value': 'yazses.facegesture' in sys.modules,\n"
        "                  'value': list(value)}))\n"
    )
    assert got["before"] is False, "importing configcheck imported yazses.facegesture"
    assert got["after_keys"] is False, "reading _ENUMS's keys resolved a deferred set"
    assert got["after_value"] is True, "reading the value never imported its definition"
    assert got["value"] == list(gesture_names())


def test_loading_a_config_that_does_not_set_the_gesture_imports_nothing(tmp_path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text('[facegesture]\nmode = "command"\n[injection]\nbackend = "auto"\n',
                   encoding="utf-8")
    got = _fresh(
        "import json, sys\n"
        "from pathlib import Path\n"
        "from yazses.config import load_config\n"
        f"load_config(Path({str(cfg)!r}))\n"
        "print(json.dumps({'loaded': 'yazses.facegesture' in sys.modules}))\n"
    )
    assert got["loaded"] is False


def test_the_deferred_set_is_the_definition() -> None:
    assert _ENUMS["facegesture.gesture"] == gesture_names()
    assert set(_ENUMS["facegesture.gesture"]) == set(GESTURES)
    assert enum_values("facegesture", "gesture") == gesture_names()
    assert _ENUMS.get("facegesture.gesture") == gesture_names()


def test_every_way_of_reading_the_table_agrees() -> None:
    """The consumers use `[]`, `get`, `in`, `sorted()`, `set()` and `.items()`."""
    eager = {key: _ENUMS[key] for key in _ENUMS}
    assert dict(_ENUMS.items()) == eager
    assert list(_ENUMS.values()) == list(eager.values())
    assert sorted(_ENUMS) == sorted(eager)
    assert dict(_ENUMS) == eager
    assert all(isinstance(v, tuple) and all(isinstance(s, str) for s in v)
               for v in _ENUMS.values())
    assert "no.such_key" not in _ENUMS and _ENUMS.get("no.such_key") is None


def test_a_misspelt_gesture_is_still_refused() -> None:
    """The enforcement itself, unchanged by the deferral."""
    problems: list[ConfigProblem] = []
    section = build_section(FacegestureConfig, {"gesture": "brow_rasie"}, "facegesture",
                            problems)
    assert section.gesture == FacegestureConfig().gesture
    assert any(p.key == "gesture" and "is not one of" in p.detail for p in problems)

    problems = []
    valid = gesture_names()[0]
    assert build_section(FacegestureConfig, {"gesture": valid}, "facegesture",
                         problems).gesture == valid
    assert not problems


def test_a_deferred_set_is_resolved_once_and_kept() -> None:
    calls: list[int] = []

    def late() -> tuple[str, ...]:
        calls.append(1)
        return ("a", "b")

    table = _ClosedSets({"x.y": ("one",), "x.late": late})
    assert table.is_deferred("x.late") and not table.is_deferred("x.y")
    assert "x.late" in table and len(table) == 2 and list(table) == ["x.y", "x.late"]
    assert calls == [], "membership, length and iteration must not resolve a value"
    assert table["x.late"] == ("a", "b")
    assert table["x.late"] == ("a", "b")
    assert calls == [1]
    assert not table.is_deferred("x.late")


def test_the_module_no_longer_imports_the_feature_at_module_scope() -> None:
    """The source-level half, so the reason survives a refactor of the table."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(configcheck))
    top_level = [
        node.module for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module
    ]
    assert not [m for m in top_level if m.startswith("yazses.facegesture")], top_level
