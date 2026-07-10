"""Fetch the Kokoro ONNX voice model for the Read-Back Loop.

Downloads the Kokoro-82M int8 ONNX model and its packed voices file from the
``kokoro-onnx`` GitHub release into the TTS model dir, under the filenames
:class:`~yazses.tts.kokoro.KokoroTtsBackend` expects. Explicit, on-demand,
one-time (~340 MB) — nothing downloads unless ``[tts] enabled`` and the files are
absent (ADR-011). Network/tooling dependent, so exercised manually, not in CI.
"""
from __future__ import annotations

import logging
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

_MODEL_FILE = "kokoro-v1.0.onnx"
_VOICES_FILE = "voices-v1.0.bin"

_RELEASE = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
)
_MODEL_URL = f"{_RELEASE}/{_MODEL_FILE}"
_VOICES_URL = f"{_RELEASE}/{_VOICES_FILE}"


def model_dir() -> Path:
    """Directory holding the Kokoro model + voices files."""
    from yazses.platform import get_platform

    return get_platform().paths.data_dir / "tts"


def model_paths() -> tuple[Path, Path]:
    """Return the (model, voices) file paths inside :func:`model_dir`."""
    d = model_dir()
    return d / _MODEL_FILE, d / _VOICES_FILE


def models_present() -> bool:
    """True when both Kokoro files exist locally."""
    model, voices = model_paths()
    return model.exists() and voices.exists()


def download_models(*, echo=print) -> tuple[Path, Path]:
    """Ensure both Kokoro files exist locally; return their (model, voices) paths."""
    model, voices = model_paths()
    model.parent.mkdir(parents=True, exist_ok=True)

    if not model.exists():
        echo(f"Downloading Kokoro model → {model} (~310 MB) …")
        _fetch(_MODEL_URL, model)
    else:
        echo(f"Kokoro model present: {model}")

    if not voices.exists():
        echo(f"Downloading Kokoro voices → {voices} (~27 MB) …")
        _fetch(_VOICES_URL, voices)
    else:
        echo(f"Kokoro voices present: {voices}")

    echo("Read-Back voice ready.")
    return model, voices


def _fetch(url: str, out_path: Path) -> None:
    """Download *url* to *out_path* via a temp file so a partial download never
    leaves a truncated model in place."""
    tmp = out_path.with_suffix(out_path.suffix + ".part")
    with urllib.request.urlopen(url) as resp:  # noqa: S310 - fixed https release URL
        tmp.write_bytes(resp.read())
    tmp.replace(out_path)
