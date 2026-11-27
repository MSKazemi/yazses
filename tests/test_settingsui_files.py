"""The File transcription page's decisions: the command it runs and where text lands."""
from __future__ import annotations

from pathlib import Path

import pytest

from yazses.settingsui import files


def _job(tmp_path, name="talk.mp3", **extra):
    return files.Job(source=tmp_path / name, **extra)


def test_the_output_sits_beside_the_source(tmp_path):
    assert files.output_path(_job(tmp_path, fmt="srt")) == tmp_path / "talk.srt"


def test_the_output_never_replaces_the_source(tmp_path):
    job = _job(tmp_path, "notes.txt", fmt="txt")
    assert files.output_path(job) != job.source


def _tail(job):
    argv = files.command(job)
    return argv[argv.index("transcribe"):]


def test_the_default_command_names_format_output_and_no_speakers(tmp_path):
    job = _job(tmp_path)
    assert _tail(job) == [
        "transcribe", str(tmp_path / "talk.mp3"), "--format", "txt",
        "--out", str(tmp_path / "talk.txt"), "--no-diarize",
    ]


def test_every_option_reaches_the_command(tmp_path):
    job = _job(tmp_path, fmt="md", model="small.en", speakers=True, count=3, translate=True)
    tail = _tail(job)
    assert "--diarize" in tail
    for flag, value in (("--speakers", "3"), ("--model", "small.en"), ("--language", "translate")):
        assert tail[tail.index(flag) + 1] == value


def test_a_speaker_count_is_ignored_without_speaker_labels(tmp_path):
    assert "--speakers" not in _tail(_job(tmp_path, speakers=False, count=3))


def test_a_path_with_spaces_and_non_ascii_stays_one_argument(tmp_path):
    job = _job(tmp_path, "گفتگو با تیم (1).m4a")
    assert str(job.source) in files.command(job)


def test_a_relative_source_is_made_absolute_so_it_cannot_read_as_a_flag():
    job = files.Job(source=Path("-weird.mp3"))
    argv = files.command(job)
    assert str(Path("-weird.mp3").resolve()) in argv
    assert "-weird.mp3" not in argv


def test_an_unknown_format_is_refused(tmp_path):
    with pytest.raises(ValueError):
        files.command(_job(tmp_path, fmt="docx"))


def test_the_failure_text_is_the_end_of_what_the_command_said():
    noise = "\n".join(f"line {i}" for i in range(50))
    text = files.failure_text(noise + "\nUnknown --model 'x'.\n")
    assert text.endswith("Unknown --model 'x'.")
    assert len(text) <= 600


def test_a_silent_failure_still_says_something():
    assert files.failure_text("  \n") == "Transcription failed without a message."


def test_a_preview_is_bounded_and_never_raises(tmp_path):
    big = tmp_path / "big.txt"
    big.write_text("a" * 500_000, encoding="utf-8")
    assert len(files.preview(big)) < 210_000
    assert "could not be read" in files.preview(tmp_path / "missing.txt")


def test_the_notes_are_the_lines_the_command_marked_as_such():
    stderr = "Loading model 'base.en'…\nNote: no speech was recognised.\nINFO x: y\n"
    assert files.notes(stderr) == "Note: no speech was recognised."
    assert files.notes("Transcribing…\n") == ""
