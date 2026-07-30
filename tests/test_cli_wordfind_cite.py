"""CLI exposure for the reverse-dictionary (ADR-v2-118) and citation (ADR-v2-071) cores."""
from __future__ import annotations

import json

from typer.testing import CliRunner

from yazses import cli

runner = CliRunner()

BIB = """@article{vaswani2017,
  author = {Vaswani, Ashish and Shazeer, Noam},
  year = {2017},
  title = {Attention Is All You Need}
}
"""


# ---- yazses wordfind --------------------------------------------------------

def test_wordfind_ranks_builtin_lexicon():
    r = runner.invoke(cli.app, ["wordfind", "finding something good by happy accident"])
    assert r.exit_code == 0, r.output
    assert r.output.splitlines()[0].strip().startswith("serendipity")


def test_wordfind_merges_user_lexicon(tmp_path):
    lex = tmp_path / "lex.json"
    lex.write_text(json.dumps({"widget": "a small gadget or control on a screen"}), encoding="utf-8")
    r = runner.invoke(cli.app, ["wordfind", "a small gadget on a screen", "--lexicon", str(lex)])
    assert r.exit_code == 0, r.output
    assert "widget" in r.output


def test_wordfind_no_match_exits_nonzero():
    r = runner.invoke(cli.app, ["wordfind", "zzz"])
    assert r.exit_code == 1


# ---- yazses cite ------------------------------------------------------------

def test_cite_resolves_latex(tmp_path):
    bib = tmp_path / "refs.bib"
    bib.write_text(BIB, encoding="utf-8")
    r = runner.invoke(cli.app, ["cite", "vaswani 2017", "--bib", str(bib)])
    assert r.exit_code == 0, r.output
    assert r.output.strip() == "\\cite{vaswani2017}"


def test_cite_apa_style(tmp_path):
    bib = tmp_path / "refs.bib"
    bib.write_text(BIB, encoding="utf-8")
    r = runner.invoke(cli.app, ["cite", "vaswani 2017", "--bib", str(bib), "--style", "apa"])
    assert r.exit_code == 0, r.output
    assert r.output.strip() == "Vaswani et al. (2017)"


def test_cite_no_match_exits_nonzero(tmp_path):
    bib = tmp_path / "refs.bib"
    bib.write_text(BIB, encoding="utf-8")
    r = runner.invoke(cli.app, ["cite", "einstein 1905", "--bib", str(bib)])
    assert r.exit_code == 1


def test_cite_missing_file_exits_nonzero(tmp_path):
    r = runner.invoke(cli.app, ["cite", "x 2020", "--bib", str(tmp_path / "nope.bib")])
    assert r.exit_code == 1
