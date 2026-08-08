"""The man page must stay in lockstep with the CLI.

If this fails, run `uv run python scripts/gen-man.py` and commit the result.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
import typer

from yazses.cli import app

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
    # Compare the body, not the `.TH` stamp — see gen_man.body() for why a
    # version bump must not be able to redden CI.
    generated = gen.body(gen.gen_man())
    on_disk = gen.body(MAN.read_text(encoding="utf-8"))
    assert generated == on_disk, (
        "man/yazses.1 is stale — run `uv run python scripts/gen-man.py` and commit."
    )


def test_man_page_header_is_well_formed():
    """The `.TH` line is excluded from the sync check, so assert its shape here."""
    if not MAN.exists():
        pytest.skip("man/yazses.1 not present on this checkout (private-only doc)")
    first = MAN.read_text(encoding="utf-8").splitlines()[0]
    assert re.fullmatch(
        r'\.TH YAZSES 1 "(\d{4}-\d{2}-\d{2}|unreleased)" '
        r'"yazses [^"]+" "User Commands"',
        first,
    ), f"malformed .TH header: {first!r}"


def test_man_page_lists_every_top_level_command(gen):
    click_app = typer.main.get_command(app)
    text = gen.gen_man()
    for name in click_app.commands:
        assert f'.SS "yazses {name}"' in text, f"yazses {name} missing from man/yazses.1"


def test_man_page_is_pure_ascii(gen):
    """Raw UTF-8 only renders under preconv; `groff -mandoc` alone garbles it.

    gen_man escapes typography to groff entities (`\\(em`, `\\(->`, …) so the
    page is portable to strict toolchains. Guard that it stays that way.
    """
    offenders = sorted({ch for ch in gen.gen_man() if ord(ch) > 127})
    assert not offenders, (
        f"non-ASCII in the man page: {offenders} — add them to _GROFF_CHARS "
        "in scripts/gen-man.py"
    )
