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


def test_cite_plain_style_prints_what_it_always_printed(tmp_path):
    """`plain` is accepted but its own format is undecided, so it prints the APA form."""
    bib = tmp_path / "refs.bib"
    bib.write_text(BIB, encoding="utf-8")
    r = runner.invoke(cli.app, ["cite", "vaswani 2017", "--bib", str(bib), "--style", "plain"])
    assert r.exit_code == 0, r.output
    assert r.output.strip() == "Vaswani et al. (2017)"


def test_cite_unknown_style_exits_nonzero_and_lists_the_valid_styles(tmp_path):
    """An unknown style used to print APA with exit 0, so a typo looked like success."""
    bib = tmp_path / "refs.bib"
    bib.write_text(BIB, encoding="utf-8")
    r = runner.invoke(cli.app, ["cite", "vaswani 2017", "--bib", str(bib), "--style", "bogus"])
    assert r.exit_code != 0, r.output
    assert "bogus" in r.output
    for valid in ("latex", "plain", "apa"):
        assert valid in r.output


def test_cite_reads_a_latin1_bib_instead_of_a_traceback(tmp_path):
    bib = tmp_path / "refs.bib"
    bib.write_bytes(
        "@article{gonzalez2017,\n  author = {Gonzalez, Jose},\n  year = {2017},\n"
        "  title = {Café study}\n}\n".encode("latin-1")
    )
    r = runner.invoke(cli.app, ["cite", "gonzalez 2017", "--bib", str(bib)])
    assert r.exit_code == 0, r.output
    assert r.output.strip() == "\\cite{gonzalez2017}"


def test_cite_on_undecodable_bytes_never_raises(tmp_path):
    bib = tmp_path / "refs.bib"
    bib.write_bytes(b"\x89PNG\r\n\x1a\n\x00\xff\xfe\x80 not bibtex")
    r = runner.invoke(cli.app, ["cite", "x 2020", "--bib", str(bib)])
    assert isinstance(r.exception, (SystemExit, type(None))), repr(r.exception)
    assert r.exit_code == 1


def test_cite_empty_bib_says_it_has_no_entries(tmp_path):
    bib = tmp_path / "empty.bib"
    bib.write_text("", encoding="utf-8")
    r = runner.invoke(cli.app, ["cite", "vaswani 2017", "--bib", str(bib)])
    assert r.exit_code == 1
    assert "has no entries" in r.output
    assert "No confident citation match" not in r.output


def test_cite_empty_query_says_the_query_is_empty(tmp_path):
    bib = tmp_path / "refs.bib"
    bib.write_text(BIB, encoding="utf-8")
    r = runner.invoke(cli.app, ["cite", "   ", "--bib", str(bib)])
    assert r.exit_code == 1
    assert "query is empty" in r.output
    assert "No confident citation match" not in r.output
