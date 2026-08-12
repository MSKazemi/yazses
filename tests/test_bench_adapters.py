"""External benchmark adapters — command construction, output reading, and refusals.

None of the rival tools are installed on a CI runner, and that is the point: the parts
worth testing are the ones that must behave correctly *before* anyone has the binaries.
The failure this guards against is a benchmark that silently scores a missing tool as an
empty transcript — a 100% word error rate that looks like a measurement and would make
the published comparison dishonest in our favour.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    # @dataclass resolves its own module through sys.modules; without this the class
    # body raises AttributeError on a by-path import.
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def adapters():
    return _load("bench_adapters")


def test_every_adapter_is_fully_described(adapters) -> None:
    """A results row without a caveat is how a benchmark becomes misleading."""
    for key, adapter in adapters.ADAPTERS.items():
        assert adapter.name, key
        assert adapter.binary, key
        assert len(adapter.note) > 30, f"{key} needs a real caveat, not a label"
        assert adapters.describe(key).startswith(adapter.name)


def test_vosk_note_refuses_to_be_read_as_nerd_dictation(adapters) -> None:
    """nerd-dictation has no file input — it is a live-microphone tool.

    Measuring VOSK is a legitimate stand-in because it is the engine underneath, but a
    table row labelled "nerd-dictation" would be a claim we did not measure.
    """
    note = adapters.ADAPTERS["vosk"].note
    assert "nerd-dictation" in note
    assert "NOT" in note


def test_missing_binary_raises_rather_than_returning_empty(adapters, monkeypatch) -> None:
    monkeypatch.setattr(adapters.shutil, "which", lambda _binary: None)
    with pytest.raises(adapters.AdapterUnavailable) as excinfo:
        adapters.transcribe("whisper-cpp", Path("/tmp/nope.wav"))
    assert "not on PATH" in str(excinfo.value)


def test_unknown_tool_is_a_key_error_listing_the_known_ones(adapters) -> None:
    with pytest.raises(KeyError) as excinfo:
        adapters.transcribe("dragon-naturally-speaking", Path("/tmp/nope.wav"))
    assert "whisper-cpp" in str(excinfo.value)


def test_whisper_cpp_argv_suppresses_timestamps_and_progress(adapters, tmp_path) -> None:
    wav = Path("/audio/a.wav")
    argv = adapters.ADAPTERS["whisper-cpp"].argv(wav, "ggml-base.en.bin", tmp_path)
    assert argv[0] == "whisper-cli"
    assert "-nt" in argv and "-np" in argv, "stray timestamps would wreck the WER score"
    # `str(wav)`, never the literal "/audio/a.wav". The adapter hands whisper-cli a
    # *native* path, which is what it needs, so on Windows this argument is
    # `\audio\a.wav`. Asserting the POSIX spelling tested the platform rather than the
    # adapter, and turned the Windows job red on main while Linux and macOS stayed green.
    assert str(wav) in argv


def test_openai_whisper_argv_writes_into_the_scratch_dir(adapters, tmp_path) -> None:
    argv = adapters.ADAPTERS["openai-whisper"].argv(Path("/audio/a.wav"), "base.en", tmp_path)
    assert str(tmp_path) in argv, "output must land in the per-run temp dir, not the corpus"
    assert "txt" in argv


def test_vosk_argv_omits_the_model_flag_when_no_model_given(adapters, tmp_path) -> None:
    with_model = adapters.ADAPTERS["vosk"].argv(Path("/a.wav"), "model-dir", tmp_path)
    without = adapters.ADAPTERS["vosk"].argv(Path("/a.wav"), "", tmp_path)
    assert "-m" in with_model
    assert "-m" not in without


def test_sidecar_reader_returns_the_written_transcript(adapters, tmp_path) -> None:
    (tmp_path / "a.txt").write_text("  hello world \n", encoding="utf-8")
    assert adapters._read_txt_sidecar("ignored stdout", tmp_path) == "hello world"


def test_sidecar_reader_raises_when_the_tool_wrote_nothing(adapters, tmp_path) -> None:
    with pytest.raises(RuntimeError):
        adapters._read_txt_sidecar("", tmp_path)


def test_nonzero_exit_raises_with_the_tail_of_stderr(adapters, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(adapters.shutil, "which", lambda _binary: "/usr/bin/whisper-cli")

    class _Proc:
        returncode = 2
        stdout = ""
        stderr = "line one\nfailed to load model\n"

    monkeypatch.setattr(adapters.subprocess, "run", lambda *a, **k: _Proc())
    with pytest.raises(RuntimeError) as excinfo:
        adapters.transcribe("whisper-cpp", tmp_path / "a.wav")
    assert "failed to load model" in str(excinfo.value)


def test_successful_run_returns_stripped_stdout(adapters, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(adapters.shutil, "which", lambda _binary: "/usr/bin/whisper-cli")

    class _Proc:
        returncode = 0
        stdout = "\n  the quick brown fox  \n"
        stderr = ""

    monkeypatch.setattr(adapters.subprocess, "run", lambda *a, **k: _Proc())
    assert adapters.transcribe("whisper-cpp", tmp_path / "a.wav") == "the quick brown fox"


def test_timeout_is_reported_not_swallowed(adapters, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(adapters.shutil, "which", lambda _binary: "/usr/bin/whisper-cli")

    def _boom(*_a, **_k):
        raise adapters.subprocess.TimeoutExpired(cmd="whisper-cli", timeout=adapters.TIMEOUT_S)

    monkeypatch.setattr(adapters.subprocess, "run", _boom)
    with pytest.raises(RuntimeError) as excinfo:
        adapters.transcribe("whisper-cpp", tmp_path / "a.wav")
    assert "exceeded" in str(excinfo.value)
