"""Moving the personal dictionary between machines (#295).

The vocabulary is the main lever anyone has over recognition of their *own* proper
nouns, package names and acronyms. Without export/import every new machine starts
that work from zero and a team cannot share it at all.

The round-trip is the test worth having: export → import → export must be
byte-identical, or the format quietly is not a format.
"""

from __future__ import annotations

import types

import pytest
from typer.testing import CliRunner

import yazses.cli as cli
from yazses.system.vocabulary import (
    add_vocab,
    export_vocab,
    import_vocab,
    load_vocab,
    parse_vocab,
)

runner = CliRunner()


@pytest.fixture()
def vocab(tmp_path):
    return tmp_path / "vocabulary.txt"


def _fake_platform(tmp_path):
    return types.SimpleNamespace(
        paths=types.SimpleNamespace(config_file=tmp_path / "config.toml")
    )


# ---- the round-trip --------------------------------------------------------


def test_export_import_export_is_byte_identical(vocab, tmp_path):
    add_vocab(vocab, ["Kubernetes", "kubectl", "YazSes", "faster-whisper"])
    first = export_vocab(vocab)

    elsewhere = tmp_path / "other" / "vocabulary.txt"
    import_vocab(elsewhere, first)

    assert export_vocab(elsewhere) == first


def test_an_empty_dictionary_exports_to_nothing_not_to_a_blank_line(vocab):
    """A stray newline would import as nothing but diff as a change."""
    assert export_vocab(vocab) == ""


def test_the_export_ends_with_exactly_one_newline(vocab):
    add_vocab(vocab, ["one", "two"])
    text = export_vocab(vocab)
    assert text.endswith("\n") and not text.endswith("\n\n")


# ---- merging is the default, and must not grow the file --------------------


def test_importing_the_same_list_twice_adds_nothing_the_second_time(vocab):
    """Repeated imports would otherwise dilute the STT prompt, which is not free."""
    text = "alpha\nbeta\ngamma\n"
    import_vocab(vocab, text)
    _, added = import_vocab(vocab, text)
    assert added == 0
    assert load_vocab(vocab) == ["alpha", "beta", "gamma"]


def test_merging_keeps_what_was_already_there(vocab):
    add_vocab(vocab, ["mine"])
    full, added = import_vocab(vocab, "theirs\n")
    assert full == ["mine", "theirs"]
    assert added == 1


def test_duplicates_collapse_case_insensitively(vocab):
    add_vocab(vocab, ["Kubectl"])
    full, added = import_vocab(vocab, "kubectl\nKUBECTL\n")
    assert added == 0
    assert full == ["Kubectl"], "the existing spelling wins"


def test_duplicates_within_one_import_collapse_too():
    assert parse_vocab("a\nA\na\n") == ["a"]


# ---- the shared-file format ------------------------------------------------


def test_comments_and_blank_lines_are_skipped():
    """So a shared domain vocabulary can explain what it is for."""
    assert parse_vocab("# team jargon\n\nkubectl\n\n# infra\nterraform\n") == [
        "kubectl", "terraform",
    ]


def test_surrounding_whitespace_is_trimmed():
    assert parse_vocab("  spaced  \n\tTabbed\t\n") == ["spaced", "Tabbed"]


def test_multi_word_phrases_survive():
    """Entries are phrases, not tokens — the prompt takes either."""
    assert parse_vocab("Ada Lovelace\nfaster-whisper\n") == ["Ada Lovelace", "faster-whisper"]


# ---- replace ---------------------------------------------------------------


def test_replace_discards_what_was_there(vocab):
    add_vocab(vocab, ["old", "stale"])
    full, added = import_vocab(vocab, "fresh\n", replace=True)
    assert full == ["fresh"] and added == 1
    assert load_vocab(vocab) == ["fresh"]


def test_replace_into_a_missing_file_creates_it(vocab, tmp_path):
    target = tmp_path / "nested" / "deep" / "vocabulary.txt"
    import_vocab(target, "word\n", replace=True)
    assert load_vocab(target) == ["word"]


# ---- the CLI ---------------------------------------------------------------


def test_export_writes_to_stdout_so_it_pipes(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_platform", lambda: _fake_platform(tmp_path))
    add_vocab(tmp_path / "vocabulary.txt", ["kubectl", "YazSes"])

    result = runner.invoke(cli.app, ["vocab", "export"])

    assert result.exit_code == 0
    assert result.stdout == "kubectl\nYazSes\n", repr(result.stdout)


def test_export_to_a_file_reports_the_count(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_platform", lambda: _fake_platform(tmp_path))
    add_vocab(tmp_path / "vocabulary.txt", ["one", "two"])
    out = tmp_path / "backup" / "vocab.txt"

    result = runner.invoke(cli.app, ["vocab", "export", "-o", str(out)])

    assert result.exit_code == 0
    assert out.read_text() == "one\ntwo\n"
    assert "2 word" in result.output


def test_import_from_a_file_merges(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_platform", lambda: _fake_platform(tmp_path))
    add_vocab(tmp_path / "vocabulary.txt", ["mine"])
    src = tmp_path / "team.txt"
    src.write_text("theirs\nmine\n")

    result = runner.invoke(cli.app, ["vocab", "import", str(src)])

    assert result.exit_code == 0
    assert "Imported 1 new word" in result.output
    assert "restart" in result.output, "the change is not live until then"
    assert load_vocab(tmp_path / "vocabulary.txt") == ["mine", "theirs"]


def test_import_from_stdin(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_platform", lambda: _fake_platform(tmp_path))
    result = runner.invoke(cli.app, ["vocab", "import", "-"], input="piped\nwords\n")
    assert result.exit_code == 0
    assert load_vocab(tmp_path / "vocabulary.txt") == ["piped", "words"]


def test_import_of_a_missing_file_says_so_rather_than_traceback(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_platform", lambda: _fake_platform(tmp_path))
    result = runner.invoke(cli.app, ["vocab", "import", str(tmp_path / "nope.txt")])
    assert result.exit_code == 1
    assert "No such file" in result.output


def test_replace_asks_before_discarding_an_existing_dictionary(tmp_path, monkeypatch):
    """One keystroke away from --merge, and it throws away the user's own work."""
    monkeypatch.setattr(cli, "get_platform", lambda: _fake_platform(tmp_path))
    add_vocab(tmp_path / "vocabulary.txt", ["precious"])
    src = tmp_path / "other.txt"
    src.write_text("replacement\n")

    result = runner.invoke(cli.app, ["vocab", "import", str(src), "--replace"], input="n\n")

    assert result.exit_code != 0, "declining must not proceed"
    assert load_vocab(tmp_path / "vocabulary.txt") == ["precious"]


def test_replace_proceeds_when_confirmed(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_platform", lambda: _fake_platform(tmp_path))
    add_vocab(tmp_path / "vocabulary.txt", ["old"])
    src = tmp_path / "other.txt"
    src.write_text("new\n")

    result = runner.invoke(cli.app, ["vocab", "import", str(src), "--replace"], input="y\n")

    assert result.exit_code == 0
    assert load_vocab(tmp_path / "vocabulary.txt") == ["new"]


def test_replace_with_yes_does_not_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_platform", lambda: _fake_platform(tmp_path))
    add_vocab(tmp_path / "vocabulary.txt", ["old"])
    src = tmp_path / "other.txt"
    src.write_text("new\n")

    result = runner.invoke(cli.app, ["vocab", "import", str(src), "--replace", "--yes"])

    assert result.exit_code == 0
    assert "Continue?" not in result.output
    assert load_vocab(tmp_path / "vocabulary.txt") == ["new"]


def test_replace_on_an_empty_dictionary_does_not_prompt(tmp_path, monkeypatch):
    """There is nothing to lose, so a confirmation would be noise."""
    monkeypatch.setattr(cli, "get_platform", lambda: _fake_platform(tmp_path))
    src = tmp_path / "other.txt"
    src.write_text("new\n")

    result = runner.invoke(cli.app, ["vocab", "import", str(src), "--replace"])

    assert result.exit_code == 0
    assert load_vocab(tmp_path / "vocabulary.txt") == ["new"]


def test_the_exported_text_is_what_import_accepts(tmp_path, monkeypatch):
    """The two halves are a format; a CLI round-trip proves they agree."""
    monkeypatch.setattr(cli, "get_platform", lambda: _fake_platform(tmp_path))
    add_vocab(tmp_path / "vocabulary.txt", ["Kubernetes", "Ada Lovelace"])

    exported = runner.invoke(cli.app, ["vocab", "export"]).stdout
    (tmp_path / "config.toml").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "vocabulary.txt").unlink()
    runner.invoke(cli.app, ["vocab", "import", "-"], input=exported)

    assert runner.invoke(cli.app, ["vocab", "export"]).stdout == exported
