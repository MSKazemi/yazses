"""The path the config is *loaded* from and the path it is *seeded* at are one function.

`system/firstrun.py` used to restate `Path.home() / ".config" / "yazses" / "config.toml"`
with a docstring saying it "mirrors ``config.load_config``'s default". A comment is not a
mechanism: seeding a file the loader does not read is a first run that appears to have
done nothing, and the two would drift the first time either moved — which is not
hypothetical, since `load_config`'s default is the Linux path on every platform while the
rest of the product resolves its config directory through `platformdirs`.

The second reason it is a named seam is the whole test suite: `load_config(None)` appears
at 28 call sites meaning *the defaults*, and meant *the developer's own machine* until
`tests/conftest.py::_no_test_may_read_the_users_real_config` had one function to point
somewhere empty.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from yazses import config
from yazses.system import firstrun

_SEED_SRC = Path(__file__).resolve().parents[1] / "src" / "yazses" / "system" / "firstrun.py"


def test_the_seeded_path_and_the_loaded_path_are_the_same():
    assert firstrun.default_config_path() == config.default_config_path()


def test_the_conftest_fixture_really_redirects_the_default(tmp_path):
    """If this ever stops holding, every `load_config(None)` reads the real machine."""
    assert not config.default_config_path().exists()
    assert config.load_config(None) == config.Config()


def test_the_seeder_does_not_restate_the_path():
    """Delegation, not a second copy — checked structurally so a rewrite cannot re-copy it."""
    tree = ast.parse(_SEED_SRC.read_text(encoding="utf-8"), filename=str(_SEED_SRC))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == "config.toml":
            raise AssertionError(
                f"{_SEED_SRC.name}:{node.lineno} names 'config.toml' itself; call "
                "yazses.config.default_config_path() instead of restating the path"
            )


def test_the_loader_uses_the_seam_rather_than_an_inline_expression():
    src = inspect.getsource(config.load_config_checked)
    assert "default_config_path()" in src, (
        "load_config_checked no longer resolves its default through the seam, so the "
        "suite's config-hermeticity fixture and the first-run seeder both stop applying"
    )
