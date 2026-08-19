"""A fresh install wrote a config key that nothing reads.

`system/firstrun.py::ensure_recommended_config` seeds `config.toml` on the first daemon
start, enabling the DEFAULT_ON and RECOMMENDED tiers so a new user gets the intended
experience without configuring anything. It writes 14 keys. Thirteen are read by running
code. One was not:

    [chords]
    enabled = true

`yazses chords "press control shift P"` is a CLI command that renders `ctrl+shift+p` and
never consults that key; no daemon code reads it, and there is no spoken grammar behind the
catalog's promise that *"Say any shortcut and it's pressed"*. So every new install carried a
setting that did nothing, while `yazses features` listed the capability as ON — and the
entry's own text said *"Off by default"*, which the RECOMMENDED tier contradicted.

`chords` is now OPTIONAL. That makes both sentences true at once and changes no
functionality: the CLI works whether or not the key is present.

## The guard is the point

One wrong tier is a one-word fix. What made it reach every user is that nothing connected
the seed to the question "is this key read anywhere?", and the tier of a new capability is
easy to set optimistically. This computes the answer from the code on every run.

## Scope, stated because it is narrow

This checks the keys **first-run writes**, not every toggle in the registry. The wider
question — 23 further features whose `enabled` key nothing reads — is a design decision
about wiring versus re-describing, and is not settled here. The distinction that justifies
acting on this one alone: those are toggles a user may choose to flip, while this one was
flipped *for* them, by default, on every fresh install.
"""

from __future__ import annotations

import ast
import dataclasses
import tomllib
from pathlib import Path

import pytest

from yazses.config import Config, load_config_checked
from yazses.system.firstrun import ensure_recommended_config

SRC = Path(__file__).resolve().parent.parent / "src" / "yazses"
#: Files that define or rewrite config rather than consume it — a mention here is not a read.
_NOT_READERS = {"config.py", "features.py", "configcheck.py", "firstrun.py"}


def _chain(node) -> list[str]:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return list(reversed(parts))


def _keys_read_from_config() -> dict[str, set[str]]:
    """`{section: {key, ...}}` actually read by running code.

    Handles the three shapes the codebase uses: a direct `cfg.section.key` chain, a local
    alias (`mc = config.macros` then `mc.enabled`), and `getattr(cfg.section, "key", …)`.
    A whole section passed to a function records `"*"`, since the callee may read anything.
    """
    sections = {f.name for f in dataclasses.fields(Config())}
    reads: dict[str, set[str]] = {}

    def record(section: str, key: str) -> None:
        reads.setdefault(section, set()).add(key)

    for path in SRC.rglob("*.py"):
        if path.name in _NOT_READERS or "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        alias: dict[str, str] = {}
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Attribute)
            ):
                chain = _chain(node.value)
                if chain and chain[-1] in sections:
                    alias[node.targets[0].id] = chain[-1]
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                chain = _chain(node)
                if len(chain) >= 2:
                    section, key = chain[-2], chain[-1]
                    if section in sections:
                        record(section, key)
                    elif section in alias:
                        record(alias[section], key)
            elif isinstance(node, ast.Call):
                if (
                    isinstance(node.func, ast.Name)
                    and node.func.id == "getattr"
                    and len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)
                    and isinstance(node.args[1].value, str)
                ):
                    chain = _chain(node.args[0])
                    if chain:
                        section = alias.get(
                            chain[-1], chain[-1] if chain[-1] in sections else ""
                        )
                        if section:
                            record(section, node.args[1].value)
                for arg in node.args:
                    if isinstance(arg, ast.Attribute):
                        chain = _chain(arg)
                        if chain and chain[-1] in sections:
                            record(chain[-1], "*")
    return reads


@pytest.fixture
def seeded(tmp_path) -> dict:
    path = tmp_path / "config.toml"
    ensure_recommended_config(path)
    assert path.exists(), "first run wrote no config at all"
    return tomllib.loads(path.read_text(encoding="utf-8"))


def test_the_reader_scan_finds_something() -> None:
    """Guard the guard: an empty scan would make every key look dead."""
    reads = _keys_read_from_config()
    assert len(reads) > 20, "the config-reader scan is broken, not the codebase"
    assert "enabled" in reads.get("timeline", set())


def test_first_run_seeds_something(seeded: dict) -> None:
    """And the other way: an empty seed would make every assertion below vacuous."""
    assert sum(len(v) for v in seeded.values()) >= 10


def test_every_seeded_key_is_read_by_running_code(seeded: dict) -> None:
    """The defect: `[chords] enabled` was written for every new user and read by nobody."""
    reads = _keys_read_from_config()
    dead = [
        f"[{section}] {key}"
        for section, keys in seeded.items()
        for key in keys
        if key not in reads.get(section, set()) and "*" not in reads.get(section, set())
    ]
    assert not dead, (
        f"a fresh install seeds {dead}, which no running code reads. Either wire the "
        f"capability, or move it out of the DEFAULT_ON/RECOMMENDED tiers — a setting "
        f"enabled for everyone that does nothing is worse than one nobody turned on, "
        f"because `yazses features` then lists the capability as ON."
    )


def test_the_seeded_config_loads_without_problems(tmp_path) -> None:
    """It is written by us, so a `ConfigProblem` here is self-inflicted."""
    path = tmp_path / "config.toml"
    ensure_recommended_config(path)
    assert not load_config_checked(path).problems


def test_an_existing_config_is_never_overwritten(tmp_path) -> None:
    """The other promise first-run makes."""
    path = tmp_path / "config.toml"
    path.write_text('[stt]\nmodel = "large-v3"\n', encoding="utf-8")
    ensure_recommended_config(path)
    assert 'model = "large-v3"' in path.read_text(encoding="utf-8")


def test_chords_is_not_in_a_seeded_tier() -> None:
    """Pinned directly, so restoring the tier fails here with the reason attached."""
    from yazses.system.features import _DEFAULT_ENABLED_TIERS, feature_status

    chords = next(f for f in feature_status(Config()) if f.slug == "chords")
    assert chords.tier not in _DEFAULT_ENABLED_TIERS, (
        "chords is seeded again — nothing reads `[chords] enabled`, and its own "
        "description says 'Off by default'"
    )
