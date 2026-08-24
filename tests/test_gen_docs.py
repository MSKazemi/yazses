"""The generated reference docs must stay in lockstep with the code.

If this fails, run `uv run python scripts/gen-docs.py` and commit the result.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GEN = ROOT / "scripts" / "gen-docs.py"


def _load_gen():
    spec = importlib.util.spec_from_file_location("gen_docs", GEN)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def gen():
    return _load_gen()


@pytest.mark.parametrize("fname,fn_name", [
    ("features.md", "gen_features"),
    ("configuration.md", "gen_configuration"),
    ("command-index.md", "gen_command_index"),
])
def test_generated_doc_is_in_sync(gen, fname, fn_name):
    on_disk_path = ROOT / "docs" / fname
    # This used to skip when the file was absent, because the public mirror's checkout
    # did not carry these generated docs. There is no mirror any more — the repo is a
    # single public tree and all three files are tracked — so an absent file is a real
    # failure (someone deleted a generated doc) rather than an expected checkout.
    assert on_disk_path.exists(), (
        f"docs/{fname} is missing — regenerate it with "
        "`uv run python scripts/gen-docs.py` and commit."
    )
    generated = getattr(gen, fn_name)()
    on_disk = on_disk_path.read_text(encoding="utf-8")
    assert generated == on_disk, (
        f"docs/{fname} is stale — run `uv run python scripts/gen-docs.py` and commit."
    )


def test_features_doc_lists_all_135(gen):
    text = gen.gen_features()
    from yazses.config import Config
    from yazses.system.features import feature_status
    for f in feature_status(Config()):
        assert f"### {f.name}" in text, f"{f.name} missing from features.md"


def test_config_doc_covers_every_section(gen):
    import dataclasses

    from yazses.config import Config
    text = gen.gen_configuration()
    for fld in dataclasses.fields(Config()):
        assert f"## `[{fld.name}]`" in text, f"[{fld.name}] missing from configuration.md"


def test_no_config_comment_smuggles_a_layout_into_a_table_cell() -> None:
    """A config comment is flattened into one markdown table cell.

    `_leading_comment` joins the block with single spaces, so anything whose meaning
    lives in its *layout* -- an aligned table of numbers, a bullet list, a code
    block -- arrives as an unreadable run-on. It renders, every generator test
    passes, and the public configuration reference carries a paragraph like
    "model test-clean test-other tiny.en 4.82 11.77". That happened here, to the
    `[stt] model` guidance, and nothing noticed until the generated cell was read.

    Runs of spaces are the tell: prose does not align columns. A collapsed table
    keeps its padding, because the join preserves what was inside each line.
    """
    import re

    text = (ROOT / "docs" / "configuration.md").read_text(encoding="utf-8")
    offenders = [
        line.split("|")[1].strip()
        for line in text.splitlines()
        if line.startswith("| `") and re.search(r"\S {3,}\S", line)
    ]
    assert not offenders, (
        "these config comments contain aligned columns that collapse into an "
        f"unreadable table cell: {offenders}. Write the numbers as prose -- the "
        "comment is rendered into one cell of docs/configuration.md, not as a block."
    )
