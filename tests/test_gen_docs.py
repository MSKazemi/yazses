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
    generated = getattr(gen, fn_name)()
    on_disk = (ROOT / "docs" / fname).read_text(encoding="utf-8")
    assert generated == on_disk, (
        f"docs/{fname} is stale — run `uv run python scripts/gen-docs.py` and commit."
    )


def test_features_doc_lists_all_135(gen):
    text = gen.gen_features()
    from yazses.system.features import feature_status
    from yazses.config import Config
    for f in feature_status(Config()):
        assert f"### {f.name}" in text, f"{f.name} missing from features.md"


def test_config_doc_covers_every_section(gen):
    import dataclasses
    from yazses.config import Config
    text = gen.gen_configuration()
    for fld in dataclasses.fields(Config()):
        assert f"## `[{fld.name}]`" in text, f"[{fld.name}] missing from configuration.md"
