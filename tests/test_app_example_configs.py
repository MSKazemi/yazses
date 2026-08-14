"""The per-app example configs must be loadable, not just parseable (#43).

`examples/config.toml` is generated and guarded by `test_example_config.py`.
The per-app profiles next to it — `config.vscode.toml`, `config.kitty.toml`,
and the rest — are hand-written by contributors, one per PR, and until this
file nothing checked them at all.

That matters more than it sounds. These are copied verbatim by newcomers, and
the loader is deliberately total (#52): an unknown key or a mistyped value is
dropped and recorded as a `ConfigProblem`, never raised. So a profile naming a
setting that does not exist — or putting a real setting under the wrong
section — installs cleanly, starts cleanly, and silently does nothing.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from yazses.config import load_config_checked

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"

# config.toml is the generated one; test_example_config.py owns it.
APP_CONFIGS = sorted(p for p in EXAMPLES.glob("config.*.toml") if p.name != "config.toml")


def test_there_are_app_configs_to_check():
    """Guards the glob: an empty parametrize list passes silently."""
    assert APP_CONFIGS, f"no examples/config.<app>.toml found under {EXAMPLES}"


@pytest.mark.parametrize("path", APP_CONFIGS, ids=lambda p: p.name)
def test_it_is_valid_toml(path: Path):
    tomllib.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", APP_CONFIGS, ids=lambda p: p.name)
def test_it_loads_with_no_config_problems(path: Path):
    """Every key must reach a real field on a real section.

    `load_config` never raises, so this is the only place a typo in a
    contributed profile can be caught.
    """
    problems = load_config_checked(path).problems
    assert not problems, "\n".join(
        [f"{path.name} would not load cleanly:"] + [f"  - {p}" for p in problems]
    )


@pytest.mark.parametrize("path", APP_CONFIGS, ids=lambda p: p.name)
def test_it_explains_itself(path: Path):
    """An app profile with no prose is a config dump.

    The point of these files is *why* a setting suits that app, not the
    settings themselves — a newcomer can already get those from
    `examples/config.toml`.
    """
    text = path.read_text(encoding="utf-8")
    assert text.startswith("#"), f"{path.name} does not open with a comment header"
    assert text.endswith("\n"), f"{path.name} has no trailing newline"


def test_the_problem_check_can_actually_fail(tmp_path: Path):
    """Red-green guard for the assertion above.

    `load_config_checked` reporting nothing is exactly what a passing profile
    looks like, so a version of this suite that could never fail would be
    indistinguishable from one that works.
    """
    bogus = tmp_path / "config.bogus.toml"
    bogus.write_text('[stt]\nnot_a_real_key = "x"\n', encoding="utf-8")
    assert load_config_checked(bogus).problems, (
        "an unknown key produced no ConfigProblem — the profile check above is inert"
    )
