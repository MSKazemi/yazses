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
_LOADER_SRC = Path(__file__).resolve().parents[1] / "src" / "yazses" / "config.py"


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


def _default_config_path_body() -> list[ast.stmt]:
    """The executable body of ``config.default_config_path``, docstring dropped.

    Read from the source file rather than the imported symbol: an autouse fixture
    in ``conftest.py`` replaces ``yazses.config.default_config_path`` for every
    test, so the module attribute is a lambda here and tells us nothing.
    """
    tree = ast.parse(_LOADER_SRC.read_text(encoding="utf-8"), filename=str(_LOADER_SRC))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "default_config_path":
            body = list(node.body)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                body = body[1:]  # the docstring tells the story; assert on the code
            return body
    raise AssertionError(f"{(_LOADER_SRC.name)} no longer defines default_config_path")


def test_default_config_path_resolves_through_the_platform_layer() -> None:
    """#330: the seam delegates to the platform paths; it does not restate a path.

    ``Path.home() / ".config"`` **is** the config dir on Linux by coincidence, and
    a directory nothing writes on Windows (``%LOCALAPPDATA%\\yazses``) or macOS
    (``~/Library/Application Support``). The daemon loads ``load_config()`` with no
    path, so on those two platforms it read dataclass defaults forever while the
    CLI read and wrote the platform file: ``hotkey set left_ctrl`` updated the
    file, ``status`` kept reporting the compiled-in ``right_ctrl``, and no restart
    could help because no restart had ever looked at that file.

    A behavioural test on this CI (Linux) cannot tell the two implementations
    apart — the old path and ``get_paths().config_file`` are the same string here.
    So the guard is structural: the body resolves through ``get_paths()`` and
    contains no path literal at all. The string constants are exactly what the
    pre-#330 body was made of.
    """
    body = _default_config_path_body()
    code = "\n".join(ast.unparse(node) for node in body)
    assert "get_paths()" in code, (
        "default_config_path no longer delegates to platform.factory.get_paths; "
        "restating a path here re-splits the daemon's config file from the CLI's (#330)"
    )
    literals = {
        node.value
        for node in ast.walk(ast.Module(body=body, type_ignores=[]))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
    }
    assert not literals, (
        f"default_config_path builds its answer from path literals {sorted(literals)} "
        "again — the Linux-shaped coincidence that stranded Windows and macOS daemons "
        "on defaults forever (#330); resolve it through get_paths() instead"
    )
