"""The hosted Hugging Face demo: its pure validation, its Space card, and its app source.

`huggingface/space-demo/` is deployed as a Gradio Space and is not part of the installed
`yazses` package, so it is loaded here by path. Nothing in this file imports gradio or
`spaces`, and the one test that touches faster-whisper reads a model that is already in
the local cache; it never downloads one.

Static checks read the three Space files as text (or parse `app.py` with `ast`, which
does not execute it). They pin the properties the public page promises: the mandatory
privacy sentence renders above the audio input, the page does not claim to be offline,
and the app keeps no state, writes nothing and reports nothing.
"""

from __future__ import annotations

import ast
import importlib.util
import math
import os
import re
import wave
from pathlib import Path
from types import ModuleType

import pytest

from tests.decoder_stack import needs_faster_whisper

ROOT = Path(__file__).resolve().parent.parent
SPACE = ROOT / "huggingface" / "space-demo"

#: The sentence the Space card and the page must carry verbatim.
MANDATORY_PRIVACY = (
    "This is a hosted demonstration. Audio submitted here is processed on Hugging Face "
    "infrastructure. For private, offline voice typing, install YazSes on your own computer."
)
PAGE_TITLE = "YazSes — Hosted Speech Recognition Preview"
ARXIV_URL = "https://arxiv.org/abs/2607.28878"


def _load_validation() -> ModuleType:
    spec = importlib.util.spec_from_file_location("hf_space_validation", SPACE / "validation.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V = _load_validation()


def _write_wav(path: Path, seconds: float, rate: int = 16000) -> Path:
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * frames)
    return path


# --- upload validation -------------------------------------------------------------------


@pytest.mark.parametrize("ext", sorted(V.ALLOWED_EXTENSIONS))
def test_allowed_extension_is_accepted(tmp_path: Path, ext: str) -> None:
    clip = tmp_path / f"clip{ext}"
    clip.write_bytes(b"not really audio, but non-empty")
    assert V.check_upload(clip) == (True, "")


@pytest.mark.parametrize("name", ["clip.txt", "clip.exe", "clip.mp4", "clip", "clip.WAV.bak"])
def test_wrong_extension_is_rejected(tmp_path: Path, name: str) -> None:
    clip = tmp_path / name
    clip.write_bytes(b"x")
    ok, message = V.check_upload(clip)
    assert ok is False
    assert "not supported" in message


def test_uppercase_extension_is_accepted(tmp_path: Path) -> None:
    clip = tmp_path / "CLIP.WAV"
    clip.write_bytes(b"x")
    assert V.check_upload(clip)[0] is True


@pytest.mark.parametrize("path", [None, ""])
def test_missing_path_is_rejected(path) -> None:
    ok, message = V.check_upload(path)
    assert ok is False
    assert message


def test_nonexistent_file_is_rejected(tmp_path: Path) -> None:
    ok, message = V.check_upload(tmp_path / "gone.wav")
    assert ok is False
    assert "could not be found" in message


def test_directory_named_like_audio_is_rejected(tmp_path: Path) -> None:
    folder = tmp_path / "folder.wav"
    folder.mkdir()
    assert V.check_upload(folder)[0] is False


def test_empty_file_is_rejected(tmp_path: Path) -> None:
    clip = tmp_path / "empty.wav"
    clip.write_bytes(b"")
    ok, message = V.check_upload(clip)
    assert ok is False
    assert "empty" in message


def test_file_at_size_limit_is_accepted(tmp_path: Path) -> None:
    clip = tmp_path / "limit.wav"
    with clip.open("wb") as handle:
        handle.truncate(V.MAX_FILE_BYTES)  # sparse: no real 25 MB is written
    assert V.check_upload(clip) == (True, "")


def test_oversize_file_is_rejected(tmp_path: Path) -> None:
    clip = tmp_path / "big.wav"
    with clip.open("wb") as handle:
        handle.truncate(V.MAX_FILE_BYTES + 1)
    ok, message = V.check_upload(clip)
    assert ok is False
    assert "too large" in message


# --- duration bounds ----------------------------------------------------------------------


@pytest.mark.parametrize("seconds", [0.01, 1.0, 30.0, V.MAX_DURATION_SECONDS])
def test_duration_within_bounds_is_accepted(seconds: float) -> None:
    assert V.check_duration(seconds) == (True, "")


def test_duration_just_over_the_cap_is_rejected() -> None:
    ok, message = V.check_duration(V.MAX_DURATION_SECONDS + 0.5)
    assert ok is False
    assert "seconds long" in message


@pytest.mark.parametrize("seconds", [0.0, -1.0, math.nan, math.inf, -math.inf, None, "60"])
def test_non_positive_or_non_finite_duration_is_rejected(seconds) -> None:
    ok, message = V.check_duration(seconds)  # type: ignore[arg-type]
    assert ok is False
    assert message


def test_duration_cap_is_one_minute_for_the_gpu_slot() -> None:
    # The Space's decode runs inside @spaces.GPU(duration=60). A cap above 60 s would
    # let a single request exceed its own slot, so this guards a deliberate choice.
    assert V.MAX_DURATION_SECONDS <= 60


def test_wav_duration_is_read_from_the_header(tmp_path: Path) -> None:
    clip = _write_wav(tmp_path / "two.wav", seconds=2.0)
    assert V.wav_duration_seconds(clip) == pytest.approx(2.0)


def test_wav_duration_is_none_for_other_formats(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp3"
    clip.write_bytes(b"ID3 not really")
    assert V.wav_duration_seconds(clip) is None


def test_wav_duration_is_none_for_a_corrupt_wav(tmp_path: Path) -> None:
    clip = tmp_path / "broken.wav"
    clip.write_bytes(b"RIFF but not a wav file")
    assert V.wav_duration_seconds(clip) is None


# --- transcript formatting ----------------------------------------------------------------


@pytest.mark.parametrize(
    "pieces",
    [[], [""], ["   "], ["\n\t"], ["...", " , "], ["?!"], [None]],  # type: ignore[list-item]
)
def test_empty_or_silent_output_gets_the_no_speech_message(pieces) -> None:
    assert V.format_transcript(pieces) == V.NO_SPEECH_MESSAGE == "(no speech detected)"


def test_speech_is_joined_and_stripped() -> None:
    assert V.format_transcript(["  Hello there.", "", " how are you? "]) == "Hello there. how are you?"


def test_formatter_never_returns_an_empty_string() -> None:
    for pieces in ([], [" "], ["..."]):
        assert V.format_transcript(pieces).strip() != ""


# --- cleanup ------------------------------------------------------------------------------


def test_cleanup_removes_a_file_inside_the_temp_dir(tmp_path: Path) -> None:
    temp = tmp_path / "gradio-cache"
    temp.mkdir()
    inside = temp / "upload.wav"
    inside.write_bytes(b"x")
    assert V.safe_cleanup(inside, temp) is True
    assert not inside.exists()


def test_cleanup_never_touches_a_file_outside_the_temp_dir(tmp_path: Path) -> None:
    temp = tmp_path / "gradio-cache"
    temp.mkdir()
    outside = tmp_path / "notes.txt"
    outside.write_text("keep me", encoding="utf-8")
    assert V.safe_cleanup(outside, temp) is False
    assert outside.read_text(encoding="utf-8") == "keep me"


def test_cleanup_refuses_path_traversal_out_of_the_temp_dir(tmp_path: Path) -> None:
    temp = tmp_path / "gradio-cache"
    temp.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me", encoding="utf-8")
    assert V.safe_cleanup(temp / ".." / "victim.txt", temp) is False
    assert victim.exists()


def test_cleanup_refuses_the_temp_dir_itself_and_directories(tmp_path: Path) -> None:
    temp = tmp_path / "gradio-cache"
    sub = temp / "sub"
    sub.mkdir(parents=True)
    assert V.safe_cleanup(temp, temp) is False
    assert V.safe_cleanup(sub, temp) is False
    assert temp.is_dir() and sub.is_dir()


def test_cleanup_refuses_a_symlink_that_points_outside(tmp_path: Path) -> None:
    temp = tmp_path / "gradio-cache"
    temp.mkdir()
    target = tmp_path / "secret.txt"
    target.write_text("keep me", encoding="utf-8")
    link = temp / "link.wav"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available on this platform")
    assert V.safe_cleanup(link, temp) is False
    assert target.read_text(encoding="utf-8") == "keep me"


def test_cleanup_of_a_missing_path_is_a_quiet_false(tmp_path: Path) -> None:
    assert V.safe_cleanup(tmp_path / "missing.wav", tmp_path) is False


# --- the decoder, on a synthetic clip, when the stack and the model are present ----------


@needs_faster_whisper
def test_silence_through_the_real_decoder_gives_the_no_speech_message(tmp_path: Path) -> None:
    from faster_whisper import WhisperModel

    try:
        model = WhisperModel("base.en", device="cpu", compute_type="int8", local_files_only=True)
    except Exception as exc:  # noqa: BLE001 - any failure here means "not cached", skip
        pytest.skip(f"base.en is not in the local Hugging Face cache ({type(exc).__name__})")

    clip = _write_wav(tmp_path / "silence.wav", seconds=2.0)
    segments, info = model.transcribe(str(clip), beam_size=5, vad_filter=True)
    texts = [segment.text for segment in segments]

    assert info.duration == pytest.approx(2.0, abs=0.05)
    assert V.format_transcript(texts) == V.NO_SPEECH_MESSAGE


# --- the Space card ------------------------------------------------------------------------


def _readme() -> str:
    return (SPACE / "README.md").read_text(encoding="utf-8")


def _front_matter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    assert lines[0] == "---", "README.md must open with YAML front matter"
    end = lines.index("---", 1)
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip().strip("'\"")
    return fields


def test_readme_front_matter_is_a_gradio_space() -> None:
    fm = _front_matter(_readme())
    assert fm["sdk"] == "gradio"
    assert fm["sdk_version"] == "6.22.0"
    assert fm["python_version"] == "3.12"
    assert fm["app_file"] == "app.py"
    assert fm["pinned"] == "false"
    assert fm["license"] == "apache-2.0"


def test_readme_title_matches_the_page_title() -> None:
    fm = _front_matter(_readme())
    assert fm["title"] == PAGE_TITLE
    assert PAGE_TITLE in (SPACE / "app.py").read_text(encoding="utf-8")


def test_short_description_fits_the_hub_limit_and_says_what_it_is() -> None:
    short = _front_matter(_readme())["short_description"]
    assert len(short) <= 60, f"Hub short_description is capped at 60 characters: {len(short)}"
    assert short.startswith("Hosted preview of YazSes")
    assert "not the app" in short


def test_mandatory_privacy_sentence_is_verbatim_and_near_the_top() -> None:
    text = _readme()
    assert MANDATORY_PRIVACY in text
    assert text.index(MANDATORY_PRIVACY) < 800


def test_readme_links_the_paper_by_its_arxiv_url() -> None:
    text = _readme()
    assert ARXIV_URL in text


def test_readme_arxiv_url_matches_the_citation_file() -> None:
    cff = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    cited = re.findall(r"url:\s*(https://arxiv\.org/abs/\S+)", cff)
    assert cited, "CITATION.cff must carry the arXiv landing page"
    assert ARXIV_URL in cited


def test_readme_has_a_bibtex_entry_for_the_paper() -> None:
    text = _readme()
    assert "@article{" in text
    assert "arXiv:2607.28878" in text


def test_readme_cites_the_landing_page_not_a_pdf() -> None:
    assert not re.search(r"\.pdf\b", _readme(), flags=re.IGNORECASE)


def test_readme_does_not_claim_the_hosted_page_is_offline() -> None:
    text = _readme()
    assert "is not the YazSes desktop application" in text
    claim = r"(this (page|space|demo|app|tool)|the (demo|space|page))[^.\n]{0,80}\boffline\b"
    assert not re.search(claim, text, flags=re.IGNORECASE)


def test_requirements_floor_matches_the_pinned_gradio() -> None:
    reqs = (SPACE / "requirements.txt").read_text(encoding="utf-8")
    assert "gradio>=6.22.0" in reqs
    assert "faster-whisper>=1.2.1" in reqs


# --- the app source, parsed and never executed ---------------------------------------------

_APP = SPACE / "app.py"
_FORBIDDEN_IMPORTS = {
    "logging", "requests", "urllib", "urllib3", "httpx", "aiohttp", "socket", "http",
    "analytics", "sentry_sdk", "posthog", "wandb", "mixpanel", "telemetry", "subprocess",
}
_ALLOWED_MODULE_NAMES = {
    "PAGE_TITLE", "MODEL_NAME", "DEVICE", "COMPUTE_TYPE", "BEAM_SIZE", "VAD_FILTER",
    "PRIVACY_SENTENCE", "PRIVACY_NOTICE", "SETTINGS_LINE", "_model", "HEADER", "FOOTER",
}


def _app_text() -> str:
    return _APP.read_text(encoding="utf-8")


def _app_tree() -> ast.Module:
    return ast.parse(_app_text(), filename=str(_APP))


def test_privacy_notice_renders_above_the_audio_input() -> None:
    src = _app_text()
    assert MANDATORY_PRIVACY in src
    notice = src.index("gr.Markdown(PRIVACY_NOTICE)")
    audio = src.index("gr.Audio(")
    assert notice < audio


def test_no_print_calls_in_app() -> None:
    calls = [
        node for node in ast.walk(_app_tree())
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id in {"print", "open", "input"}
    ]
    assert calls == []


def test_app_imports_nothing_that_reports_or_logs() -> None:
    imported: set[str] = set()
    for node in ast.walk(_app_tree()):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & _FORBIDDEN_IMPORTS, imported & _FORBIDDEN_IMPORTS


def test_app_never_names_a_logger() -> None:
    names = {node.id for node in ast.walk(_app_tree()) if isinstance(node, ast.Name)}
    assert "logging" not in names
    assert "log" not in names


def test_module_level_state_is_only_the_lazy_model_and_constants() -> None:
    assigned: set[str] = set()
    for node in _app_tree().body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assigned.add(target.id)
    assert assigned <= _ALLOWED_MODULE_NAMES, assigned - _ALLOWED_MODULE_NAMES


def test_cpu_int8_and_the_gpu_slot_are_unchanged() -> None:
    src = _app_text()
    assert 'DEVICE = "cpu"' in src
    assert 'COMPUTE_TYPE = "int8"' in src
    assert 'MODEL_NAME = "base.en"' in src
    assert "@spaces.GPU(duration=60)" in src
    assert "BEAM_SIZE = 5" in src
    assert "VAD_FILTER = True" in src


def test_telemetry_is_disabled_in_the_gradio_blocks() -> None:
    assert "analytics_enabled=False" in _app_text()


def test_page_header_does_not_call_the_hosted_page_offline() -> None:
    match = re.search(r'HEADER = """(.*?)"""', _app_text(), flags=re.DOTALL)
    assert match is not None
    header = match.group(1)
    headings = [line for line in header.splitlines() if line.startswith("# ")]
    assert headings == [f"# {PAGE_TITLE}"]
    assert "offline" not in headings[0].lower()
    # Any sentence that mentions "offline" must be about the desktop app, not this page.
    for sentence in re.split(r"(?<=\.)\s+", header):
        if "offline" in sentence.lower():
            assert "desktop" in sentence.lower(), sentence
