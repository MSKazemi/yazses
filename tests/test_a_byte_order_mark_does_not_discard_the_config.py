"""A UTF-8 BOM must not throw away everything the user configured.

`tomllib` rejects a leading byte-order mark: the TOML specification has no place for
one, so the first line fails to parse and, because a TOML document parses as a whole,
**the entire file is lost**. `load_config` then falls back to defaults — model,
hotkey, VAD threshold, injector, every setting — and reports

    could not be read (Invalid statement (at line 1, column 1))

about a line that looks perfectly correct on screen, because the offending bytes are
invisible. The user sees dictation behave as though they had never configured it.

That is not an exotic input. Windows PowerShell 5.1 — the default shell on Windows —
writes UTF-8 **with** a BOM from `Set-Content` and `Out-File`, and "UTF-8 with BOM" is
still an offered encoding in Notepad and Visual Studio. Every hand-edited TOML this
project reads was affected: `config.toml`, the macros file, the style-rules file, and
the copy `yazses report` includes in a diagnostic bundle.

`yazses.tomlio` strips a leading BOM and changes nothing else, so an invisible encoding
artefact stops being a syntax error while a real syntax error still is — the assertions
below hold both halves. `configedit` reads `utf-8-sig`, so writing a setting also
repairs a file that already had one rather than carrying it forward.
"""

from __future__ import annotations

import pathlib

import pytest

from yazses.commands.macros import load_macros
from yazses.config import load_config_checked
from yazses.styleguard.loader import load_rules_file
from yazses.system.configedit import set_config_key
from yazses.system.report import collect

BOM = b"\xef\xbb\xbf"

CONFIG = b"[stt]\nmodel = 'small.en'\n[hotkey]\nkey = 'KEY_F13'\n"
MACROS = b'[[macro]]\ntrigger = "sig"\ntype = "text"\ntext = "Best,"\n'
RULES = b'[[rule]]\npreferred = "e-mail"\nvariants = ["email"]\n'


@pytest.mark.parametrize("prefix", [b"", BOM], ids=["plain", "utf-8-bom"])
def test_the_config_survives_a_byte_order_mark(prefix: bytes, tmp_path: pathlib.Path) -> None:
    """Both settings, not just the first: the failure was whole-document, so a test
    that checked one key could pass on a file that had lost the rest."""
    path = tmp_path / "config.toml"
    path.write_bytes(prefix + CONFIG)
    loaded = load_config_checked(path)
    assert loaded.config.stt.model == "small.en"
    assert loaded.config.hotkey.key == "KEY_F13"
    assert loaded.problems == [], (
        f"a BOM was reported as a config problem: {[str(p) for p in loaded.problems]}"
    )


@pytest.mark.parametrize("prefix", [b"", BOM], ids=["plain", "utf-8-bom"])
def test_the_macros_file_survives_a_byte_order_mark(prefix: bytes, tmp_path: pathlib.Path) -> None:
    path = tmp_path / "macros.toml"
    path.write_bytes(prefix + MACROS)
    assert load_macros(path).match("sig") is not None


@pytest.mark.parametrize("prefix", [b"", BOM], ids=["plain", "utf-8-bom"])
def test_the_style_rules_survive_a_byte_order_mark(prefix: bytes, tmp_path: pathlib.Path) -> None:
    path = tmp_path / "rules.toml"
    path.write_bytes(prefix + RULES)
    assert len(load_rules_file(path)) == 1


@pytest.mark.parametrize("prefix", [b"", BOM], ids=["plain", "utf-8-bom"])
def test_the_diagnostic_report_reads_a_config_with_a_byte_order_mark(
    prefix: bytes, tmp_path: pathlib.Path,
) -> None:
    """`yazses report` is what someone sends when nothing works. A bundle saying the
    config is `unreadable` would point every reader at the wrong problem."""
    path = tmp_path / "config.toml"
    path.write_bytes(prefix + CONFIG)
    report = collect(
        config_file=path, log_file=tmp_path / "absent.log", data_dir=tmp_path, status=None
    )
    # The hotkey is redacted by `redact_config`, so only its presence is asserted —
    # what matters here is that both sections arrived, not their values.
    assert report["config"]["stt"] == {"model": "small.en"}
    assert "hotkey" in report["config"]
    assert report["config_problems"] == []


def test_writing_a_setting_removes_a_byte_order_mark_the_file_already_had(
    tmp_path: pathlib.Path,
) -> None:
    """`yazses features enable`, `hotkey set` and `audio use` all go through here.
    Reading `utf-8` and writing it back would preserve the BOM, so the one command a
    user runs to fix their config would keep re-emitting the thing that broke it."""
    path = tmp_path / "config.toml"
    path.write_bytes(BOM + CONFIG)
    set_config_key(path, "stt", "model", "base.en")
    assert not path.read_bytes().startswith(BOM), "the BOM was carried into the rewrite"
    assert load_config_checked(path).config.stt.model == "base.en"


def test_a_real_syntax_error_is_still_reported(tmp_path: pathlib.Path) -> None:
    """The fix widens what parses, not what is accepted. Without this, a loader that
    swallowed every error would pass every test above."""
    path = tmp_path / "config.toml"
    path.write_bytes(BOM + b"[stt\nmodel = 'small.en'\n")
    loaded = load_config_checked(path)
    assert loaded.problems, "an unclosed section header parsed cleanly"
    assert loaded.config.stt.model != "small.en"


def test_a_file_that_is_not_utf8_is_reported_rather_than_crashing(
    tmp_path: pathlib.Path,
) -> None:
    """Decoding moved out of `tomllib` and into our code, so the exception type moved
    too. `UnicodeDecodeError` is a `ValueError`, which is what the caller catches —
    asserted here because that is the only reason the daemon still starts."""
    path = tmp_path / "config.toml"
    path.write_bytes(b"[stt]\nmodel = '\xff\xfe not utf-8'\n")
    loaded = load_config_checked(path)
    assert loaded.problems, "invalid bytes parsed cleanly"


@pytest.mark.parametrize("prefix", [b"", BOM], ids=["plain", "utf-8-bom"])
def test_the_vocabulary_file_survives_a_byte_order_mark(
    prefix: bytes, tmp_path: pathlib.Path,
) -> None:
    """Line-oriented, so a BOM costs one entry rather than the file — and it is the
    *first* entry, which is the one the user added first and cares about most.

    It fails three ways at once and looks fine in all of them: `"\\ufeffKubernetes"`
    renders identically to `Kubernetes` in `yazses vocab list`, is not matched by
    `yazses vocab remove Kubernetes`, and reaches Whisper's `initial_prompt` as a token
    the model has never seen, so priming that word silently stops working.
    """
    from yazses.system.vocabulary import load_vocab

    path = tmp_path / "vocabulary.txt"
    path.write_bytes(prefix + b"Kubernetes\nEuroHPC\n")
    assert load_vocab(path) == ["Kubernetes", "EuroHPC"]


def test_importing_a_vocabulary_strips_a_byte_order_mark(tmp_path: pathlib.Path) -> None:
    """`yazses vocab import` takes text from a file someone else exported and sent on,
    which is exactly where a foreign editor's encoding arrives."""
    from yazses.system.vocabulary import parse_vocab

    assert parse_vocab("﻿Kubernetes\nEuroHPC\n") == ["Kubernetes", "EuroHPC"]


def test_adding_a_word_repairs_a_vocabulary_that_had_a_byte_order_mark(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "vocabulary.txt"
    path.write_bytes(BOM + b"Kubernetes\n")
    from yazses.system.vocabulary import add_vocab, load_vocab

    add_vocab(path, ["Slurm"])
    assert not path.read_bytes().startswith(BOM)
    assert load_vocab(path) == ["Kubernetes", "Slurm"]


def test_a_vocabulary_that_is_not_utf8_is_still_tolerated(tmp_path: pathlib.Path) -> None:
    """The BOM fix moved the decode to `utf-8-sig`; invalid bytes must still be
    replaced-with-a-warning rather than raising, because dictation continues."""
    from yazses.system.vocabulary import load_vocab

    path = tmp_path / "vocabulary.txt"
    path.write_bytes(b"\xff\xfe oops\n")
    assert load_vocab(path), "an unreadable vocabulary file now yields nothing at all"
