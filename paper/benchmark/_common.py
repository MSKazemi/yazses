"""Shared helpers for the YazSes benchmark harness (arXiv paper).

Provenance capture, LibriSpeech subset loading, and audio I/O. Every result JSON
embeds a provenance block so a number is never quoted without the conditions it was
measured under (design/vision/PRINCIPLES.md).
"""
from __future__ import annotations

import json
import platform
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
PAPER_DIR = REPO_ROOT / "paper"
DATA_DIR = PAPER_DIR / "data"
RESULTS_DIR = PAPER_DIR / "results"
LIBRISPEECH_DIR = DATA_DIR / "LibriSpeech" / "test-clean"

SAMPLE_RATE = 16000


def _cpu_model() -> str:
    try:
        out = subprocess.run(
            ["lscpu"], capture_output=True, text=True, check=False
        ).stdout
        for line in out.splitlines():
            if line.strip().startswith("Model name:"):
                return line.split(":", 1)[1].strip()
    except Exception:  # pragma: no cover - best effort
        pass
    return platform.processor() or "unknown"


def _pkg_version(name: str) -> str:
    import importlib.metadata as m

    try:
        return m.version(name)
    except Exception:  # pragma: no cover
        return "unknown"


@dataclass
class Provenance:
    """Everything needed to interpret a measurement."""

    timestamp: str
    cpu_model: str
    logical_cpus: int
    ram_gb: float
    os: str
    kernel: str
    python: str
    faster_whisper: str
    yazses: str
    numpy: str
    compute_type: str = "int8"
    device: str = "cpu"


def provenance(timestamp: str) -> dict:
    import os

    import psutil

    p = Provenance(
        timestamp=timestamp,
        cpu_model=_cpu_model(),
        logical_cpus=os.cpu_count() or 0,
        ram_gb=round(psutil.virtual_memory().total / 1e9, 1),
        os=_os_pretty(),
        kernel=platform.release(),
        python=platform.python_version(),
        faster_whisper=_pkg_version("faster-whisper"),
        yazses=_pkg_version("yazses"),
        numpy=np.__version__,
    )
    return asdict(p)


def _os_pretty() -> str:
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"')
    except Exception:  # pragma: no cover
        pass
    return platform.platform()


def load_audio(flac_path: Path) -> np.ndarray:
    """Load a FLAC file as float32 mono at 16 kHz (LibriSpeech is already 16 kHz)."""
    import soundfile as sf

    audio, sr = sf.read(str(flac_path), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    assert sr == SAMPLE_RATE, f"expected {SAMPLE_RATE} Hz, got {sr}"
    return audio


def librispeech_subset(
    n: int, stratified: bool = True
) -> list[tuple[str, Path, str, float]]:
    """Return a deterministic subset of LibriSpeech test-clean.

    Each entry is ``(utt_id, flac_path, reference_text, duration_seconds)``.

    ``stratified=True`` (default) draws a **speaker-stratified** sample: it
    round-robins across all speakers (sorted), taking one utterance from each in
    turn until ``n`` are collected, so the subset spans the corpus's speakers
    rather than clustering on the lowest-numbered ids. Fully deterministic (no RNG).
    ``stratified=False`` keeps the legacy "first ``n`` by sorted id" behaviour
    (used for timing-only benches where speaker mix is irrelevant).
    """
    import soundfile as sf

    if not LIBRISPEECH_DIR.exists():
        raise FileNotFoundError(
            f"LibriSpeech test-clean not found at {LIBRISPEECH_DIR}. "
            "Download https://www.openslr.org/resources/12/test-clean.tar.gz "
            "into paper/data/ and extract it."
        )
    refs: dict[str, str] = {}
    for trans in LIBRISPEECH_DIR.rglob("*.trans.txt"):
        for line in trans.read_text().splitlines():
            utt_id, _, text = line.partition(" ")
            refs[utt_id] = text

    def _entry(utt_id: str):
        parts = utt_id.split("-")  # e.g. 7127-75946-0000
        flac = LIBRISPEECH_DIR / parts[0] / parts[1] / f"{utt_id}.flac"
        if not flac.exists():
            return None
        info = sf.info(str(flac))
        return (utt_id, flac, refs[utt_id], float(info.frames) / info.samplerate)

    if not stratified:
        entries: list[tuple[str, Path, str, float]] = []
        for utt_id in sorted(refs):
            e = _entry(utt_id)
            if e is not None:
                entries.append(e)
            if len(entries) >= n:
                break
        return entries

    # Speaker-stratified round-robin (deterministic).
    by_speaker: dict[str, list[str]] = {}
    for utt_id in sorted(refs):
        by_speaker.setdefault(utt_id.split("-")[0], []).append(utt_id)
    speakers = sorted(by_speaker)
    out: list[tuple[str, Path, str, float]] = []
    idx = 0
    while len(out) < n:
        progressed = False
        for spk in speakers:
            bucket = by_speaker[spk]
            if idx < len(bucket):
                progressed = True
                e = _entry(bucket[idx])
                if e is not None:
                    out.append(e)
                    if len(out) >= n:
                        break
        if not progressed:  # exhausted every speaker
            break
        idx += 1
    return out


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    return float(np.percentile(np.asarray(values, dtype=float), q))


def write_result(name: str, payload: dict) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=False))
    return path
