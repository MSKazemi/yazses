"""Tests for the local diagnostic bundle.

Two properties matter and they pull against each other: the report must contain enough to
explain a failure, and it must not contain anything the user would not want to paste into
a public issue. The second is the one that needs tests, because a leak is only noticed
after it has been published.
"""
from __future__ import annotations

import json
from pathlib import Path

from yazses.system import report as report_mod


def test_home_directory_is_replaced_everywhere():
    home = str(Path.home())
    text = f"Logging to {home}/.local/state/yazses/log/daemon.log"

    out = report_mod.redact_text(text)

    assert home not in out, "a home path leaks the account name"
    assert "~" in out


def test_paths_and_identifiers_are_dropped_but_their_keys_survive():
    """Knowing a socket is configured is diagnostic; knowing where it points is not."""
    raw = {
        "learning": {"editor_socket": "/run/user/1000/nvim.sock", "enabled": True},
        "remote": {"host": "lab.example.com", "ssh_port": 22},
    }

    out = report_mod.redact_config(raw)

    assert out["learning"]["editor_socket"] == "<redacted>"
    assert out["remote"]["host"] == "<redacted>"
    assert "editor_socket" in out["learning"], "the key itself is useful"
    assert out["learning"]["enabled"] is True, "booleans change behaviour and identify nobody"
    assert out["remote"]["ssh_port"] == 22, "numbers are kept"


def test_empty_values_are_not_pointlessly_redacted():
    """`device = ""` means "follow the OS default" — replacing it would hide the setting."""
    out = report_mod.redact_config({"audio": {"device": ""}})

    assert out["audio"]["device"] == ""


def test_vocabulary_like_strings_still_get_home_paths_scrubbed():
    home = str(Path.home())
    out = report_mod.redact_config({"stt": {"initial_prompt": f"see {home}/notes"}})

    assert home not in out["stt"]["initial_prompt"]


def test_collect_never_opens_the_corpus(tmp_path):
    """The corpus holds real transcripts and audio. Size only."""
    corpus = tmp_path / "corpus.db"
    corpus.write_bytes(b"SECRET TRANSCRIPT CONTENT" * 100)

    data = report_mod.collect(
        config_file=tmp_path / "absent.toml",
        log_file=tmp_path / "absent.log",
        data_dir=tmp_path,
        status=None,
    )

    assert data["corpus"]["present"] is True
    assert data["corpus"]["size_mb"] >= 0
    assert "SECRET" not in json.dumps(data)


def test_collect_survives_a_dead_daemon_and_a_missing_config(tmp_path):
    """The moment a report is most needed is the moment nothing else works."""
    data = report_mod.collect(
        config_file=tmp_path / "absent.toml",
        log_file=tmp_path / "absent.log",
        data_dir=tmp_path,
        status=None,
    )

    assert data["daemon"] == {"reachable": False}
    assert "note" in data["config"]
    assert data["log_tail"] == ["<no log file>"]


def test_collect_reports_config_problems(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('[accessibility]\nvad_threshold = "0.004"\n')

    data = report_mod.collect(
        config_file=config, log_file=tmp_path / "absent.log", data_dir=tmp_path, status=None
    )

    assert any("vad_threshold" in p for p in data["config_problems"])


def test_log_tail_is_bounded_and_scrubbed(tmp_path):
    home = str(Path.home())
    log = tmp_path / "daemon.log"
    log.write_text("\n".join(f"line {i} at {home}/x" for i in range(500)))

    data = report_mod.collect(
        config_file=tmp_path / "absent.toml", log_file=log, data_dir=tmp_path,
        status=None, log_lines=50,
    )

    assert len(data["log_tail"]) == 50
    assert home not in "\n".join(data["log_tail"])


def test_write_produces_readable_json_and_a_summary(tmp_path):
    data = report_mod.collect(
        config_file=tmp_path / "absent.toml", log_file=tmp_path / "absent.log",
        data_dir=tmp_path, status={"state": "idle"},
    )

    bundle = report_mod.write(data, tmp_path / "out" / "report.json")

    assert bundle.path.exists()
    assert json.loads(bundle.path.read_text())["daemon"]["state"] == "idle"
    assert "daemon=idle" in bundle.summary


def test_report_states_the_version_that_is_actually_installed():
    """It reported 2.10.0.dev5 for months while --version said 2.12.1.

    A diagnostic that misidentifies the build is worse than one that omits it: it sends
    whoever is helping to the wrong source.
    """
    from importlib.metadata import version as pkg_version

    import yazses

    assert yazses.__version__ == pkg_version("yazses")


# ---- the account name outside $HOME -----------------------------------------


def _with_account(monkeypatch, name):
    """Point the redactor at a chosen account name."""
    import re

    monkeypatch.setattr(
        report_mod, "_ACCOUNT", re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
    )


def test_the_account_name_is_redacted_outside_the_home_directory(monkeypatch):
    """Home-only redaction missed every path that embeds the name elsewhere.

    Found by running `yazses report --print` on a real machine: the log tail
    carried `/tmp/pytest-of-<account>/...` while `/home/<account>` was correctly
    collapsed to `~`. The bundle is meant to be attached to a public issue, and its
    own help text promises "paths and identifiers removed".

    `/media/<account>/…` is the one that matters in normal use — it is where a
    transcribed file off a USB stick lives.
    """
    _with_account(monkeypatch, "ada")
    for path in (
        "/media/ada/USB-STICK/note.wav",
        "/run/media/ada/disk/note.wav",
        "/tmp/pytest-of-ada/pytest-3/x.toml",
        "sent mail to ada",
    ):
        assert "ada" not in report_mod.redact_text(path), path


def test_the_home_path_still_collapses_rather_than_being_blanked(monkeypatch):
    """Home is matched first because it is longer and more specific.

    `~/.config/yazses` is diagnostically useful; `/home/<redacted>/.config/yazses`
    is the same information with more noise.
    """
    _with_account(monkeypatch, "ada")
    out = report_mod.redact_text(f"{Path.home()}/.config/yazses/config.toml")
    assert out.startswith("~/"), out


def test_a_generic_account_name_is_left_alone(monkeypatch):
    """Redaction that destroys the report defeats its purpose as surely as
    redaction that misses.

    An account called `root`, `ubuntu` or `ci` identifies nobody, and blanking a
    common short word would shred the surrounding log — `/usr/lib/test/...`,
    `docker run`, "the build failed" — into unreadable diagnostics.
    """
    for generic in ("root", "ubuntu", "ci", "runner", "test"):
        monkeypatch.setattr("getpass.getuser", lambda g=generic: g)
        assert report_mod._account_pattern() is None, generic


def test_a_short_account_name_is_left_alone(monkeypatch):
    """Two letters cannot be matched on word boundaries without wrecking prose."""
    monkeypatch.setattr("getpass.getuser", lambda: "jo")
    assert report_mod._account_pattern() is None


def test_an_unreadable_account_never_breaks_the_report(monkeypatch):
    """A diagnostic bundle that raises while being collected is worse than one
    that redacts a little less."""
    def _boom():
        raise OSError("no passwd entry")

    monkeypatch.setattr("getpass.getuser", _boom)
    assert report_mod._account_pattern() is None


def test_the_corpus_size_counts_the_audio_clips(tmp_path):
    """`report` sized `corpus.db` alone, and the clips are almost all of it.

    Measured on a real machine: the database was 3.0 MB and the corpus was
    1294.9 MB. `yazses report` said 3.0. `yazses corpus status` said 1294.9. The
    same corpus, 430x apart, and the wrong number is the one that gets attached
    to bug reports — so a maintainer reading "3 MB" rules the corpus out of a
    disk-space problem it is in fact causing.

    It is also the number a user checks against `[learning] max_corpus_mb`
    (default 500), which prunes on the total. Reading the report, someone 2.5x
    over the cap concludes they are comfortably under it.

    Still never opens anything: this is filesystem metadata, the same stat calls
    the store's own pruning uses.
    """
    from yazses.system import report as report_mod

    data_dir = tmp_path / "data"
    (data_dir / "clips").mkdir(parents=True)
    (data_dir / "corpus.db").write_bytes(b"x" * 3_000_000)
    for i in range(4):
        (data_dir / "clips" / f"{i}.wav.enc").write_bytes(b"y" * 2_000_000)

    cfg = tmp_path / "config.toml"
    cfg.write_text("")
    log = tmp_path / "yazses.log"
    log.write_text("")
    data = report_mod.collect(
        config_file=cfg, log_file=log, data_dir=data_dir, status=None
    )
    size = data["corpus"]["size_mb"]
    expected = 11_000_000 / 1_048_576  # the cap enforces mebibytes; so must this
    assert abs(size - expected) < 0.2, (
        f"expected the database plus its clips ({expected:.1f}); got {size} — "
        "clips are almost all of a real corpus"
    )

    # The reported number exists to be compared against `[learning] max_corpus_mb`,
    # so it must be in the unit the prune enforces. Dividing by 1e6 made `report` and
    # `corpus status` disagree on one corpus, which reads as a bug in one of them.
    from yazses.learning.store import corpus_disk_bytes

    assert size == round(corpus_disk_bytes(data_dir) / 1_048_576, 1)
