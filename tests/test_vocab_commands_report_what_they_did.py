"""`yazses vocab add/remove` must say what happened, not what was asked for.

Both commands echoed the argument back regardless of outcome, and one of them
crashed before it got that far:

* `vocab remove` was the only writer in the module with no ``mkdir``. On a machine
  where nobody has added a word the config directory does not exist, so a plain typo
  answered with a `FileNotFoundError` traceback — on the command whose entire job is
  undoing a mistake.
* Once the directory existed, `vocab remove <not-a-word>` printed "Removed 'x'" and
  exited 0. That is a false statement with a cost: the user believes the word is gone,
  and is left with the mis-transcription and no reason for it.
* `vocab add ""` printed "Added . Dictionary now has 0 word(s)." — a success message
  for nothing, next to a count contradicting it. `add_vocab` drops blanks and
  case-insensitive duplicates, so the argument was never what was added.

Exit codes matter here beyond tidiness: these are the commands people put in a setup
script when moving to a new machine.
"""

from __future__ import annotations

import pathlib

import pytest
from typer.testing import CliRunner

from yazses.cli import app
from yazses.system.vocabulary import add_vocab, load_vocab, remove_vocab

runner = CliRunner()


@pytest.fixture
def config_dir(sandbox_paths) -> pathlib.Path:
    """A machine where YazSes has never written anything — the state a fresh install
    is in, and the one `vocab remove` crashed on.

    Sandboxed through `sandbox_paths`, which patches `build_paths()`, rather than by
    setting the XDG variables. Those are a Linux answer to a cross-platform question:
    `platformdirs` resolves the Windows folders through the OS and never reads them,
    so on both Windows legs the CLI wrote the *runner's own*
    `%APPDATA%\\yazses\\vocabulary.txt` while the assertions read a temporary
    directory that stayed empty — `assert [] == ['Kubernetes']`, on every run since
    this file was added in d075588, which is where `main`'s Windows legs went red.

    The red leg is the lesser half. A test that edits the machine it runs on would
    have appended `Kubernetes` and `EuroHPC` to a real person's personal dictionary,
    where they then reach Whisper's `initial_prompt` on every burst. `conftest.py`
    watches `config.toml` and the pid file for exactly that and did not watch this
    file, so nothing on a green platform would ever have said so.
    """
    return sandbox_paths.config_dir


def test_removing_from_a_dictionary_that_does_not_exist_yet(config_dir) -> None:
    result = runner.invoke(app, ["vocab", "remove", "Kubernetes"])
    assert result.exit_code == 1, result.output
    assert "Traceback" not in result.output
    assert "not in your dictionary" in result.output
    assert not config_dir.exists(), "a failed removal created the config directory"


def test_removing_a_word_that_is_not_there_is_not_reported_as_a_removal(
    config_dir,
) -> None:
    assert runner.invoke(app, ["vocab", "add", "Kubernetes"]).exit_code == 0
    result = runner.invoke(app, ["vocab", "remove", "EuroHPC"])
    assert result.exit_code == 1, result.output
    assert "Removed" not in result.output
    assert load_vocab(config_dir / "vocabulary.txt") == ["Kubernetes"]


def test_a_real_removal_still_works_and_is_case_insensitive(config_dir) -> None:
    runner.invoke(app, ["vocab", "add", "Kubernetes", "EuroHPC"])
    result = runner.invoke(app, ["vocab", "remove", "kubernetes"])
    assert result.exit_code == 0, result.output
    assert "Removed 'kubernetes'" in result.output
    assert load_vocab(config_dir / "vocabulary.txt") == ["EuroHPC"]


def test_adding_nothing_is_not_reported_as_an_addition(config_dir) -> None:
    result = runner.invoke(app, ["vocab", "add", ""])
    assert result.exit_code == 1, result.output
    assert "Added" not in result.output
    assert "Nothing was added" in result.output


def test_adding_a_duplicate_is_not_reported_as_an_addition(config_dir) -> None:
    runner.invoke(app, ["vocab", "add", "Kubernetes"])
    result = runner.invoke(app, ["vocab", "add", "KUBERNETES"])
    assert result.exit_code == 1, result.output
    assert "Nothing was added" in result.output


def test_a_mixed_add_names_only_the_words_that_landed(config_dir) -> None:
    """The message is the only feedback there is, so it must not credit a word the
    dictionary already had."""
    runner.invoke(app, ["vocab", "add", "Kubernetes"])
    result = runner.invoke(app, ["vocab", "add", "kubernetes", "Slurm"])
    assert result.exit_code == 0, result.output
    assert "Added Slurm." in result.output
    assert "kubernetes" not in result.output.split("Added")[1].split(".")[0]


def test_remove_does_not_write_when_nothing_matched(tmp_path: pathlib.Path) -> None:
    """The unit beneath the CLI: a no-op removal must leave the file untouched, so a
    failed `vocab remove` cannot create an empty dictionary as a side effect."""
    path = tmp_path / "nested" / "vocabulary.txt"
    assert remove_vocab(path, "absent") == []
    assert not path.exists()
    assert not path.parent.exists()

    add_vocab(path, ["Kubernetes"])
    before = path.read_bytes()
    assert remove_vocab(path, "absent") == ["Kubernetes"]
    assert path.read_bytes() == before
