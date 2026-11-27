"""The pure model registry and ``ensure_model`` (#929): fake caches, no network."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import yazses.cli as cli
from yazses.models import registry as reg

runner = CliRunner()


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    d = {k: tmp_path / k for k in ("hf", "slm", "tts", "diar", "gaze")}
    for p in d.values():
        p.mkdir()
    real = reg.build_registry

    def build(**kw):
        return real(
            hf_cache=d["hf"], slm_dir=d["slm"], tts_dir=d["tts"],
            diarization_dir=d["diar"], gaze_dir=d["gaze"],
        )

    monkeypatch.setattr(reg, "build_registry", build)
    monkeypatch.setattr("yazses.stt.download.hub_cache_dir", lambda: d["hf"])
    return d


def _stt_dir(hf: Path, repo: str) -> Path:
    p = hf / ("models--" + repo.replace("/", "--"))
    (p / "snapshots" / "x").mkdir(parents=True)
    (p / "snapshots" / "x" / "model.bin").write_bytes(b"x" * 2048)
    return p


def test_every_kind_is_listed_and_empty_cache_is_missing(dirs):
    entries = reg.build_registry()
    assert {e.kind for e in entries} == set(reg.KINDS)
    by_kind = {e.kind: e for e in entries}
    assert by_kind["vad"].state == "bundled"
    assert all(e.state == "missing" for e in entries if e.kind != "vad")
    assert all(e.owner for e in entries)


def test_present_models_report_state_and_bytes(dirs):
    _stt_dir(dirs["hf"], "Systran/faster-whisper-base.en")
    (dirs["tts"] / "kokoro-v1.0.onnx").write_bytes(b"a" * 10)
    (dirs["tts"] / "voices-v1.0.bin").write_bytes(b"b" * 5)
    (dirs["gaze"] / "face_landmarker.task").write_bytes(b"g" * 7)
    e = {x.id: x for x in reg.build_registry()}
    assert e["stt:base.en"].present and e["stt:base.en"].disk_bytes == 2048
    assert e["stt:base"].state == "missing"
    assert e["tts:kokoro"].disk_bytes == 15
    assert e["gaze:face-landmarker"].state == "present"
    assert e["diarization:sherpa"].state == "missing"


def test_one_of_two_files_is_not_present(dirs):
    (dirs["tts"] / "kokoro-v1.0.onnx").write_bytes(b"a")
    assert {x.id: x for x in reg.build_registry()}["tts:kokoro"].state == "missing"


def test_slm_truncated_file_is_not_present(dirs):
    from yazses.commands.model_manager import REGISTRY

    (dirs["slm"] / REGISTRY["qwen2.5-0.5b"].filename).write_bytes(b"tiny")
    assert {e.id: e for e in reg.build_registry()}["slm:qwen2.5-0.5b"].state == "missing"


def test_a_distil_checkpoint_does_not_make_its_suffix_namesake_present(dirs):
    _stt_dir(dirs["hf"], "Systran/faster-distil-whisper-small.en")
    e = {x.id: x for x in reg.build_registry()}
    assert e["stt:distil-small.en"].present
    assert e["stt:small.en"].state == "missing"


def test_find_entry_accepts_kind_prefix_or_unambiguous_bare_name(dirs):
    entries = reg.build_registry()
    found = reg.find_entry(entries, "stt:base.en")
    assert found is not None and found.id == "stt:base.en"
    found = reg.find_entry(entries, "kokoro")
    assert found is not None and found.id == "tts:kokoro"
    assert reg.find_entry(entries, "nope") is None


def test_disk_usage_counts_shared_cache_once(dirs):
    _stt_dir(dirs["hf"], "Systran/faster-whisper-large-v3")  # large and large-v3 share it
    usage = reg.disk_usage(reg.build_registry())
    assert usage["stt"] == 2048
    assert set(usage) == set(reg.KINDS)


def _ensure(policy, cached, calls, **kw):
    def dl(name):
        calls.append(name)
        return Path("/m") / name

    return reg.ensure_model("stt", "base.en", policy, is_cached=lambda n: cached, download=dl, **kw)


@pytest.mark.parametrize("policy", reg.POLICIES)
def test_cached_is_ready_under_every_policy_and_never_downloads(policy):
    calls: list[str] = []
    r = _ensure(policy, True, calls)
    assert r.status == "ready" and r.ok and not calls


def test_auto_downloads_when_missing():
    calls: list[str] = []
    r = _ensure("auto", False, calls)
    assert r.status == "downloaded" and r.ok and calls == ["base.en"]


def test_auto_reports_a_failed_download():
    def boom(name):
        raise OSError("blocked")

    r = reg.ensure_model("stt", "base.en", "auto", is_cached=lambda n: False, download=boom)
    assert r.status == "failed" and "blocked" in r.message and not r.ok


def test_ask_names_what_is_missing_and_size_without_downloading():
    calls: list[str] = []
    r = _ensure("ask", False, calls, size_mb=141)
    assert r.status == "missing" and not calls
    assert "base.en" in r.message and "141 MB" in r.message


def test_never_names_the_manual_route_without_downloading():
    calls: list[str] = []
    r = _ensure("never", False, calls, manual_hint="https://huggingface.co/x")
    assert r.status == "missing" and not calls and "https://huggingface.co/x" in r.message


def test_a_failed_download_can_be_reraised_unchanged():
    boom = OSError("blocked")

    def dl(name):
        raise boom

    r = reg.ensure_model("tts", "kokoro", "auto", is_cached=lambda n: False, download=dl)
    assert r.error is boom
    with pytest.raises(OSError) as caught:
        r.raise_for_failure()
    assert caught.value is boom


@pytest.mark.parametrize(("policy", "cached"), [("auto", True), ("auto", False), ("ask", False),
                                                ("never", False)])
def test_only_a_failure_raises(policy, cached):
    _ensure(policy, cached, []).raise_for_failure()


def _missing(kind, name, **kw):
    r = reg.ensure_model(
        kind, name, "ask", is_cached=lambda n: False,
        download=lambda n: pytest.fail("ask must not download"), **kw,
    )
    assert r.status == "missing"
    return r.message


@pytest.mark.parametrize(
    ("kind", "name", "command"),
    [
        ("stt", "base.en", "yazses model download base.en"),
        ("slm", "qwen2.5-0.5b", "yazses model download qwen2.5-0.5b"),
        ("diarization", "sherpa", "yazses transcribe --download-models"),
    ],
)
def test_ask_names_the_command_that_fetches_this_kind(kind, name, command):
    assert command in _missing(kind, name)


@pytest.mark.parametrize(
    ("kind", "name"),
    [("tts", "kokoro"), ("gaze", "face-landmarker"), ("stt", "someorg/some-ct2-model")],
)
def test_ask_never_names_a_command_that_cannot_fetch_the_model(kind, name):
    message = _missing(kind, name, manual_hint="https://example.invalid/m")
    assert "yazses model download" not in message
    assert "https://example.invalid/m" in message


# --- the first adopter: the Read-Back voice ----------------------------------------------


@pytest.fixture
def kokoro(tmp_path, monkeypatch):
    """`_resolve_models` on a backend whose heavy `__init__` never ran."""
    from yazses.tts.kokoro import KokoroTtsBackend

    paths = (tmp_path / "model.onnx", tmp_path / "voices.bin")
    monkeypatch.setattr("yazses.tts.download.model_paths", lambda: paths)
    backend = object.__new__(KokoroTtsBackend)
    backend._config = SimpleNamespace(model_path="", voices_path="")
    return backend, paths


@pytest.mark.parametrize("present", [0, 1])
def test_the_voice_is_fetched_when_either_file_is_missing(kokoro, monkeypatch, present):
    backend, paths = kokoro
    for p in paths[:present]:
        p.write_bytes(b"x")
    calls: list[int] = []
    monkeypatch.setattr("yazses.tts.download.download_models", lambda **kw: calls.append(1))
    assert backend._resolve_models() == (str(paths[0]), str(paths[1]))
    assert calls == [1]


def test_a_cached_voice_is_never_refetched(kokoro, monkeypatch):
    backend, paths = kokoro
    for p in paths:
        p.write_bytes(b"x")
    monkeypatch.setattr(
        "yazses.tts.download.download_models", lambda **kw: pytest.fail("must not download")
    )
    assert backend._resolve_models() == (str(paths[0]), str(paths[1]))


def test_a_blocked_voice_download_still_raises_its_own_error(kokoro, monkeypatch):
    backend, _ = kokoro

    def blocked(**kw):
        raise OSError("blocked by firewall")

    monkeypatch.setattr("yazses.tts.download.download_models", blocked)
    with pytest.raises(OSError, match="blocked by firewall"):
        backend._resolve_models()


def test_bad_kind_and_policy_are_rejected():
    with pytest.raises(ValueError):
        reg.ensure_model("zzz", "a", "auto", is_cached=lambda n: True, download=lambda n: None)
    with pytest.raises(ValueError):
        reg.ensure_model("stt", "a", "sometimes", is_cached=lambda n: True, download=lambda n: None)


def test_registry_import_pulls_in_no_network_or_heavy_module():
    code = (
        "import sys, yazses.models.registry;"
        "bad=[m for m in ('urllib.request','requests','httpx','huggingface_hub',"
        "'faster_whisper') if m in sys.modules];"
        "print(bad)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"


# --- CLI ---------------------------------------------------------------------------------


def test_cli_list_shows_every_kind(dirs):
    r = runner.invoke(cli.app, ["model", "list"], env={"COLUMNS": "200"})
    assert r.exit_code == 0, r.output
    for needle in ("Speech-to-text", "Voice activity", "Intent routing", "Read-Back", "diarization", "Gaze"):
        assert needle in r.output
    assert "silero" in r.output and "kokoro" in r.output and "base.en" in r.output


def test_cli_remove_deletes_a_cached_stt_model(dirs):
    folder = _stt_dir(dirs["hf"], "Systran/faster-whisper-base.en")
    r = runner.invoke(cli.app, ["model", "remove", "stt:base.en", "--yes"])
    assert r.exit_code == 0, r.output
    assert not folder.exists()


def test_cli_remove_asks_first_and_keeps_on_no(dirs):
    folder = _stt_dir(dirs["hf"], "Systran/faster-whisper-base.en")
    r = runner.invoke(cli.app, ["model", "remove", "stt:base.en"], input="n\n")
    assert r.exit_code == 0 and folder.exists()


def test_cli_remove_file_models_and_edge_cases(dirs):
    f = dirs["gaze"] / "face_landmarker.task"
    f.write_bytes(b"g")
    assert runner.invoke(cli.app, ["model", "remove", "gaze:face-landmarker", "-y"]).exit_code == 0
    assert not f.exists()
    r = runner.invoke(cli.app, ["model", "remove", "gaze:face-landmarker", "-y"])
    assert r.exit_code == 0 and "not downloaded" in r.output
    assert runner.invoke(cli.app, ["model", "remove", "vad:silero", "-y"]).exit_code == 1
    assert runner.invoke(cli.app, ["model", "remove", "nonsense", "-y"]).exit_code == 1


def test_cli_disk_reports_per_kind_and_total(dirs):
    _stt_dir(dirs["hf"], "Systran/faster-whisper-base.en")
    r = runner.invoke(cli.app, ["model", "disk"])
    assert r.exit_code == 0, r.output
    assert "stt" in r.output and "total" in r.output and "1 downloaded" in r.output
