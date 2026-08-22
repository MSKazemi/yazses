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


def test_the_release_date_survives_an_em_dash_heading(gen, tmp_path, monkeypatch):
    """`_release_date` silently stopped finding dates when the heading style changed.

    It matched `## [X.Y.Z] - YYYY-MM-DD` with an ASCII hyphen. Every release from
    2.25.0 writes `## [X.Y.Z] — YYYY-MM-DD` with an em dash, so the lookup failed
    and the stamp fell back to "unreleased" — which the header test permits, so
    nothing noticed. 2.24.0, the last heading with a hyphen, is the last one that
    resolved.

    The function exists to give the page a stable, real date instead of
    `datetime.today()`. Falling back for a formatting reason defeats that quietly.
    """
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n"
        "## [9.9.9] — 2026-01-02\n\n"
        "## [9.9.8] - 2026-01-01\n\n"
        "## [9.9.7] – 2025-12-31\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(gen, "CHANGELOG", changelog)

    assert gen._release_date("9.9.9") == "2026-01-02", "em dash (the current style)"
    assert gen._release_date("9.9.8") == "2026-01-01", "ascii hyphen (the old style)"
    assert gen._release_date("9.9.7") == "2025-12-31", "en dash, for good measure"
    assert gen._release_date("0.0.0") == "unreleased", "genuinely absent stays absent"


def test_the_real_changelog_resolves_the_current_version(gen):
    """The regression this guards is only visible against the real file."""
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    ver = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert gen._release_date(ver) != "unreleased", (
        f"no date found for {ver} in CHANGELOG.md — the heading style and the "
        "generator's pattern have drifted apart again"
    )
