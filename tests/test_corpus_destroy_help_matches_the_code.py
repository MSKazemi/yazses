"""`yazses corpus destroy` says what it deletes, and only that.

The help read "Irreversibly delete the entire learning corpus (database + audio clips)" and
the docs said "wipe the whole corpus", "erase everything" and "delete it all". The code
(`CorpusStore.destroy`) unlinks `corpus.db` and the `clips/*.wav.enc` files, nothing else:
`corpus.key` (which also keys `voiceprint.enc` and `participants/`), meeting transcripts,
scratch notes and approved few-shots survive. A privacy control that over-claims is worse
than one that under-claims, so this runs the real command and holds every surface that
describes it to the measured result.
"""
from __future__ import annotations

import re
import types
from pathlib import Path

import numpy as np
from typer.testing import CliRunner

import yazses.cli as cli
from yazses.learning.capture import open_store

ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()

#: Files other features keep beside the corpus; none of them may be touched by `destroy`.
BYSTANDERS = ("corpus.key", "voiceprint.enc", "scratch.jsonl", "few_shots.toml")


def _fake_platform(data_dir: Path):
    paths = types.SimpleNamespace(
        data_dir=data_dir, config_file=data_dir / "config.toml", ipc_socket=data_dir / "d.sock"
    )
    return types.SimpleNamespace(paths=paths)


def _tree(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*")}


def _measure(tmp_path, monkeypatch) -> tuple[set[str], set[str]]:
    store = open_store(tmp_path)
    store.add_event(
        {"ts": 1.0, "raw_text": "hi", "cleaned_text": "hi", "filtered_text": "hi",
         "final_text": "hi", "injected": True},
        audio=np.zeros(1600, dtype="float32"),
    )
    store.close()
    for name in BYSTANDERS[1:]:
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "meetings" / "m1").mkdir(parents=True)
    (tmp_path / "meetings" / "m1" / "transcript.md").write_text("x", encoding="utf-8")
    before = _tree(tmp_path)
    assert any(n.startswith("clips/") and n.endswith(".wav.enc") for n in before)
    monkeypatch.setattr(cli, "get_platform", lambda: _fake_platform(tmp_path))
    result = runner.invoke(cli.app, ["corpus", "destroy", "--i-mean-it"])
    assert result.exit_code == 0, result.output
    after = _tree(tmp_path)
    return before - after, after


def _help() -> str:
    result = runner.invoke(cli.app, ["corpus", "destroy", "--help"], terminal_width=200)
    assert result.exit_code == 0, result.output
    return re.sub(r"\s+", " ", result.output)


def test_the_help_names_exactly_what_the_command_removes(tmp_path, monkeypatch):
    removed, after = _measure(tmp_path, monkeypatch)
    # Measured: the database and the clip files go; the key and everything else stay.
    assert "corpus.db" in removed
    assert all(n in ("corpus.db", "clips") or n.startswith("clips/") for n in removed), removed
    for name in BYSTANDERS:
        assert name in after, f"{name} should survive `corpus destroy`"
    assert "meetings/m1/transcript.md" in after

    text = _help()
    assert "corpus.db" in text and "clips" in text
    # It must say the key and the rest stay, and must not claim a total wipe.
    assert "corpus.key" in text and "stay" in text
    assert not re.search(r"\b(entire|whole|everything|all of)\b", text, re.I), text


def test_no_doc_calls_destroy_a_total_wipe():
    """The prose around the command must not promise more than the help does."""
    over_claims = (
        re.compile(r"corpus destroy[^\n]*(wipe the whole|entire learning corpus|delete it all)", re.I),
        re.compile(r"Erase everything \| `yazses corpus destroy"),
        re.compile(r"corpus destroy`? does the same thing", re.I),
    )
    pages = [
        ROOT / "docs" / "cli-reference.md",
        ROOT / "docs" / "privacy-statement.md",
        ROOT / "docs" / "uninstall.md",
        ROOT / "docs" / "command-index.md",
        ROOT / "docs" / "use-cases" / "private-offline-dictation.md",
        ROOT / "man" / "yazses.1",
        ROOT / "src" / "yazses" / "cli.py",
    ]
    offenders = [
        f"{p.relative_to(ROOT)}: {m.group(0)!r}"
        for p in pages
        for rx in over_claims
        for m in rx.finditer(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, offenders
    # The generated surfaces must carry the corrected first line.
    for rel in ("docs/command-index.md", "man/yazses.1"):
        body = (ROOT / rel).read_text(encoding="utf-8")
        assert "entire learning corpus" not in body, rel
