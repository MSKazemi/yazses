"""One non-UTF-8 byte in `vocabulary.txt` broke every dictation burst.

`core/daemon.py::_on_hold_end` reads the personal dictionary on **every** burst, to build
Whisper's `initial_prompt`. `load_vocab` decoded strictly, so:

    b"good\\nb\\xffad\\n"   ->  UnicodeDecodeError
    a directory at that path  ->  IsADirectoryError

Both raise inside the burst's `try`, which sets `pipeline_failed` and reports a generic
"could not type that". So every dictation failed, the toast named nothing, and the log said
`UnicodeDecodeError` without mentioning the vocabulary file. The daemon survived; the
product did not work.

The file is documented as user-editable and `yazses vocab add` is only one way to fill it —
a word pasted from an editor in another encoding is enough.

## Tolerant to read, strict to write

Losing one mojibake term costs a word that would never have matched anyway. Losing every
burst costs the product. So reading replaces the bad bytes and logs the path.

Writing must not. `add_vocab` and `remove_vocab` rewrite the **whole** file from that list,
so a tolerant read there would persist the replacement characters into the dictionary — a
silent corruption of the user's own data, caused by trying to help. They pass `strict=True`
and refuse.

## The warning had to be made reachable

The first version hung the warning off `except UnicodeDecodeError` around a
`read_text(errors="replace")` call, which never raises — so the file would have been mangled
with nothing said, which is the failure this function exists to end. It decodes strictly
first now and falls back deliberately.
"""

from __future__ import annotations

import shutil

import pytest

from yazses.system.vocabulary import add_vocab, load_vocab, remove_vocab, vocab_path

BAD_BYTES = b"good\nb\xffad\nfine\n"


@pytest.fixture
def vocab(tmp_path):
    return vocab_path(tmp_path)


def test_bad_bytes_do_not_break_the_read(vocab) -> None:
    """The burst path: every dictation used to fail on this."""
    vocab.write_bytes(BAD_BYTES)
    words = load_vocab(vocab)
    assert "good" in words and "fine" in words
    assert len(words) == 3


def test_bad_bytes_are_logged_with_the_path(vocab, caplog) -> None:
    """Silently mangling the file is the failure this exists to end."""
    vocab.write_bytes(BAD_BYTES)
    with caplog.at_level("WARNING"):
        load_vocab(vocab)
    # `r.getMessage()`, not `r.message % r.args`: caplog already interpolated `message`,
    # so re-applying the args raises "not all arguments converted".
    assert any(str(vocab) in r.getMessage() for r in caplog.records), (
        "the bad file was replaced silently"
    )


def test_an_unreadable_path_yields_nothing_rather_than_raising(vocab) -> None:
    vocab.mkdir()
    try:
        assert load_vocab(vocab) == []
    finally:
        shutil.rmtree(vocab)


def test_a_clean_file_is_unaffected(vocab) -> None:
    """The expensive direction: a reader that dropped words would pass the tests above."""
    vocab.write_text("YazSes\nKubernetes\n", encoding="utf-8")
    assert load_vocab(vocab) == ["YazSes", "Kubernetes"]


def test_a_missing_file_is_still_empty(vocab) -> None:
    assert load_vocab(vocab) == []


def test_non_ascii_that_is_valid_utf8_is_kept_intact(vocab) -> None:
    """Replacement must not fire on legitimate accented or non-Latin words."""
    vocab.write_text("Bologna\nSeyedkazemi\nمحسن\ncafé\n", encoding="utf-8")
    assert load_vocab(vocab) == ["Bologna", "Seyedkazemi", "محسن", "café"]


@pytest.mark.parametrize("writer", [lambda p: add_vocab(p, ["new"]), lambda p: remove_vocab(p, "good")])
def test_the_writers_refuse_a_file_they_cannot_read_exactly(vocab, writer) -> None:
    """They rewrite the WHOLE file, so a tolerant read here would persist the damage."""
    vocab.write_bytes(BAD_BYTES)
    with pytest.raises(UnicodeDecodeError):
        writer(vocab)
    assert vocab.read_bytes() == BAD_BYTES, "the dictionary was rewritten anyway"


def test_the_writers_still_work_on_a_clean_file(vocab) -> None:
    """A strict writer that refused everything would pass the test above."""
    vocab.write_text("YazSes\n", encoding="utf-8")
    assert add_vocab(vocab, ["Kubernetes"]) == ["YazSes", "Kubernetes"]
    assert remove_vocab(vocab, "yazses") == ["Kubernetes"]


def test_the_burst_path_reads_this_file() -> None:
    """The reason tolerance is the right default; if the daemon stops reading it per
    burst, the trade-off in this file should be revisited."""
    import inspect

    from yazses.core.daemon import Daemon

    assert "load_vocab(vocab_path(" in inspect.getsource(Daemon._on_hold_end)
