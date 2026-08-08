"""The man page must stay in lockstep with the CLI.

If this fails, run `uv run python scripts/gen-man.py` and commit the result.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GEN = ROOT / "scripts" / "gen-man.py"
MAN = ROOT / "man" / "yazses.1"


def _load_gen():
    spec = importlib.util.spec_from_file_location("gen_man", GEN)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def gen():
    return _load_gen()


def test_man_page_is_in_sync(gen):
    # man/yazses.1 is generated, same as the docs/ reference pages — see
    # test_gen_docs.py for why a missing file is a skip, not a failure, here too.
    if not MAN.exists():
        pytest.skip("man/yazses.1 not present on this checkout (private-only doc)")
    generated = gen.gen_man()
    on_disk = MAN.read_text(encoding="utf-8")
    assert generated == on_disk, (
        "man/yazses.1 is stale — run `uv run python scripts/gen-man.py` and commit."
    )


def test_man_page_lists_every_top_level_command(gen):
    from yazses.cli import app
    import typer

    click_app = typer.main.get_command(app)
    text = gen.gen_man()
    for name in click_app.commands:
        assert f'.SS "yazses {name}"' in text, f"yazses {name} missing from man/yazses.1"
