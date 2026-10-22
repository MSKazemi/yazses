"""The config editor must refuse a deeply nested file the way it refuses any unparseable one.

Both write paths in `yazses.system.configedit` parse the complete candidate before it
replaces the target: `set_config_keys_atomic` (every `yazses ... set` command and the
settings panel) and `set_config_table_array` (`[[facegesture.switches]]`). They called
`tomllib.loads` directly, and `tomllib` is a recursive-descent parser with no depth
limit, so a value nested past the recursion limit raised `RecursionError` -- a
`RuntimeError`, not the `TOMLDecodeError` (or, for the table-array path, the
`ValueError`) their callers handle. `yazses.tomlio` already translates that one failure
for the loaders (see `test_deeply_nested_toml_does_not_crash_the_loader.py`); these
tests hold the editor to the same contract.

The original file must also be left byte-for-byte untouched and no temporary candidate
may be left behind: the refusal happens before the replace, which is the whole point of
parsing the candidate first.
"""

from __future__ import annotations

import pathlib
import tomllib

import pytest

from yazses.system.configedit import (
    ConfigChange,
    set_config_keys_atomic,
    set_config_table_array,
)

#: Far past the default recursion limit (1000), as in the loader test.
DEPTH = 5000

NESTED = {
    "array": "x = " + "[" * DEPTH + "]" * DEPTH + "\n",
    "inline-table": "x = " + "{a = " * DEPTH + "1" + "}" * DEPTH + "\n",
}


def _write(tmp_path: pathlib.Path, shape: str) -> tuple[pathlib.Path, bytes]:
    path = tmp_path / "config.toml"
    path.write_text("[stt]\nmodel = 'small.en'\n\n[deep]\n" + NESTED[shape], encoding="utf-8")
    return path, path.read_bytes()


def _leftover_candidates(tmp_path: pathlib.Path) -> list[str]:
    return [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


@pytest.mark.parametrize("shape", sorted(NESTED))
def test_atomic_edit_reports_deep_nesting_as_a_decode_error(
    shape: str, tmp_path: pathlib.Path
) -> None:
    path, original = _write(tmp_path, shape)

    with pytest.raises(tomllib.TOMLDecodeError, match="nested too deeply"):
        set_config_keys_atomic(path, [ConfigChange("stt", "model", "base.en")])

    assert path.read_bytes() == original
    assert _leftover_candidates(tmp_path) == []


@pytest.mark.parametrize("shape", sorted(NESTED))
def test_table_array_edit_refuses_deep_nesting_with_value_error(
    shape: str, tmp_path: pathlib.Path
) -> None:
    path, original = _write(tmp_path, shape)

    with pytest.raises(ValueError, match="could not be written"):
        set_config_table_array(
            path, "facegesture.switches", [(("gesture", "smile"), ("intent", "hold_to_command"))]
        )

    assert path.read_bytes() == original
    assert _leftover_candidates(tmp_path) == []


def test_ordinary_nesting_is_still_edited(tmp_path: pathlib.Path) -> None:
    """Non-vacuity: only what `tomllib` cannot parse is refused."""
    path = tmp_path / "config.toml"
    path.write_text(
        "[stt]\nmodel = 'small.en'\n\n[deep]\nx = " + "[" * 20 + "]" * 20 + "\n",
        encoding="utf-8",
    )

    set_config_keys_atomic(path, [ConfigChange("stt", "model", "base.en")])

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert data["stt"]["model"] == "base.en"
    assert "x" in data["deep"]
