"""A typo in `macros.toml` stopped the daemon starting.

`Daemon.__init__` calls `build_macro_table`, and `load_macros`'s own docstring is explicit:
*"A single bad entry is skipped (logged), never raised — a broken macro must not break the
daemon."* It handled an unparseable file and an entry missing its fields. Two shapes got
through:

    macro = "a string"          ->  AttributeError: 'str' object has no attribute 'get'
    [[macro]]
    trigger = 42                ->  AttributeError: 'int' object has no attribute 'strip'

Both raise out of the constructor, so the daemon does not start.

`macros.toml` is a **separate file**. `configcheck` — which exists so that no config can
stop the daemon starting — never sees it, so nothing else could catch this.

## Why this is an oversight rather than a decision

`build_style_rules` is called from the same constructor, for the same kind of user-authored
side file, and already has all three guards: it rejects a non-list `rule`, skips a non-table
entry, and wraps the whole load in `except Exception` with the comment *"a style sheet must
never block startup"*. The macros loader intended the same thing — its docstring says so —
and simply did not check these two.

The fix follows the sibling: reject a non-list `macro`, skip a non-table entry, skip an
entry whose trigger or type is not a string. The type check lives here rather than inside
`normalize`, so that stays a pure text function with one job.
"""

from __future__ import annotations

import pytest

from yazses.commands.macros import build_macro_table, load_macros
from yazses.config import Config

VALID = '[[macro]]\ntrigger = "sig"\ntype = "text"\ntext = "Best,"\n'


def _table(tmp_path, body: str):
    (tmp_path / "macros.toml").write_text(body, encoding="utf-8")
    cfg = Config()
    cfg.macros.enabled = True
    return build_macro_table(cfg, tmp_path)


@pytest.mark.parametrize(
    "body,why",
    [
        ('macro = "a string"', "`macro` is a string, not an array of tables"),
        ('[macro]\ntrigger = "x"\n', "`[macro]` is a table, not `[[macro]]`"),
        ("macro = [1, 2]", "the entries are not tables"),
        ('[[macro]]\ntrigger = 42\ntype = "text"\ntext = "hi"\n', "trigger is not a string"),
        ('[[macro]]\ntrigger = "x"\ntype = 7\ntext = "hi"\n', "type is not a string"),
        ("this is not toml [[[", "unparseable"),
    ],
)
def test_a_broken_macros_file_yields_an_empty_table(tmp_path, body: str, why: str) -> None:
    """Never raises: `Daemon.__init__` calls this, and a typo must not stop startup."""
    table = _table(tmp_path, body)
    assert table is not None
    assert len(table) == 0, f"{why}: expected no macros, got {len(table)}"


def test_a_valid_file_still_loads(tmp_path) -> None:
    """The expensive direction: a loader that rejected everything would pass above."""
    table = _table(tmp_path, VALID)
    assert len(table) == 1


def test_one_bad_entry_does_not_discard_the_good_ones(tmp_path) -> None:
    """The docstring's actual promise: a single bad entry is skipped, not the file."""
    table = _table(tmp_path, VALID + '\n[[macro]]\ntrigger = 42\ntype = "text"\ntext = "x"\n')
    assert len(table) == 1


def test_a_missing_file_is_an_empty_table(tmp_path) -> None:
    cfg = Config()
    cfg.macros.enabled = True
    assert len(build_macro_table(cfg, tmp_path)) == 0


def test_the_feature_stays_dormant_when_disabled(tmp_path) -> None:
    """A file that would crash must not even be read when macros are off."""
    (tmp_path / "macros.toml").write_text('macro = "a string"', encoding="utf-8")
    assert build_macro_table(Config(), tmp_path) is None


def test_load_macros_is_the_thing_the_daemon_calls() -> None:
    """If the constructor stops going through this, the guarantee moves with it."""
    import inspect

    from yazses.core.daemon import Daemon

    # The call is wrapped across lines, so match the call itself, not an argument list
    # that black may reflow.
    assert "self._macro_table = build_macro_table(" in inspect.getsource(Daemon)


def test_the_sibling_loader_still_has_the_same_guards() -> None:
    """`build_style_rules` is the reference this was brought into line with.

    It is called from the same constructor for the same kind of user-authored side file.
    If its protection is ever removed, the argument that this shape is an oversight rather
    than a decision needs revisiting.
    """
    import inspect

    from yazses.styleguard import loader

    source = inspect.getsource(loader)
    assert "must be a list of [[rule]] tables" in source
    assert "except Exception" in source


def test_normalize_is_not_asked_to_type_check() -> None:
    """The check lives in the loader so `normalize` stays a pure text function."""
    from yazses.commands.macros import normalize

    with pytest.raises(AttributeError):
        normalize(42)  # type: ignore[arg-type]


def test_load_macros_accepts_none(tmp_path) -> None:
    """Pre-existing behaviour, pinned because the new early return sits beside it."""
    assert len(load_macros(None)) == 0
