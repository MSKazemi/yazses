"""The example config must not drift from the defaults it claims (#20).

The previous hand-written example said `key = "space"` and `model = "tiny.en"`
long after the defaults had moved to `right_ctrl` and `base.en`, so the file a
newcomer was told to copy taught them settings the program no longer used. It is
generated now, and this is what keeps it that way.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tomllib
from dataclasses import fields
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "config.toml"


def _generator():
    spec = importlib.util.spec_from_file_location(
        "gen_example_config", ROOT / "scripts/gen-example-config.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["gen_example_config"] = module
    spec.loader.exec_module(module)
    return module


def test_the_committed_example_matches_the_defaults():
    assert EXAMPLE.read_text(encoding="utf-8") == _generator().render(), (
        "examples/config.toml is stale — run "
        "`uv run python scripts/gen-example-config.py`"
    )


def test_the_check_flag_agrees():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/gen-example-config.py"), "--check"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_it_is_valid_toml_and_loads_as_a_config():
    """A broken example is worse than none — people paste this verbatim."""
    from yazses.config import load_config

    data = tomllib.loads(EXAMPLE.read_text(encoding="utf-8"))
    assert "stt" in data and "hotkey" in data

    cfg = load_config(EXAMPLE)
    assert cfg.stt.model == data["stt"]["model"]
    assert cfg.hotkey.key == data["hotkey"]["key"]


def test_every_documented_key_exists_on_its_dataclass():
    """The bug this caught: a key declared on the WRONG dataclass.

    `vocab_correction` was added to `TtsConfig` instead of `SttConfig`, so
    `[stt] vocab_correction = true` was dropped by the loader and the feature
    could never turn on — silently, because the daemon reads it with a defaulted
    `getattr`. Nothing else in the suite would have noticed.
    """
    module = _generator()
    for section, cls, _purpose, comments in module.SECTIONS:
        names = {f.name for f in fields(cls)}
        missing = sorted(set(comments) - names)
        assert not missing, f"[{section}] documents keys its dataclass lacks: {missing}"


@pytest.mark.parametrize("section", ["stt", "hotkey", "audio", "injection",
                                     "accessibility", "commands"])
def test_the_sections_the_issue_asked_for_are_present(section):
    assert f"[{section}]" in EXAMPLE.read_text(encoding="utf-8")


def test_every_line_carries_an_explanation():
    """"Annotated" is the whole point; an uncommented key is a key you must
    look up somewhere else."""
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            assert "#" in line, f"no explanation on: {line!r}"
